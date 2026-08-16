#!/usr/bin/env python3
"""Build a 100-record CatLog/OpenKinetics demo sample.

The source CatLog table is a flat JSONL export without protein sequences or
substrate structures. This script selects rows that can be resolved through
UniProt and PubChem, then writes a single self-describing demo JSON artifact.
"""

import argparse
import gzip
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone


DEFAULT_SOURCE = "/Users/mrsalwer/Downloads/catlog-table.jsonl.gz"
DEFAULT_OUTPUT = "data/sample/openkinetics_demo_100.json"
DEFAULT_CACHE = "/private/tmp/openkinetics_catlog_demo_cache"

UNIPROT_FASTA_URL = "https://rest.uniprot.org/uniprotkb/{accession}.fasta"
PUBCHEM_PROPS_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
    "{name}/property/CanonicalSMILES,IsomericSMILES,InChIKey,IUPACName,"
    "MolecularFormula/JSON"
)

ACCESSION_RE = re.compile(r"^[A-Z0-9]+(?:-\d+)?$")
AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYXBZUO]+$")

BAD_SUBSTRATE_WORDS = (
    "unknown",
    "not reported",
    "not specified",
    "various",
    "protein",
    "enzyme",
    "peptide",
    "polypeptide",
    "casein",
    "hemoglobin",
    "albumin",
    "histone",
    "dna",
    "rna",
    "cellulose",
    "starch",
    "xylan",
    "pectin",
    "glycogen",
    "chitin",
    "lipid",
    "acceptor",
    "donor",
)

STATUS_SCORE = {
    "corrected": 50,
    "verified": 45,
    "mathematically_inferred": 35,
    "manual_review_required": 25,
    "unverified": 10,
    "disputed": -20,
}

GROUNDING_SCORE = {
    "full_text_verified": 40,
    "review_excerpt_preserved": 25,
    "literature_id_present_unresolved": 15,
    "no_literature_id": -10,
}

EVIDENCE_SCORE = {
    "paper_grounded_high_confidence": 40,
    "paper_grounded": 30,
    "literature_linked": 18,
    "candidate_only": 5,
}


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dir(path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(prefix, *parts):
    payload = "\x1f".join("" if part is None else str(part) for part in parts)
    return "%s_%s" % (prefix, sha256_text(payload)[:16])


def predictor_cache_sequence_id(sequence):
    return sha256_text(sequence)[:12]


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_path(cache_dir, namespace, key, suffix):
    digest = sha256_text(key)
    directory = os.path.join(cache_dir, namespace)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "%s.%s" % (digest, suffix))


def http_get(url, timeout=30, retries=2, sleep_seconds=0.2):
    headers = {
        "User-Agent": "OpenKinetics demo data builder (contact: predictor.openkinetics.org)",
        "Accept": "*/*",
    }
    last_error = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 404):
                raise
            if attempt < retries:
                time.sleep(sleep_seconds * (attempt + 1))
    raise last_error


