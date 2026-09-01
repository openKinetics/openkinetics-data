import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_datetime

from data_api.artifacts import ARTIFACT_DEFINITIONS, artifact_payload as artifact_file_payload
from data_api.models import (
    Measurement,
    Release,
    ReleaseArtifact,
    Sequence,
    SplitAssignment,
    Substrate,
)
from data_api.sequence_artifacts import resolve_sequence_id


DEFAULT_SAMPLE_PATH = "data/sample/openkinetics_demo_100.json"


def coalesce(value, default=""):
    return default if value is None else value


def ec_class(ec_number):
    if not ec_number:
        return ""
    return str(ec_number).split(".", 1)[0]


def parse_generated_at(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed:
        return parsed
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def metric_value(datapoint, metric):
    return datapoint.get("measurements", {}).get(metric, {}).get("value")


def metric_unit(datapoint, metric):
    return datapoint.get("measurements", {}).get(metric, {}).get("unit") or ""


def compact_evidence_summary(datapoint):
    evidence = datapoint.get("evidence", {})
    provenance = datapoint.get("provenance", {})
    bits = [
        "Verification: %s" % coalesce(evidence.get("verification_status"), "unknown"),
        "Evidence tier: %s" % coalesce(evidence.get("evidence_confidence_tier"), "unknown"),
        "Paper grounding: %s" % coalesce(evidence.get("paper_grounding_status"), "unknown"),
        "Source DB: %s" % coalesce(provenance.get("source_db"), "unknown"),
    ]
    pmid_count = provenance.get("pmid_count") or 0
    doi_count = provenance.get("doi_count") or 0
    if pmid_count or doi_count:
        bits.append("Literature IDs: %s PMID(s), %s DOI(s)" % (pmid_count, doi_count))
    if evidence.get("has_proof_excerpt"):
        bits.append("CatLog marks this row as having a proof excerpt.")
    return " ".join(bits)


def search_text_for(datapoint):
    enzyme = datapoint.get("enzyme", {})
    substrate = datapoint.get("substrate", {})
    evidence = datapoint.get("evidence", {})
    provenance = datapoint.get("provenance", {})
    sequence = datapoint.get("sequence", {})
    parts = [
        datapoint.get("record_key"),
        datapoint.get("measurement_key"),
        datapoint.get("review_key"),
        enzyme.get("name"),
        enzyme.get("ec_number"),
        enzyme.get("organism"),
        enzyme.get("primary_uniprot_id"),
        substrate.get("name"),
        substrate.get("inchi_key"),
        str(substrate.get("pubchem_cid") or ""),
        evidence.get("verification_status"),
        evidence.get("evidence_confidence_tier"),
        evidence.get("paper_grounding_status"),
        provenance.get("source_db"),
        sequence.get("sequence_variant_status"),
        sequence.get("mutation_signature"),
    ]
    return " ".join(str(part).lower() for part in parts if part not in (None, ""))


def upsert_sequence(datapoint):
    sequence = datapoint["sequence"]
    enzyme = datapoint["enzyme"]
    sequence_id = sequence.get("sequence_id") or resolve_sequence_id(sequence["sequence"])
    obj, _created = Sequence.objects.update_or_create(
        sequence_id=sequence_id,
        defaults={
            "primary_uniprot_id": enzyme.get("primary_uniprot_id") or "",
            "sequence": sequence["sequence"],
            "length": sequence.get("length") or len(sequence["sequence"]),
            "fasta_header": sequence.get("fasta_header") or "",
            "source": sequence.get("source") or "",
            "source_url": sequence.get("source_url") or "",
            "sequence_variant_status": sequence.get("sequence_variant_status") or "",
            "mutation_signature": sequence.get("mutation_signature") or "",
            "wild_type": sequence.get("wild_type"),
        },
    )
    return obj


def upsert_substrate(datapoint):
    substrate = datapoint["substrate"]
    obj, _created = Substrate.objects.update_or_create(
        substrate_id=substrate["substrate_id"],
        defaults={
            "name": substrate.get("name") or "",
            "pubchem_query": substrate.get("pubchem_query") or "",
            "pubchem_cid": substrate.get("pubchem_cid"),
            "smiles": substrate.get("smiles") or "",
            "canonical_smiles": substrate.get("canonical_smiles") or "",
            "isomeric_smiles": substrate.get("isomeric_smiles") or "",
            "inchi_key": substrate.get("inchi_key") or "",
            "iupac_name": substrate.get("iupac_name") or "",
            "molecular_formula": substrate.get("molecular_formula") or "",
            "source": substrate.get("source") or "",
            "source_url": substrate.get("source_url") or "",
        },
    )
    return obj


def create_measurement(release, datapoint, sequence, substrate):
    enzyme = datapoint["enzyme"]
    evidence = datapoint.get("evidence", {})
    provenance = datapoint.get("provenance", {})
    assay = datapoint.get("assay_conditions", {})
    return Measurement.objects.create(
        release=release,
        record_key=datapoint["record_key"],
        measurement_key=datapoint.get("measurement_key") or "",
        measurement_id=datapoint.get("measurement_id") or "",
        review_key=datapoint.get("review_key") or "",
        enzyme_name=enzyme.get("name") or "",
        ec_number=enzyme.get("ec_number") or "",
        ec_class=ec_class(enzyme.get("ec_number")),
        organism=enzyme.get("organism") or "",
        primary_uniprot_id=enzyme.get("primary_uniprot_id") or "",
        identity_resolution_state=enzyme.get("identity_resolution_state") or "",
        uniprot_candidate_ids=enzyme.get("uniprot_candidate_ids") or [],
        sequence=sequence,
        substrate=substrate,
        pair_id=datapoint.get("enzyme_substrate_pair", {}).get("pair_id") or "",
        kcat=metric_value(datapoint, "kcat"),
        kcat_unit=metric_unit(datapoint, "kcat"),
        km=metric_value(datapoint, "km"),
        km_unit=metric_unit(datapoint, "km"),
        ki=metric_value(datapoint, "ki"),
        ki_unit=metric_unit(datapoint, "ki"),
        kcat_over_km=metric_value(datapoint, "kcat_over_km"),
        kcat_over_km_unit=metric_unit(datapoint, "kcat_over_km"),
        ph=assay.get("ph"),
        temperature_c=assay.get("temperature_c"),
        temperature_k=assay.get("temperature_k"),
        temperature_display=assay.get("temperature_display") or "",
        source_db=provenance.get("source_db") or "",
        source_record_count=provenance.get("source_record_count") or 0,
        has_literature_id=bool(provenance.get("has_literature_id")),
        pmid_count=provenance.get("pmid_count") or 0,
        doi_count=provenance.get("doi_count") or 0,
        literature_id_count=provenance.get("literature_id_count") or 0,
        literature_linkage=provenance.get("literature_linkage") or "",
        verification_status=evidence.get("verification_status") or "",
        evidence_confidence_tier=evidence.get("evidence_confidence_tier") or "",
        paper_grounding_status=evidence.get("paper_grounding_status") or "",
        has_proof_excerpt=bool(evidence.get("has_proof_excerpt")),
        compact_evidence_summary=compact_evidence_summary(datapoint),
        raw=datapoint,
        search_text=search_text_for(datapoint),
    )


def import_splits(release, measurement, datapoint):
    split_map = {
        "random": "random_seed_20260810",
        "sequence_exclusive": "sequence_exclusive_sha256",
        "substrate_exclusive": "substrate_exclusive_sha256",
        "pair_exclusive": "pair_exclusive_sha256",
    }
    demo_splits = datapoint.get("demo_splits", {})
    rows = []
    for family, source_key in split_map.items():
        split = demo_splits.get(source_key)
        if split:
            rows.append(
                SplitAssignment(
                    release=release,
                    measurement=measurement,
                    split_family=family,
                    split=split,
                )
            )
    SplitAssignment.objects.bulk_create(rows)


def sync_artifacts(release):
    ReleaseArtifact.objects.filter(release=release).delete()
    rows = []
    for definition in ARTIFACT_DEFINITIONS:
        payload = artifact_file_payload(release.release_id, definition)
        rows.append(ReleaseArtifact(release=release, **payload))
    ReleaseArtifact.objects.bulk_create(rows)


class Command(BaseCommand):
    help = "Import the 100-record CatLog/OpenKinetics demo sample."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sample",
            default=str(settings.BASE_DIR / DEFAULT_SAMPLE_PATH),
            help="Path to openkinetics_demo_100.json.",
        )
        parser.add_argument(
            "--latest",
            action="store_true",
            default=True,
            help="Mark imported release as latest.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["sample"])
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        manifest = payload["manifest"]
        release_id = manifest["release_id"]
        schema = payload.get("schema") or {}
        release, _created = Release.objects.update_or_create(
            release_id=release_id,
            defaults={
                "title": manifest.get("title") or release_id,
                "generated_at": parse_generated_at(manifest.get("generated_at")),
                "record_count": manifest.get("record_count") or len(payload["datapoints"]),
                "manifest": manifest,
                "schema": schema,
                "attribution": manifest.get("attribution") or {},
                "source_sha256": manifest.get("source", {}).get("input_sha256") or "",
                "is_latest": bool(options["latest"]),
            },
        )
        if options["latest"]:
            Release.objects.exclude(pk=release.pk).update(is_latest=False)

        Measurement.objects.filter(release=release).delete()
        SplitAssignment.objects.filter(release=release).delete()

        count = 0
        for datapoint in payload["datapoints"]:
            sequence = upsert_sequence(datapoint)
            substrate = upsert_substrate(datapoint)
            measurement = create_measurement(release, datapoint, sequence, substrate)
            import_splits(release, measurement, datapoint)
            count += 1

        sync_artifacts(release)
        Sequence.objects.filter(measurements__isnull=True).delete()
        release.record_count = count
        release.save(update_fields=["record_count", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                "Imported %s measurements for release %s from %s" % (count, release_id, path)
            )
        )
