"""Build and persist release-level API payloads that are expensive to aggregate."""

from collections import Counter

from django.db.models import Count, Q
from django.utils import timezone

from .models import Measurement, Sequence, Substrate


# Increment this whenever the shape or meaning of a precomputed payload changes.
# Endpoints ignore payloads written by an older version and use their live-query
# fallback until the release is precomputed again.
PRECOMPUTATION_VERSION = 1

REVIEW_STATUS_LABELS = {
    "accepted": "Accepted",
    "accepted_identity_only": "Accepted (identity only)",
    "further_checks": "Further checks",
    "unreviewed_or_excluded": "Unreviewed or excluded",
}

ACCEPTED_VERIFICATION_STATUSES = ("corrected", "verified")
UNREVIEWED_VERIFICATION_STATUSES = ("unverified", "mathematically_inferred", "disputed")

COUNT_BUCKETS = (
    (1, 1, "1"),
    (2, 2, "2"),
    (3, 5, "3-5"),
    (6, 10, "6-10"),
    (11, 25, "11-25"),
    (26, 50, "26-50"),
    (51, 100, "51-100"),
    (101, None, "101+"),
)

INTERNAL_COUNT_KEYS = {
    "mutant_rows_using_variant_sequence",
    "mutant_rows_without_variant_sequence",
    "rows_marked_mutant",
    "rows_with_variant_sequence",
    "rows_with_wild_type_sequence",
}


def review_status_filter(review_status):
    if review_status == "accepted":
        return Q(
            verification_status__in=ACCEPTED_VERIFICATION_STATUSES,
            has_literature_id=True,
        )
    if review_status == "accepted_identity_only":
        return Q(
            verification_status__in=ACCEPTED_VERIFICATION_STATUSES,
            has_literature_id=False,
        )
    if review_status == "further_checks":
        return Q(verification_status="manual_review_required")
    if review_status == "unreviewed_or_excluded":
        return Q(verification_status__in=UNREVIEWED_VERIFICATION_STATUSES)
    return None


def review_status_counts(measurements):
    return {
        key: measurements.filter(review_status_filter(key)).count()
        for key in REVIEW_STATUS_LABELS
    }


def bucket_for_count(count):
    for minimum, maximum, label in COUNT_BUCKETS:
        if count >= minimum and (maximum is None or count <= maximum):
            return label
    return "unknown"


def bucketed_distribution(rows):
    counts = Counter()
    for row in rows:
        counts[bucket_for_count(row["datapoints"])] += 1
    return [
        {"bucket": label, "count": counts.get(label, 0)}
        for _minimum, _maximum, label in COUNT_BUCKETS
    ]


def public_release_counts(counts):
    counts = dict(counts or {})
    if "mutant_rows" not in counts:
        for legacy_key in (
            "rows_marked_mutant",
            "mutant_rows_using_variant_sequence",
            "rows_with_variant_sequence",
        ):
            if legacy_key in counts:
                counts["mutant_rows"] = counts[legacy_key]
                break
    if "wild_type_rows" not in counts and "datapoints" in counts and "mutant_rows" in counts:
        counts["wild_type_rows"] = max(counts["datapoints"] - counts["mutant_rows"], 0)
    return {
        key: value
        for key, value in counts.items()
        if key not in INTERNAL_COUNT_KEYS
    }


def release_counts_from_db(measurements, release):
    datapoints = measurements.count()
    mutant_rows = measurements.filter(sequence__wild_type=False).count()
    return {
        "datapoints": datapoints,
        "unique_sequences": Sequence.objects.filter(measurements__release=release)
        .distinct()
        .count(),
        "unique_substrates": Substrate.objects.filter(measurements__release=release)
        .distinct()
        .count(),
        "unique_ec_numbers": measurements.exclude(ec_number="")
        .values("ec_number")
        .distinct()
        .count(),
        "rows_with_kcat": measurements.filter(kcat__isnull=False).count(),
        "rows_with_km": measurements.filter(km__isnull=False).count(),
        "rows_with_both_kcat_and_km": measurements.filter(
            kcat__isnull=False,
            km__isnull=False,
        ).count(),
        "mutant_rows": mutant_rows,
        "wild_type_rows": datapoints - mutant_rows,
    }


def build_stats(release):
    """Return the counts object served by the stats endpoint."""
    measurements = Measurement.objects.filter(release=release)
    return {
        "measurements": measurements.count(),
        "sequences": Sequence.objects.filter(measurements__release=release).distinct().count(),
        "substrates": Substrate.objects.filter(measurements__release=release).distinct().count(),
        "ec_numbers": measurements.exclude(ec_number="")
        .values("ec_number")
        .distinct()
        .count(),
        "rows_with_kcat": measurements.filter(kcat__isnull=False).count(),
        "rows_with_km": measurements.filter(km__isnull=False).count(),
        "rows_with_both_kcat_and_km": measurements.filter(
            kcat__isnull=False,
            km__isnull=False,
        ).count(),
    }


