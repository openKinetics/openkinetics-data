from collections import Counter, defaultdict

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404

from .models import Measurement, Release, ReleaseArtifact, Sequence, Substrate
from .sequence_artifacts import (
    EMBEDDING_ARTIFACT_KEYS,
    SEQUENCE_ARTIFACT_DEFINITIONS,
    artifact_path,
    sequence_artifact_archive,
)
from .serializers import (
    artifact_payload,
    measurement_detail,
    measurement_summary,
    release_payload,
    sequence_payload,
    substrate_payload,
)


def latest_release():
    release = Release.objects.filter(is_latest=True).first()
    if release:
        return release
    return Release.objects.order_by("-generated_at", "-created_at").first()


def parse_int(value, default, minimum=1, maximum=200):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def parse_bool(value):
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "y"):
        return True
    if normalized in ("0", "false", "no", "n"):
        return False
    return None


REVIEW_STATUS_LABELS = {
    "accepted": "Accepted",
    "accepted_identity_only": "Accepted (identity only)",
    "further_checks": "Further checks",
    "unreviewed_or_excluded": "Unreviewed or excluded",
}

ACCEPTED_VERIFICATION_STATUSES = ("corrected", "verified")
UNREVIEWED_VERIFICATION_STATUSES = ("unverified", "mathematically_inferred", "disputed")


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


def apply_measurement_filters(queryset, params):
    q = (params.get("q") or "").strip()
    if q:
        queryset = queryset.filter(search_text__icontains=q.lower())

    requested_review_status = (params.get("review_status") or "").strip()
    review_filter = review_status_filter(requested_review_status)
    if review_filter is not None:
        queryset = queryset.filter(review_filter)

    enzyme_identity = parse_bool(params.get("enzyme_identity"))
    if enzyme_identity is True:
        queryset = queryset.filter(
            enzyme_name=(params.get("enzyme_name") or "").strip(),
            ec_number=(params.get("ec_number_exact") or params.get("ec_number") or "").strip(),
            organism=(params.get("organism_exact") or params.get("organism") or "").strip(),
        )
        uniprot = (params.get("uniprot") or params.get("primary_uniprot_id") or "").strip()
        if uniprot:
            queryset = queryset.filter(primary_uniprot_id__iexact=uniprot)
        else:
            queryset = queryset.filter(primary_uniprot_id="")

    exact_filters = {
        "ec_class": "ec_class",
        "source_db": "source_db",
        "verification_status": "verification_status",
        "evidence_confidence_tier": "evidence_confidence_tier",
        "paper_grounding_status": "paper_grounding_status",
        "enzyme_name": "enzyme_name__iexact",
        "ec_number_exact": "ec_number__iexact",
        "organism_exact": "organism__iexact",
        "primary_uniprot_id": "primary_uniprot_id__iexact",
        "organism": "organism__icontains",
        "ec_number": "ec_number__startswith",
        "uniprot": "primary_uniprot_id__iexact",
        "substrate": "substrate__name__icontains",
    }
    for param, lookup in exact_filters.items():
        value = (params.get(param) or "").strip()
        if value:
            queryset = queryset.filter(**{lookup: value})

    has_kcat = parse_bool(params.get("has_kcat"))
    if has_kcat is True:
        queryset = queryset.filter(kcat__isnull=False)
    elif has_kcat is False:
        queryset = queryset.filter(kcat__isnull=True)

    has_km = parse_bool(params.get("has_km"))
    if has_km is True:
        queryset = queryset.filter(km__isnull=False)
    elif has_km is False:
        queryset = queryset.filter(km__isnull=True)

    wild_type = parse_bool(params.get("wild_type"))
    if wild_type is not None:
        queryset = queryset.filter(sequence__wild_type=wild_type)

    for param, lookup in (
        ("ph_min", "ph__gte"),
        ("ph_max", "ph__lte"),
        ("temperature_min", "temperature_c__gte"),
        ("temperature_max", "temperature_c__lte"),
    ):
        value = params.get(param)
        if value not in (None, ""):
            try:
                queryset = queryset.filter(**{lookup: float(value)})
            except ValueError:
                pass

    return queryset


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
        "unique_sequences": Sequence.objects.filter(measurements__release=release).distinct().count(),
        "unique_substrates": Substrate.objects.filter(measurements__release=release).distinct().count(),
        "unique_ec_numbers": measurements.exclude(ec_number="").values("ec_number").distinct().count(),
        "rows_with_kcat": measurements.filter(kcat__isnull=False).count(),
        "rows_with_km": measurements.filter(km__isnull=False).count(),
        "rows_with_both_kcat_and_km": measurements.filter(
            kcat__isnull=False,
            km__isnull=False,
        ).count(),
        "mutant_rows": mutant_rows,
        "wild_type_rows": datapoints - mutant_rows,
    }