def parse_fasta(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(">"):
        raise ValueError("not a FASTA response")
    header = lines[0][1:]
    sequence = "".join(lines[1:]).replace(" ", "").upper()
    if not sequence or not AA_RE.match(sequence):
        raise ValueError("invalid amino-acid sequence")
    return header, sequence


def fetch_uniprot_sequence(accession, cache_dir):
    accession = accession.strip()
    path = cache_path(cache_dir, "uniprot_fasta", accession, "fasta")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    else:
        url = UNIPROT_FASTA_URL.format(accession=urllib.parse.quote(accession, safe=""))
        text = http_get(url)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        time.sleep(0.05)
    header, sequence = parse_fasta(text)
    return {
        "accession": accession,
        "sequence": sequence,
        "length": len(sequence),
        "fasta_header": header,
        "source": "UniProt REST API",
        "source_url": UNIPROT_FASTA_URL.format(accession=accession),
    }


def pubchem_query_variants(name):
    variants = []
    compact = " ".join(name.split()).strip()
    if compact:
        variants.append(compact)
    stripped_parenthetical = re.sub(r"\s*\([^)]{1,60}\)\s*", " ", compact).strip()
    stripped_parenthetical = " ".join(stripped_parenthetical.split())
    if stripped_parenthetical and stripped_parenthetical not in variants:
        variants.append(stripped_parenthetical)
    no_charge_suffix = re.sub(r"\s*\([+-]?\d*\)\s*$", "", compact).strip()
    if no_charge_suffix and no_charge_suffix not in variants:
        variants.append(no_charge_suffix)
    return variants


def fetch_pubchem_properties(name, cache_dir):
    errors = []
    for query in pubchem_query_variants(name):
        path = cache_path(cache_dir, "pubchem_name", query, "json")
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            else:
                url = PUBCHEM_PROPS_URL.format(name=urllib.parse.quote(query, safe=""))
                text = http_get(url)
                payload = json.loads(text)
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                time.sleep(0.15)
            properties = payload.get("PropertyTable", {}).get("Properties", [])
            if not properties:
                raise ValueError("PubChem response had no properties")
            first = properties[0]
            cid = first.get("CID")
            isomeric_smiles = first.get("SMILES") or first.get("IsomericSMILES")
            canonical_smiles = first.get("ConnectivitySMILES") or first.get("CanonicalSMILES")
            if not cid or not (isomeric_smiles or canonical_smiles):
                raise ValueError("PubChem response missing CID or SMILES")
            return {
                "query": query,
                "pubchem_cid": int(cid),
                "substrate_id": "pubchem:%s" % cid,
                "canonical_smiles": canonical_smiles,
                "isomeric_smiles": isomeric_smiles,
                "smiles": isomeric_smiles or canonical_smiles,
                "inchi_key": first.get("InChIKey"),
                "iupac_name": first.get("IUPACName"),
                "molecular_formula": first.get("MolecularFormula"),
                "source": "PubChem PUG REST name lookup",
                "source_url": "https://pubchem.ncbi.nlm.nih.gov/compound/%s" % cid,
            }
        except Exception as exc:
            errors.append("%s: %s" % (query, exc))
            continue
    raise ValueError("; ".join(errors))


def clean_substrate_name(name):
    if name is None:
        return None
    cleaned = " ".join(str(name).strip().split())
    if not cleaned:
        return None
    lower = cleaned.lower()
    if len(cleaned) > 90:
        return None
    if ";" in cleaned or "|" in cleaned:
        return None
    if " + " in cleaned or " plus " in lower or " and " in lower or " or " in lower:
        return None
    for word in BAD_SUBSTRATE_WORDS:
        if word in lower:
            return None
    return cleaned


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


def good_candidate(record):
    if not valid_accession(record.get("primary_uniprot_id")):
        return False
    if record.get("has_sequence") is not True:
        return False
    if record.get("sequence_resolved") is not True:
        return False
    if not has_value(record, "kcat") and not has_value(record, "km"):
        return False
    if not value_unit_ok(record, "kcat", "kcat_unit"):
        return False
    if not value_unit_ok(record, "km", "km_unit"):
        return False
    if not value_unit_ok(record, "ki", "ki_unit"):
        return False
    if not value_unit_ok(record, "kcat_over_km", "kcat_over_km_unit"):
        return False
    if clean_substrate_name(record.get("substrate_name")) is None:
        return False
    if record.get("verification_status") == "disputed":
        return False
    return True


def candidate_score(record):
    score = 0
    if has_value(record, "kcat") and has_value(record, "km"):
        score += 100
    elif has_value(record, "kcat") or has_value(record, "km"):
        score += 30
    score += STATUS_SCORE.get(record.get("verification_status"), 0)
    score += GROUNDING_SCORE.get(record.get("paper_grounding_status"), 0)
    score += EVIDENCE_SCORE.get(record.get("evidence_confidence_tier"), 0)
    score += min(int(record.get("pmid_count") or 0), 5) * 3
    score += min(int(record.get("doi_count") or 0), 3) * 3
    if record.get("source_db") in ("oed", "brenda", "sabio_rk", "skid", "uniprot"):
        score += 5
    if record.get("wild_type") is True:
        score += 3
    if record.get("sequence_variant_status") in (
        "canonical_wild_type_sequence",
        "reconstructed_variant_sequence",
        "source_provided_variant_sequence",
    ):
        score += 6
    return score


def ec_class(record):
    ec_number = record.get("ec_number") or ""
    return ec_number.split(".", 1)[0] if "." in ec_number else ec_number or "unknown"


def load_candidates(source_path):
    candidates = []
    with gzip.open(source_path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if good_candidate(record):
                record["_source_line_number"] = line_number
                record["_candidate_score"] = candidate_score(record)
                record["_clean_substrate_name"] = clean_substrate_name(record.get("substrate_name"))
                candidates.append(record)
    candidates.sort(key=lambda r: (-r["_candidate_score"], ec_class(r), r.get("record_key", "")))
    return candidates


def round_robin_by_ec_class(candidates):
    grouped = defaultdict(list)
    for record in candidates:
        grouped[ec_class(record)].append(record)
    classes = sorted(grouped.keys())
    index = 0
    while classes:
        key = classes[index % len(classes)]
        bucket = grouped[key]
        if bucket:
            yield bucket.pop(0)
        if not bucket:
            classes.remove(key)
            if not classes:
                break
            index = index % len(classes)
        else:
            index += 1


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


def build_datapoint(record, sequence_info, compound_info):
    sequence = sequence_info["sequence"]
    sequence_id = stable_id("seq", sequence)
    cache_sequence_id = predictor_cache_sequence_id(sequence)
    substrate_id = compound_info["substrate_id"]
    enzyme_substrate_id = stable_id(
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
            "cache_sequence_id": cache_sequence_id,
            "sequence": sequence,
            "length": sequence_info["length"],
            "source": sequence_info["source"],
            "source_url": sequence_info["source_url"],
            "fasta_header": sequence_info["fasta_header"],
            "has_sequence": record.get("has_sequence"),
            "sequence_resolved": record.get("sequence_resolved"),
            "sequence_source_confidence": record.get("sequence_source_confidence"),
            "sequence_variant_status": record.get("sequence_variant_status"),
            "mutation_signature": record.get("mutation_signature"),
            "wild_type": record.get("wild_type"),
        },
        "substrate": {
            "substrate_id": substrate_id,
            "name": record.get("substrate_name"),
            "pubchem_query": compound_info["query"],
            "pubchem_cid": compound_info["pubchem_cid"],
            "canonical_smiles": compound_info["canonical_smiles"],
            "isomeric_smiles": compound_info["isomeric_smiles"],
            "smiles": compound_info["smiles"],
            "inchi_key": compound_info["inchi_key"],
            "iupac_name": compound_info["iupac_name"],
            "molecular_formula": compound_info["molecular_formula"],
            "source": compound_info["source"],
            "source_url": compound_info["source_url"],
        },
        "enzyme_substrate_pair": {
            "pair_id": enzyme_substrate_id,
            "sequence_id": sequence_id,
            "cache_sequence_id": cache_sequence_id,
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
            "source_line_number": record.get("_source_line_number"),
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
            "pair_exclusive_sha256": assign_split(enzyme_substrate_id),
        },
        "demo_artifact_keys": {
            "embedding_key": cache_sequence_id,
            "binding_site_prediction_key": cache_sequence_id,
            "note": "Keys use the predictor seqmap-compatible cache ID: sha256(sequence)[:12].",
        },
    }


def build_schema():
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
            "demo_artifact_keys",
        ],
        "notes": [
            "Protein sequences are fetched from UniProt by primary_uniprot_id.",
            "Substrate structures are fetched from PubChem by substrate_name.",
            "PMID/DOI lists are not present in catlog-table.jsonl.gz; only counts are included.",
            "Verification notes and raw source envelopes are not present in catlog-table.jsonl.gz.",
            "Embeddings and pseq2sites scores are represented by join keys, not computed vectors/scores.",
        ],
    }


