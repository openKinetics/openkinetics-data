from collections import defaultdict

from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404

from .models import Measurement, Release, ReleaseArtifact, Sequence, Substrate
from .release_precomputation import (
    build_download_stats,
    build_facets,
    build_stats,
    current_precomputed_payload,
    review_status_filter,
)
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


def stats(_request):
    release = latest_release()
    if not release:
        return JsonResponse({"release": None, "counts": {}})

    counts = current_precomputed_payload(release, "precomputed_stats") or build_stats(release)
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
            "stats": current_precomputed_payload(release, "precomputed_download_stats")
            or build_download_stats(release),
            "groups": dict(groups),
        }
    )


def facets(_request):
    release = latest_release()
    if not release:
        return JsonResponse({"facets": {}})
    facets_payload = current_precomputed_payload(release, "precomputed_facets") or build_facets(
        release
    )
    return JsonResponse({"facets": facets_payload})


def search(request):
    # Alias kept explicit for clients that expect a dedicated search route.
    return measurements(request)
