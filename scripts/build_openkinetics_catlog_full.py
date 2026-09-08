#!/usr/bin/env python3
"""Build a full OpenKinetics JSON artifact from CatLog enriched JSONL.

The output keeps the same high-level shape as
data/sample/openkinetics_demo_100.json, but does not perform UniProt or PubChem
network lookups. It uses resolved sequences and source SMILES already present in
catlog-enriched.jsonl.gz.
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SOURCE_CANDIDATES = (
    "data/catlog-enriched.jsonl.gz",
    "data/sample/catlog-enriched.jsonl.gz",
)
DEFAULT_OUTPUT = "data/openkinetics_catlog_full.json"
DEFAULT_RELEASE_ID = "openkinetics-catlog-full-2026-09"
TRUNCATED_ARTIFACT_N_TERMINAL_RESIDUES = 512
TRUNCATED_ARTIFACT_C_TERMINAL_RESIDUES = 512
TRUNCATED_ARTIFACT_INPUT_LENGTH = (
    TRUNCATED_ARTIFACT_N_TERMINAL_RESIDUES + TRUNCATED_ARTIFACT_C_TERMINAL_RESIDUES
)
DEFAULT_SEQMAP_DB = os.environ.get(
    "OPENKINETICS_SEQMAP_DB",
    os.path.join(os.environ.get("OPENKINETICS_SEQUENCE_INFO_ROOT", "/sequence_info"), "seqmap.sqlite3"),
)

ACCESSION_RE = re.compile(r"^[A-Z0-9]+(?:-\d+)?$")
AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYXBZUO]+$")


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_source():
    for candidate in DEFAULT_SOURCE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return DEFAULT_SOURCE_CANDIDATES[0]


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(prefix, *parts):
    payload = "\x1f".join("" if part is None else str(part) for part in parts)
    return "%s_%s" % (prefix, sha256_text(payload)[:16])


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value):
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


def clean_sequence(value):
    sequence = normalize_text(value)
    if not sequence:
        return None
    sequence = sequence.replace(" ", "").upper()
    if not AA_RE.match(sequence):
        return None
    return sequence


def substrate_name(record):
    name = record.get("substrate_name")
    if name is None:
        name = record.get("substrate")
    return normalize_text(name)


def valid_accession(accession):
    if not accession:
        return False
    accession = str(accession).strip()
    if not accession or accession.lower() in ("unknown", "none", "null"):
        return False
    return bool(ACCESSION_RE.match(accession))


def has_value(record, key):
    value = record.get(key)
    return isinstance(value, (int, float)) and value > 0


def value_unit_ok(record, value_key, unit_key):
    if not has_value(record, value_key):
        return True
    unit = record.get(unit_key)
    return isinstance(unit, str) and bool(unit.strip())


def is_mutant_record(record):
    mutation_type = normalize_text(record.get("mutation_type"))
    mutation_signature = normalize_text(record.get("mutation_signature"))
    if record.get("wild_type") is False:
        return True
    if mutation_type and mutation_type != "wild_type":
        return True
    if mutation_signature and mutation_signature.lower() not in ("unknown", "wild_type", "wt", "none"):
        return True
    return False


def selected_sequence(record):
    variant_sequence = clean_sequence(record.get("variant_sequence"))
    source_sequence = clean_sequence(record.get("sequence"))
    if is_mutant_record(record):
        if variant_sequence:
            return variant_sequence, "variant_sequence"
        return None, "missing_variant_sequence"
    return source_sequence, "sequence"


def sequence_artifact_input_sequence(sequence):
    if len(sequence) <= TRUNCATED_ARTIFACT_INPUT_LENGTH:
        return sequence
    return (
        sequence[:TRUNCATED_ARTIFACT_N_TERMINAL_RESIDUES]
        + sequence[-TRUNCATED_ARTIFACT_C_TERMINAL_RESIDUES:]
    )


def sequence_artifact_generation_payload(sequence):
    input_sequence = sequence_artifact_input_sequence(sequence)
    was_truncated = len(input_sequence) != len(sequence)
    payload = {
        "input_sequence_was_truncated": was_truncated,
        "input_strategy": "first_512_last_512" if was_truncated else "full_sequence",
        "original_sequence_length": len(sequence),
        "input_sequence_length": len(input_sequence),
        "input_sequence_sha256": sha256_text(input_sequence),
    }
    if was_truncated:
        payload.update(
            {
                "truncation_n_terminal_residues": TRUNCATED_ARTIFACT_N_TERMINAL_RESIDUES,
                "truncation_c_terminal_residues": TRUNCATED_ARTIFACT_C_TERMINAL_RESIDUES,
                "truncation_note": (
                    "Sequence artifact arrays are stored under the original sequence_id, "
                    "but model input used the first 512 and last 512 residues."
                ),
            }
        )
    return payload


def eligibility_reason(record, require_smiles=True):
    if is_mutant_record(record) and clean_sequence(record.get("variant_sequence")) is None:
        return "mutant_without_variant_sequence"
    sequence = selected_sequence(record)[0]
    if sequence is None:
        return "missing_or_invalid_sequence"
    if not has_value(record, "kcat") and not has_value(record, "km"):
        return "missing_positive_kcat_or_km"
    for value_key, unit_key in (
        ("kcat", "kcat_unit"),
        ("km", "km_unit"),
        ("ki", "ki_unit"),
        ("kcat_over_km", "kcat_over_km_unit"),
    ):
        if not value_unit_ok(record, value_key, unit_key):
            return "missing_unit_for_%s" % value_key
    if substrate_name(record) is None:
        return "missing_substrate_name"
    if require_smiles and normalize_text(record.get("smiles")) is None:
        return "missing_smiles"
    if record.get("verification_status") == "disputed":
        return "disputed"
    return None


class SequenceIdResolver:
    def __init__(self, seqmap_db=None):
        self.connection = None
        if seqmap_db and os.path.exists(seqmap_db):
            try:
                uri = "file:%s?mode=ro" % os.path.abspath(seqmap_db)
                self.connection = sqlite3.connect(uri, uri=True)
            except sqlite3.Error:
                self.connection = None

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def resolve(self, sequence):
        digest = sha256_text(sequence)
        if self.connection is not None:
            try:
                row = self.connection.execute("SELECT id FROM sequences WHERE sha256=?", (digest,)).fetchone()
                if row and row[0]:
                    return row[0]
            except sqlite3.Error:
                pass
        return digest[:12]


def substrate_id_for(substrate_name, smiles):
    if smiles:
        return "smiles:%s" % sha256_text(smiles)[:16]
    return stable_id("substrate", substrate_name)


def metric_payload(record, value_key, unit_key, display_key):
    value = record.get(value_key)
    return {
        "value": value,
        "unit": record.get(unit_key) or None,
        "display": record.get(display_key),
        "available": value is not None,
    }


def assign_split(identifier, ratios=(0.8, 0.1, 0.1)):
    value = int(hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:8], 16) / float(0xFFFFFFFF)
    if value < ratios[0]:
        return "train"
    if value < ratios[0] + ratios[1]:
        return "val"
    return "test"


def uniprot_url(accession):
    if not accession:
        return None
    return "https://www.uniprot.org/uniprotkb/%s/entry" % accession


def build_datapoint(record, line_number, sequence_resolver):
    sequence, assayed_sequence_source = selected_sequence(record)
    sequence_id = sequence_resolver.resolve(sequence)
    substrate = substrate_name(record)
    smiles = normalize_text(record.get("smiles"))
    substrate_id = substrate_id_for(substrate, smiles)
    is_mutant = is_mutant_record(record)
    wild_type_sequence = clean_sequence(record.get("wild_type_sequence"))
    variant_sequence = clean_sequence(record.get("variant_sequence"))
    pair_id = stable_id(
        "pair",
        sequence_id,
        substrate_id,
        record.get("mutation_signature"),
    )
    measurement_key = record.get("measurement_key")
    measurement_id = stable_id("meas", measurement_key, sequence_id, substrate_id)

    return {
        "record_key": record.get("record_key"),
        "measurement_key": measurement_key,
        "measurement_id": measurement_id,
        "review_key": record.get("review_key"),
        "enzyme": {
            "name": record.get("enzyme_display_name"),
            "label_source": record.get("enzyme_label_source"),
            "name_source": record.get("enzyme_name_source"),
            "ec_number": record.get("ec_number"),
            "organism": record.get("organism"),
            "primary_uniprot_id": record.get("primary_uniprot_id"),
            "uniprot_candidate_ids": record.get("uniprot_candidate_ids") or [],
            "identity_resolution_state": record.get("identity_resolution_state"),
        },
        "sequence": {
            "sequence_id": sequence_id,
            "sequence": sequence,
            "length": len(sequence),
            "source": "CatLog enriched JSONL sequence",
            "source_url": uniprot_url(record.get("primary_uniprot_id")),
            "fasta_header": None,
            "has_sequence": record.get("has_sequence"),
            "sequence_resolved": record.get("sequence_resolved"),
            "sequence_source_confidence": record.get("sequence_source_confidence"),
            "sequence_variant_status": record.get("sequence_variant_status"),
            "mutation_signature": record.get("mutation_signature"),
            "wild_type": record.get("wild_type"),
            "is_mutant": is_mutant,
            "mutation_type": record.get("mutation_type"),
            "wild_type_sequence": wild_type_sequence,
            "variant_sequence": variant_sequence,
            "sequence_variant_note": record.get("sequence_variant_note"),
            "assayed_sequence_source": assayed_sequence_source,
            "sequence_artifact_generation": sequence_artifact_generation_payload(sequence),
        },
        "substrate": {
            "substrate_id": substrate_id,
            "name": substrate,
            "pubchem_query": None,
            "pubchem_cid": None,
            "canonical_smiles": None,
            "isomeric_smiles": None,
            "smiles": smiles,
            "inchi_key": None,
            "iupac_name": None,
            "molecular_formula": None,
            "source": "CatLog enriched JSONL SMILES",
            "source_url": None,
        },
        "enzyme_substrate_pair": {
            "pair_id": pair_id,
            "sequence_id": sequence_id,
            "substrate_id": substrate_id,
        },
        "measurements": {
            "kcat": metric_payload(record, "kcat", "kcat_unit", "kcat_display"),
            "km": metric_payload(record, "km", "km_unit", "km_display"),
            "ki": metric_payload(record, "ki", "ki_unit", "ki_display"),
            "kcat_over_km": metric_payload(
                record,
                "kcat_over_km",
                "kcat_over_km_unit",
                "kcat_over_km_display",
            ),
        },
        "assay_conditions": {
            "ph": record.get("ph"),
            "temperature_k": record.get("temperature_k"),
            "temperature_c": record.get("temperature_c"),
            "temperature_display": record.get("temperature_display"),
        },
        "provenance": {
            "source_db": record.get("source_db"),
            "source_record_count": record.get("source_record_count"),
            "has_literature_id": record.get("has_literature_id"),
            "pmid_count": record.get("pmid_count"),
            "doi_count": record.get("doi_count"),
            "literature_id_count": record.get("literature_id_count"),
            "literature_linkage": record.get("literature_linkage"),
            "source_line_number": line_number,
        },
        "evidence": {
            "verification_status": record.get("verification_status"),
            "evidence_confidence_tier": record.get("evidence_confidence_tier"),
            "paper_grounding_status": record.get("paper_grounding_status"),
            "has_proof_excerpt": record.get("has_proof_excerpt"),
        },
        "demo_splits": {
            "random_seed_20260810": assign_split(record.get("record_key", "")),
            "sequence_exclusive_sha256": assign_split(sequence_id),
            "substrate_exclusive_sha256": assign_split(substrate_id),
            "pair_exclusive_sha256": assign_split(pair_id),
        },
    }


def iter_jsonl(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield line_number, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON on line %s: %s" % (line_number, exc)) from exc


def iter_eligible_records(
    path,
    require_smiles=True,
    limit=None,
    rejection_counts=None,
):
    yielded = 0
    for line_number, record in iter_jsonl(path):
        reason = eligibility_reason(record, require_smiles=require_smiles)
        if reason is not None:
            if rejection_counts is not None:
                rejection_counts[reason] += 1
            continue
        yield line_number, record
        yielded += 1
        if limit is not None and yielded >= limit:
            break


def build_schema(require_smiles=True):
    notes = [
        "Protein sequences are read from catlog-enriched.jsonl.gz.",
        "Substrate SMILES are read from catlog-enriched.jsonl.gz.",
        "PubChem CIDs, canonical SMILES, isomeric SMILES, InChIKey, IUPAC names, and molecular formulae are not joined.",
        "sequence_id is the predictor seqmap ID when available and otherwise sha256(sequence)[:12].",
        "substrate_id is smiles:sha256(smiles)[:16] when SMILES are present.",
        "Primary UniProt IDs are retained when present but are not required when an assayed sequence is available.",
        "Mutant datapoints use variant_sequence as the main sequence; mutant rows without variant_sequence are excluded.",
        "Sequences longer than 1024 residues are retained, but sequence artifact generation uses the first 512 and last 512 residues as model input.",
        "Truncated artifact inputs are marked in sequence.sequence_artifact_generation.",
        "Embeddings and pseq2sites scores are keyed by sequence_id, not embedded in this file.",
    ]
    if not require_smiles:
        notes.append("Rows without source SMILES use substrate_<hash> IDs generated from substrate names.")

    return {
        "required_per_datapoint": [
            "record_key",
            "measurement_key",
            "measurement_id",
            "review_key",
            "enzyme",
            "sequence",
            "substrate",
            "measurements",
            "assay_conditions",
            "provenance",
            "evidence",
            "demo_splits",
        ],
        "notes": notes,
    }


def empty_stats():
    return {
        "record_count": 0,
        "unique_sequences": set(),
        "unique_substrates": set(),
        "unique_ec_numbers": set(),
        "rows_with_kcat": 0,
        "rows_with_km": 0,
        "rows_with_both_kcat_and_km": 0,
        "rows_without_primary_uniprot_id": 0,
        "rows_marked_mutant": 0,
        "rows_with_variant_sequence": 0,
        "rows_with_wild_type_sequence": 0,
        "mutant_rows_using_variant_sequence": 0,
        "mutant_rows_without_variant_sequence": 0,
        "rows_with_truncated_artifact_input": 0,
        "sequences_with_truncated_artifact_input": set(),
        "source_db_counts": defaultdict(int),
        "verification_status_counts": defaultdict(int),
        "rejection_counts": Counter(),
    }


def update_stats(stats, datapoint):
    stats["record_count"] += 1
    stats["unique_sequences"].add(datapoint["sequence"]["sequence_id"])
    stats["unique_substrates"].add(datapoint["substrate"]["substrate_id"])
    ec_number = datapoint["enzyme"].get("ec_number")
    if ec_number:
        stats["unique_ec_numbers"].add(ec_number)
    if datapoint["measurements"]["kcat"]["available"]:
        stats["rows_with_kcat"] += 1
    if datapoint["measurements"]["km"]["available"]:
        stats["rows_with_km"] += 1
    if datapoint["measurements"]["kcat"]["available"] and datapoint["measurements"]["km"]["available"]:
        stats["rows_with_both_kcat_and_km"] += 1
    if not valid_accession(datapoint["enzyme"].get("primary_uniprot_id")):
        stats["rows_without_primary_uniprot_id"] += 1
    if datapoint["sequence"].get("is_mutant"):
        stats["rows_marked_mutant"] += 1
        if datapoint["sequence"].get("assayed_sequence_source") == "variant_sequence":
            stats["mutant_rows_using_variant_sequence"] += 1
        else:
            stats["mutant_rows_without_variant_sequence"] += 1
    if datapoint["sequence"].get("variant_sequence"):
        stats["rows_with_variant_sequence"] += 1
    if datapoint["sequence"].get("wild_type_sequence"):
        stats["rows_with_wild_type_sequence"] += 1
    artifact_generation = datapoint["sequence"].get("sequence_artifact_generation") or {}
    if artifact_generation.get("input_sequence_was_truncated"):
        stats["rows_with_truncated_artifact_input"] += 1
        stats["sequences_with_truncated_artifact_input"].add(datapoint["sequence"]["sequence_id"])
    source_db = datapoint["provenance"].get("source_db") or "unknown"
    status = datapoint["evidence"].get("verification_status") or "unknown"
    stats["source_db_counts"][source_db] += 1
    stats["verification_status_counts"][status] += 1


def scan_source(args):
    stats = empty_stats()
    resolver = SequenceIdResolver(args.seqmap_db)
    try:
        for line_number, record in iter_eligible_records(
            args.source,
            require_smiles=not args.include_missing_smiles,
            limit=args.limit,
            rejection_counts=stats["rejection_counts"],
        ):
            datapoint = build_datapoint(record, line_number, resolver)
            update_stats(stats, datapoint)
    finally:
        resolver.close()
    return stats


def serializable_stats(stats):
    return {
        "datapoints": stats["record_count"],
        "unique_sequences": len(stats["unique_sequences"]),
        "unique_substrates": len(stats["unique_substrates"]),
        "unique_ec_numbers": len(stats["unique_ec_numbers"]),
        "rows_with_kcat": stats["rows_with_kcat"],
        "rows_with_km": stats["rows_with_km"],
        "rows_with_both_kcat_and_km": stats["rows_with_both_kcat_and_km"],
        "rows_without_primary_uniprot_id": stats["rows_without_primary_uniprot_id"],
        "rows_marked_mutant": stats["rows_marked_mutant"],
        "rows_with_variant_sequence": stats["rows_with_variant_sequence"],
        "rows_with_wild_type_sequence": stats["rows_with_wild_type_sequence"],
        "mutant_rows_using_variant_sequence": stats["mutant_rows_using_variant_sequence"],
        "mutant_rows_without_variant_sequence": stats["mutant_rows_without_variant_sequence"],
        "rows_with_truncated_artifact_input": stats["rows_with_truncated_artifact_input"],
        "sequences_with_truncated_artifact_input": len(stats["sequences_with_truncated_artifact_input"]),
    }


def build_manifest(args, source_sha256, stats):
    source_limitations = [
        "Rows are included when they have a valid protein sequence string, substrate name, at least one positive kcat or km value, units for present kinetic values, and non-disputed status.",
        "A primary UniProt ID is not required when the enriched source provides an assayed sequence.",
        "Rows without source SMILES are excluded by default; pass --include-missing-smiles to retain them with substrate-name-derived IDs.",
        "PubChem CIDs, canonical/isomeric SMILES, InChIKey, IUPAC names, and molecular formulae are intentionally not joined.",
        "Substrate labels are normalized for whitespace but not rejected for old demo-only name heuristics when source SMILES are present.",
        "Mutant rows are included only when variant_sequence is present, because sequence-keyed artifacts must target the assayed mutant sequence.",
        "Sequences longer than 1024 residues are retained; sequence artifacts are generated from a first-512 plus last-512 truncation and saved under the original sequence_id.",
        "Raw source envelopes are not included in this artifact.",
    ]
    if args.limit is not None:
        source_limitations.append("This file was generated with --limit %s." % args.limit)

    return {
        "release_id": args.release_id,
        "title": "OpenKinetics Data full CatLog enriched export",
        "generated_at": utc_now_iso(),
        "record_count": stats["record_count"],
        "candidate_rows_passing_local_filters": stats["record_count"],
        "source": {
            "input_file": os.path.basename(args.source),
            "input_path": args.source,
            "input_sha256": source_sha256,
            "source_kind": "CatLog enriched JSONL export",
            "source_limitations": source_limitations,
        },
        "counts": serializable_stats(stats),
        "source_db_counts": dict(sorted(stats["source_db_counts"].items())),
        "verification_status_counts": dict(sorted(stats["verification_status_counts"].items())),
        "eligibility": {
            "require_source_smiles": not args.include_missing_smiles,
            "rejected_rows_by_reason": dict(sorted(stats["rejection_counts"].items())),
        },
        "api_lookups": {},
        "attribution": {
            "catlog": "Data curated by CatLog collaborators, served by OpenKinetics.",
            "temporary_citation": "Sajeevan et al., Robust Prediction of Enzyme Variant Kinetics with RealKcat, bioRxiv 2025, DOI 10.1101/2025.02.10.637555.",
            "redistribution_note": "Confirm final CatLog redistribution/license terms before public release.",
        },
    }


def json_text(value, compact=False):
    if compact:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, indent=2, sort_keys=True)


def indented_json_text(value, indent, compact=False):
    prefix = " " * indent
    text = json_text(value, compact=compact)
    return prefix + text.replace("\n", "\n" + prefix)


def write_artifact(args, manifest, schema):
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.name + ".tmp")

    resolver = SequenceIdResolver(args.seqmap_db)
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write("{\n")
            handle.write('  "manifest": ')
            handle.write(json_text(manifest, compact=args.compact).replace("\n", "\n  "))
            handle.write(",\n")
            handle.write('  "schema": ')
            handle.write(json_text(schema, compact=args.compact).replace("\n", "\n  "))
            handle.write(",\n")
            handle.write('  "datapoints": [\n')

            count = 0
            for line_number, record in iter_eligible_records(
                args.source,
                require_smiles=not args.include_missing_smiles,
                limit=args.limit,
            ):
                if count:
                    handle.write(",\n")
                datapoint = build_datapoint(record, line_number, resolver)
                handle.write(indented_json_text(datapoint, 4, compact=args.compact))
                count += 1
                if args.verbose and count % 10000 == 0:
                    print("Wrote %s datapoints" % count, file=sys.stderr)

            handle.write("\n  ]\n")
            handle.write("}\n")
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        resolver.close()

    os.replace(temp_path, output_path)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=default_source(), help="Path to catlog-enriched.jsonl.gz.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path for the generated OpenKinetics JSON.")
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument("--seqmap-db", default=DEFAULT_SEQMAP_DB)
    parser.add_argument("--limit", type=int, help="Write only the first N eligible records.")
    parser.add_argument(
        "--include-missing-smiles",
        action="store_true",
        help="Include otherwise eligible rows even when the source SMILES field is empty.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of the pretty-printed demo style.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")

    source_path = Path(args.source)
    if not source_path.exists():
        raise SystemExit("Source file not found: %s" % source_path)

    print("Scanning %s" % args.source, file=sys.stderr)
    source_sha = file_sha256(args.source)
    stats = scan_source(args)
    if stats["record_count"] == 0:
        raise SystemExit("No eligible records found in %s" % args.source)

    manifest = build_manifest(args, source_sha, stats)
    schema = build_schema(require_smiles=not args.include_missing_smiles)

    print("Writing %s datapoints to %s" % (stats["record_count"], args.output), file=sys.stderr)
    write_artifact(args, manifest, schema)
    print("Wrote %s" % args.output, file=sys.stderr)


if __name__ == "__main__":
    main()