def build_manifest(args, source_sha256, candidates_count, datapoints):
    unique_sequences = sorted({row["sequence"]["sequence_id"] for row in datapoints})
    unique_substrates = sorted({row["substrate"]["substrate_id"] for row in datapoints})
    unique_ecs = sorted({row["enzyme"]["ec_number"] for row in datapoints if row["enzyme"].get("ec_number")})
    source_dbs = defaultdict(int)
    statuses = defaultdict(int)
    for row in datapoints:
        source_dbs[row["provenance"].get("source_db") or "unknown"] += 1
        statuses[row["evidence"].get("verification_status") or "unknown"] += 1
    return {
        "release_id": "openkinetics-catlog-demo-2026-08",
        "title": "OpenKinetics Data demo sample from CatLog table export",
        "generated_at": utc_now_iso(),
        "record_count": len(datapoints),
        "candidate_rows_passing_local_filters": candidates_count,
        "source": {
            "input_file": os.path.basename(args.source),
            "input_path": args.source,
            "input_sha256": source_sha256,
            "source_kind": "CatLog flat table export",
            "source_limitations": [
                "The table export does not include raw source envelopes.",
                "The table export does not include full PMID/DOI lists.",
                "The table export does not include verification notes.",
                "Protein sequences and substrate structures were joined from public APIs.",
            ],
        },
        "counts": {
            "datapoints": len(datapoints),
            "unique_sequences": len(unique_sequences),
            "unique_substrates": len(unique_substrates),
            "unique_ec_numbers": len(unique_ecs),
            "rows_with_kcat": sum(1 for row in datapoints if row["measurements"]["kcat"]["available"]),
            "rows_with_km": sum(1 for row in datapoints if row["measurements"]["km"]["available"]),
            "rows_with_both_kcat_and_km": sum(
                1
                for row in datapoints
                if row["measurements"]["kcat"]["available"] and row["measurements"]["km"]["available"]
            ),
        },
        "source_db_counts": dict(sorted(source_dbs.items())),
        "verification_status_counts": dict(sorted(statuses.items())),
        "api_lookups": {
            "uniprot": {
                "purpose": "protein sequences",
                "endpoint_template": UNIPROT_FASTA_URL,
            },
            "pubchem": {
                "purpose": "substrate SMILES, InChIKey, CID, formula",
                "endpoint_template": PUBCHEM_PROPS_URL,
            },
        },
        "attribution": {
            "catlog": "Data curated by CatLog collaborators, served by OpenKinetics.",
            "temporary_citation": "Sajeevan et al., Robust Prediction of Enzyme Variant Kinetics with RealKcat, bioRxiv 2025, DOI 10.1101/2025.02.10.637555.",
            "redistribution_note": "Demo sample for data.openkinetics.org planning; confirm final CatLog redistribution/license terms before public release.",
        },
    }