def build_facets(release):
    """Return the facets object served by the facets endpoint."""
    measurements = Measurement.objects.filter(release=release)
    return {
        "ec_classes": list(
            measurements.exclude(ec_class="")
            .values("ec_class")
            .annotate(count=Count("id"))
            .order_by("ec_class")
        ),
        "source_dbs": list(
            measurements.exclude(source_db="")
            .values("source_db")
            .annotate(count=Count("id"))
            .order_by("source_db")
        ),
        "verification_statuses": list(
            measurements.exclude(verification_status="")
            .values("verification_status")
            .annotate(count=Count("id"))
            .order_by("verification_status")
        ),
        "review_statuses": [
            {
                "review_status": key,
                "label": label,
                "count": count,
            }
            for key, label in REVIEW_STATUS_LABELS.items()
            if (count := measurements.filter(review_status_filter(key)).count())
        ],
        "evidence_tiers": list(
            measurements.exclude(evidence_confidence_tier="")
            .values("evidence_confidence_tier")
            .annotate(count=Count("id"))
            .order_by("evidence_confidence_tier")
        ),
        "organisms": list(
            measurements.exclude(organism="")
            .values("organism")
            .annotate(count=Count("id"))
            .order_by("-count", "organism")[:30]
        ),
    }


def build_download_stats(release):
    """Return the stats object embedded in the downloads endpoint response."""
    measurements = Measurement.objects.filter(release=release)
    manifest = release.manifest if isinstance(release.manifest, dict) else {}

    enzyme_rows = list(
        measurements.values("enzyme_name", "ec_number", "organism", "primary_uniprot_id")
        .annotate(datapoints=Count("id"))
        .order_by(
            "-datapoints",
            "enzyme_name",
            "ec_number",
            "organism",
            "primary_uniprot_id",
        )
    )
    substrate_rows = list(
        measurements.values("substrate__name", "substrate__substrate_id")
        .annotate(datapoints=Count("id"))
        .order_by("-datapoints", "substrate__name", "substrate__substrate_id")
    )

    return {
        "counts": public_release_counts(
            manifest.get("counts") or release_counts_from_db(measurements, release)
        ),
        "source_db_counts": manifest.get("source_db_counts")
        or dict(
            measurements.exclude(source_db="")
            .values_list("source_db")
            .annotate(count=Count("id"))
            .order_by("source_db")
        ),
        "verification_status_counts": manifest.get("verification_status_counts")
        or dict(
            measurements.exclude(verification_status="")
            .values_list("verification_status")
            .annotate(count=Count("id"))
            .order_by("verification_status")
        ),
        "review_status_counts": review_status_counts(measurements),
        "eligibility": manifest.get("eligibility") or {},
        "distributions": {
            "enzyme_datapoints": bucketed_distribution(enzyme_rows),
            "substrate_datapoints": bucketed_distribution(substrate_rows),
        },
        "top_enzymes": [
            {
                "enzyme_name": row["enzyme_name"],
                "ec_number": row["ec_number"],
                "organism": row["organism"],
                "primary_uniprot_id": row["primary_uniprot_id"],
                "datapoints": row["datapoints"],
            }
            for row in enzyme_rows[:10]
        ],
        "top_substrates": [
            {
                "substrate_name": row["substrate__name"],
                "substrate_id": row["substrate__substrate_id"],
                "datapoints": row["datapoints"],
            }
            for row in substrate_rows[:10]
        ],
    }


def precompute_release(release):
    """Build all release payloads and save them in one model update."""
    stats = build_stats(release)
    facets = build_facets(release)
    download_stats = build_download_stats(release)

    release.precomputed_stats = stats
    release.precomputed_facets = facets
    release.precomputed_download_stats = download_stats
    release.precomputation_version = PRECOMPUTATION_VERSION
    release.precomputed_at = timezone.now()
    release.save(
        update_fields=[
            "precomputed_stats",
            "precomputed_facets",
            "precomputed_download_stats",
            "precomputation_version",
            "precomputed_at",
            "updated_at",
        ]
    )
    return {
        "stats": stats,
        "facets": facets,
        "download_stats": download_stats,
    }


def current_precomputed_payload(release, field_name):
    """Return a valid current-version payload, or None to request a live fallback."""
    if release.precomputation_version != PRECOMPUTATION_VERSION:
        return None
    payload = getattr(release, field_name, None)
    if not isinstance(payload, dict) or not payload:
        return None
    return payload