def release_download_stats(release):
    measurements = Measurement.objects.filter(release=release)
    manifest = release.manifest if isinstance(release.manifest, dict) else {}

    enzyme_rows = list(
        measurements.values("enzyme_name", "ec_number", "organism", "primary_uniprot_id")
        .annotate(datapoints=Count("id"))
        .order_by("-datapoints", "enzyme_name", "ec_number", "organism", "primary_uniprot_id")
    )
    substrate_rows = list(
        measurements.values("substrate__name", "substrate__substrate_id")
        .annotate(datapoints=Count("id"))
        .order_by("-datapoints", "substrate__name", "substrate__substrate_id")
    )

    return {
        "counts": public_release_counts(manifest.get("counts") or release_counts_from_db(measurements, release)),
        "source_db_counts": manifest.get("source_db_counts") or dict(
            measurements.exclude(source_db="")
            .values_list("source_db")
            .annotate(count=Count("id"))
            .order_by("source_db")
        ),
        "verification_status_counts": manifest.get("verification_status_counts") or dict(
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


def stats(_request):
    release = latest_release()
    if not release:
        return JsonResponse({"release": None, "counts": {}})

    measurements = Measurement.objects.filter(release=release)
    counts = {
        "measurements": measurements.count(),
        "sequences": Sequence.objects.filter(measurements__release=release).distinct().count(),
        "substrates": Substrate.objects.filter(measurements__release=release).distinct().count(),
        "ec_numbers": measurements.exclude(ec_number="").values("ec_number").distinct().count(),
        "rows_with_kcat": measurements.filter(kcat__isnull=False).count(),
        "rows_with_km": measurements.filter(km__isnull=False).count(),
        "rows_with_both_kcat_and_km": measurements.filter(kcat__isnull=False, km__isnull=False).count(),
    }
    return JsonResponse({"release": release_payload(release), "counts": counts})


def releases(_request):
    payload = [release_payload(row) for row in Release.objects.all()]
    return JsonResponse({"releases": payload})


def release_latest(_request):
    release = latest_release()
    if not release:
        return JsonResponse({"release": None}, status=404)
    return JsonResponse({"release": release_payload(release, include_manifest=True)})


def release_detail(_request, release_id):
    release = get_object_or_404(Release, release_id=release_id)
    return JsonResponse({"release": release_payload(release, include_manifest=True)})


def measurements(request):
    release = latest_release()
    if not release:
        return JsonResponse({"results": [], "pagination": {"total": 0}})

    queryset = (
        Measurement.objects.filter(release=release)
        .select_related("sequence", "substrate", "release")
        .prefetch_related("split_assignments")
    )
    queryset = apply_measurement_filters(queryset, request.GET)
    queryset = queryset.order_by("enzyme_name", "substrate__name", "record_key")

    page_number = parse_int(request.GET.get("page"), 1, maximum=100000)
    page_size = parse_int(request.GET.get("page_size"), 25, maximum=100)
    paginator = Paginator(queryset, page_size)
    page = paginator.get_page(page_number)

    return JsonResponse(
        {
            "release": release_payload(release),
            "results": [measurement_summary(row) for row in page.object_list],
            "pagination": {
                "page": page.number,
                "page_size": page_size,
                "total": paginator.count,
                "pages": paginator.num_pages,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
            },
        }
    )


def measurement_record(request, record_key):
    release = latest_release()
    queryset = (
        Measurement.objects.select_related("release", "sequence", "substrate")
        .prefetch_related("split_assignments")
    )
    if release:
        queryset = queryset.filter(release=release)
    measurement = get_object_or_404(queryset, record_key=record_key)
    return JsonResponse({"measurement": measurement_detail(measurement)})


def sequence_detail(_request, sequence_id):
    sequence = get_object_or_404(Sequence, sequence_id=sequence_id)
    return JsonResponse({"sequence": sequence_payload(sequence, include_sequence=True)})


def sequence_artifact_download(_request, sequence_id, artifact_key):
    sequence = get_object_or_404(Sequence, sequence_id=sequence_id)
    definition = SEQUENCE_ARTIFACT_DEFINITIONS.get(artifact_key)
    if not definition:
        raise Http404("Unknown sequence artifact.")
    path = artifact_path(sequence.sequence_id, artifact_key)
    if not path or not path.exists() or not path.is_file():
        raise Http404("Sequence artifact is not available.")
    archive = sequence_artifact_archive(sequence, artifact_key, path)
    filename = "%s_%s" % (sequence.sequence_id, definition["download_filename_suffix"])
    return FileResponse(
        archive,
        as_attachment=True,
        filename=filename,
        content_type=definition["content_type"],
    )


def raw_embedding_artifact_download(_request, artifact_key, sequence_id):
    definition = SEQUENCE_ARTIFACT_DEFINITIONS.get(artifact_key)
    if not definition or artifact_key not in EMBEDDING_ARTIFACT_KEYS:
        raise Http404("Unknown embedding artifact.")
    path = artifact_path(sequence_id, artifact_key)
    if not path or not path.exists() or not path.is_file():
        raise Http404("Embedding artifact is not available.")
    return FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename="%s.npy" % sequence_id,
        content_type="application/octet-stream",
    )


def substrate_detail(_request, substrate_id):
    substrate = get_object_or_404(Substrate, substrate_id=substrate_id)
    return JsonResponse({"substrate": substrate_payload(substrate)})


def downloads(_request):
    release = latest_release()
    if not release:
        return JsonResponse({"release": None, "groups": {}})
    groups = defaultdict(list)
    for artifact in ReleaseArtifact.objects.filter(release=release):
        groups[artifact.family].append(artifact_payload(artifact))
    return JsonResponse(
        {
            "release": release_payload(release),
            "stats": release_download_stats(release),
            "groups": dict(groups),
        }
    )


def facets(_request):
    release = latest_release()
    if not release:
        return JsonResponse({"facets": {}})
    measurements = Measurement.objects.filter(release=release)
    facets_payload = {
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
    return JsonResponse({"facets": facets_payload})


def search(request):
    # Alias kept explicit for clients that expect a dedicated search route.
    return measurements(request)