def should_accept(datapoint, counts, constraints):
    accession = datapoint["enzyme"]["primary_uniprot_id"]
    substrate = datapoint["substrate"]["substrate_id"]
    organism = datapoint["enzyme"]["organism"] or "unknown"
    klass = (datapoint["enzyme"]["ec_number"] or "unknown").split(".", 1)[0]
    if counts["accession"][accession] >= constraints["max_per_accession"]:
        return False
    if counts["substrate"][substrate] >= constraints["max_per_substrate"]:
        return False
    if counts["organism"][organism] >= constraints["max_per_organism"]:
        return False
    if counts["ec_class"][klass] >= constraints["max_per_ec_class"]:
        return False
    return True


def update_counts(datapoint, counts):
    accession = datapoint["enzyme"]["primary_uniprot_id"]
    substrate = datapoint["substrate"]["substrate_id"]
    organism = datapoint["enzyme"]["organism"] or "unknown"
    klass = (datapoint["enzyme"]["ec_number"] or "unknown").split(".", 1)[0]
    counts["accession"][accession] += 1
    counts["substrate"][substrate] += 1
    counts["organism"][organism] += 1
    counts["ec_class"][klass] += 1


def build_sample(args):
    source_sha = file_sha256(args.source)
    candidates = load_candidates(args.source)
    if args.verbose:
        print("Loaded %s locally eligible candidates" % len(candidates), file=sys.stderr)

    constraints_phases = [
        {"max_per_accession": 2, "max_per_substrate": 4, "max_per_organism": 12, "max_per_ec_class": 20},
        {"max_per_accession": 4, "max_per_substrate": 8, "max_per_organism": 20, "max_per_ec_class": 30},
        {"max_per_accession": 8, "max_per_substrate": 12, "max_per_organism": 35, "max_per_ec_class": 50},
        {"max_per_accession": 999, "max_per_substrate": 999, "max_per_organism": 999, "max_per_ec_class": 999},
    ]

    built_by_record_key = {}
    failed_uniprot = {}
    failed_pubchem = {}
    api_attempts = 0
    counts = {
        "accession": defaultdict(int),
        "substrate": defaultdict(int),
        "organism": defaultdict(int),
        "ec_class": defaultdict(int),
    }

    for phase_index, constraints in enumerate(constraints_phases, 1):
        if len(built_by_record_key) >= args.count:
            break
        if args.verbose:
            print("Selection phase %s with constraints %s" % (phase_index, constraints), file=sys.stderr)
        for record in round_robin_by_ec_class(list(candidates)):
            if len(built_by_record_key) >= args.count:
                break
            record_key = record.get("record_key")
            if record_key in built_by_record_key:
                continue
            accession = record.get("primary_uniprot_id")
            substrate_name = record.get("_clean_substrate_name")
            if accession in failed_uniprot or substrate_name in failed_pubchem:
                continue
            try:
                sequence_info = fetch_uniprot_sequence(accession, args.cache_dir)
            except Exception as exc:
                failed_uniprot[accession] = str(exc)
                continue
            try:
                compound_info = fetch_pubchem_properties(substrate_name, args.cache_dir)
            except Exception as exc:
                failed_pubchem[substrate_name] = str(exc)
                continue
            api_attempts += 1
            datapoint = build_datapoint(record, sequence_info, compound_info)
            if not should_accept(datapoint, counts, constraints):
                continue
            built_by_record_key[record_key] = datapoint
            update_counts(datapoint, counts)
            if args.verbose and len(built_by_record_key) % 10 == 0:
                print("Accepted %s datapoints" % len(built_by_record_key), file=sys.stderr)

    datapoints = list(built_by_record_key.values())
    datapoints.sort(key=lambda row: row["record_key"])
    if len(datapoints) < args.count:
        raise RuntimeError(
            "Only built %s datapoints; need %s. Failed UniProt=%s, PubChem=%s, API attempts=%s"
            % (len(datapoints), args.count, len(failed_uniprot), len(failed_pubchem), api_attempts)
        )

    artifact = {
        "manifest": build_manifest(args, source_sha, len(candidates), datapoints),
        "schema": build_schema(),
        "datapoints": datapoints,
    }
    ensure_dir(args.output)
    temp_path = args.output + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, args.output)
    return artifact


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    artifact = build_sample(args)
    manifest = artifact["manifest"]
    print("Wrote %s" % args.output)
    print("Records: %s" % manifest["record_count"])
    print("Unique sequences: %s" % manifest["counts"]["unique_sequences"])
    print("Unique substrates: %s" % manifest["counts"]["unique_substrates"])
    print("Rows with both kcat and Km: %s" % manifest["counts"]["rows_with_both_kcat_and_km"])


if __name__ == "__main__":
    main()
