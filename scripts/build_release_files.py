#!/usr/bin/env python3
"""Build server-side release files and zip bundles from the demo sample."""

import argparse
import csv
import gzip
import hashlib
import json
import os
import zipfile
from pathlib import Path


DEFAULT_SAMPLE = "data/sample/openkinetics_demo_100.json"
DEFAULT_RELEASES_DIR = os.environ.get("OPENKINETICS_RELEASES_ROOT", "releases")


def ensure_dir(path):
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path, payload):
    ensure_dir(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl_gz(path, rows):
    ensure_dir(path)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def write_csv_gz(path, rows, fieldnames):
    ensure_dir(path)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def write_csv(path, rows, fieldnames):
    ensure_dir(path)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metric(datapoint, key, attr):
    return datapoint.get("measurements", {}).get(key, {}).get(attr)


def flat_measurement(datapoint):
    enzyme = datapoint["enzyme"]
    substrate = datapoint["substrate"]
    sequence = datapoint["sequence"]
    assay = datapoint["assay_conditions"]
    evidence = datapoint["evidence"]
    provenance = datapoint["provenance"]
    pair = datapoint["enzyme_substrate_pair"]
    return {
        "record_key": datapoint["record_key"],
        "measurement_key": datapoint.get("measurement_key"),
        "measurement_id": datapoint.get("measurement_id"),
        "review_key": datapoint.get("review_key"),
        "enzyme_name": enzyme.get("name"),
        "ec_number": enzyme.get("ec_number"),
        "organism": enzyme.get("organism"),
        "primary_uniprot_id": enzyme.get("primary_uniprot_id"),
        "sequence_id": sequence.get("sequence_id"),
        "sequence_length": sequence.get("length"),
        "sequence_variant_status": sequence.get("sequence_variant_status"),
        "mutation_signature": sequence.get("mutation_signature"),
        "wild_type": sequence.get("wild_type"),
        "substrate_id": substrate.get("substrate_id"),
        "substrate_name": substrate.get("name"),
        "pubchem_cid": substrate.get("pubchem_cid"),
        "smiles": substrate.get("smiles"),
        "inchi_key": substrate.get("inchi_key"),
        "pair_id": pair.get("pair_id"),
        "kcat": metric(datapoint, "kcat", "value"),
        "kcat_unit": metric(datapoint, "kcat", "unit"),
        "km": metric(datapoint, "km", "value"),
        "km_unit": metric(datapoint, "km", "unit"),
        "ki": metric(datapoint, "ki", "value"),
        "ki_unit": metric(datapoint, "ki", "unit"),
        "kcat_over_km": metric(datapoint, "kcat_over_km", "value"),
        "kcat_over_km_unit": metric(datapoint, "kcat_over_km", "unit"),
        "ph": assay.get("ph"),
        "temperature_c": assay.get("temperature_c"),
        "source_db": provenance.get("source_db"),
        "source_record_count": provenance.get("source_record_count"),
        "pmid_count": provenance.get("pmid_count"),
        "doi_count": provenance.get("doi_count"),
        "verification_status": evidence.get("verification_status"),
        "evidence_confidence_tier": evidence.get("evidence_confidence_tier"),
        "paper_grounding_status": evidence.get("paper_grounding_status"),
        "has_proof_excerpt": evidence.get("has_proof_excerpt"),
    }


def sequence_rows(datapoints):
    seen = {}
    for row in datapoints:
        sequence = row["sequence"]
        enzyme = row["enzyme"]
        seen[sequence["sequence_id"]] = {
            "sequence_id": sequence["sequence_id"],
            "primary_uniprot_id": enzyme.get("primary_uniprot_id"),
            "length": sequence.get("length"),
            "sequence": sequence.get("sequence"),
            "fasta_header": sequence.get("fasta_header"),
            "source_url": sequence.get("source_url"),
            "sequence_variant_status": sequence.get("sequence_variant_status"),
            "mutation_signature": sequence.get("mutation_signature"),
            "wild_type": sequence.get("wild_type"),
        }
    return [seen[key] for key in sorted(seen)]


def substrate_rows(datapoints):
    seen = {}
    for row in datapoints:
        substrate = row["substrate"]
        seen[substrate["substrate_id"]] = substrate
    return [seen[key] for key in sorted(seen)]


def fasta_text(rows):
    parts = []
    for row in rows:
        header = "%s|%s|len=%s" % (
            row["sequence_id"],
            row.get("primary_uniprot_id") or "uniprot_unknown",
            row.get("length") or "",
        )
        parts.append(">%s\n" % header)
        sequence = row["sequence"]
        for index in range(0, len(sequence), 80):
            parts.append(sequence[index : index + 80])
            parts.append("\n")
    return "".join(parts)


def split_rows(datapoints, family, source_key):
    rows = []
    for row in datapoints:
        rows.append(
            {
                "record_key": row["record_key"],
                "measurement_key": row.get("measurement_key"),
                "measurement_id": row.get("measurement_id"),
                "sequence_id": row["sequence"]["sequence_id"],
                "substrate_id": row["substrate"]["substrate_id"],
                "pair_id": row["enzyme_substrate_pair"]["pair_id"],
                "split_family": family,
                "split": row.get("demo_splits", {}).get(source_key),
            }
        )
    return rows


def zip_available(zip_path, release_dir, relative_paths):
    existing_paths = []
    for rel_path in relative_paths:
        path = release_dir / rel_path
        if path.exists() and path.is_file():
            existing_paths.append(rel_path)
    if not existing_paths:
        if zip_path.exists():
            zip_path.unlink()
        return
    ensure_dir(zip_path)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for rel_path in existing_paths:
            bundle.write(release_dir / rel_path, arcname=rel_path)


def write_checksums(release_dir):
    checksum_path = release_dir / "checksums.sha256"
    rows = []
    for path in sorted(release_dir.rglob("*")):
        if not path.is_file() or path == checksum_path:
            continue
        rows.append("%s  %s" % (sha256_file(path), path.relative_to(release_dir)))
    checksum_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default=DEFAULT_SAMPLE)
    parser.add_argument("--releases-dir", default=DEFAULT_RELEASES_DIR)
    args = parser.parse_args()

    root = Path.cwd()
    sample_path = root / args.sample
    with open(sample_path, "r", encoding="utf-8") as handle:
        sample = json.load(handle)

    manifest = sample["manifest"]
    release_id = manifest["release_id"]
    release_dir = root / args.releases_dir / release_id
    release_dir.mkdir(parents=True, exist_ok=True)

    datapoints = sample["datapoints"]
    measurements = [flat_measurement(row) for row in datapoints]
    sequences = sequence_rows(datapoints)
    substrates = substrate_rows(datapoints)

    enriched_manifest = dict(manifest)
    enriched_manifest["schema"] = sample.get("schema", {})
    enriched_manifest["download_note"] = (
        "Large embeddings and Pseq2Sites artifacts are distributed as ZIP packages containing "
        "sequence metadata plus predictor arrays keyed by sequence_id."
    )
    write_json(release_dir / "manifest.json", enriched_manifest)

    write_jsonl_gz(release_dir / "measurements.jsonl.gz", measurements)
    write_csv_gz(release_dir / "measurements.csv.gz", measurements, list(measurements[0].keys()))
    write_jsonl_gz(release_dir / "record_details.jsonl.gz", datapoints)
    write_jsonl_gz(release_dir / "sequences.jsonl.gz", sequences)
    ensure_dir(release_dir / "sequences.fasta")
    (release_dir / "sequences.fasta").write_text(fasta_text(sequences), encoding="utf-8")
    write_jsonl_gz(release_dir / "substrates.jsonl.gz", substrates)

    split_specs = {
        "random": "random_seed_20260810",
        "sequence_exclusive": "sequence_exclusive_sha256",
        "substrate_exclusive": "substrate_exclusive_sha256",
        "pair_exclusive": "pair_exclusive_sha256",
    }
    split_fieldnames = [
        "record_key",
        "measurement_key",
        "measurement_id",
        "sequence_id",
        "substrate_id",
        "pair_id",
        "split_family",
        "split",
    ]
    for family, source_key in split_specs.items():
        write_csv(
            release_dir / "splits" / ("%s.csv" % family),
            split_rows(datapoints, family, source_key),
            split_fieldnames,
        )

    expected = {
        "mounted_sequence_info_root": os.environ.get(
            "OPENKINETICS_SEQUENCE_INFO_ROOT",
            "/sequence_info",
        ),
        "embeddings": {
            "esm2": os.environ.get("OPENKINETICS_ESM2_RESIDUE_ROOT", "esm2_layer_33/residue_vecs"),
            "esmc": os.environ.get("OPENKINETICS_ESMC_RESIDUE_ROOT", "esmc_layer_32/residue_vecs"),
            "prot_t5": os.environ.get(
                "OPENKINETICS_PROT_T5_RESIDUE_ROOT",
                "prot_t5_last/residue_vecs",
            ),
        },
        "pseq2sites": os.environ.get("OPENKINETICS_PSEQ2SITES_ROOT", "pseq2sites_scores"),
        "join_key": "sequence_id",
        "filename_pattern": "{sequence_id}.npy",
        "bundle_metadata": {
            "sequence_metadata": "metadata/sequences.jsonl",
            "artifact_metadata": "metadata/artifacts.jsonl",
            "pseq2sites_scores": "pseq2sites/scores.jsonl.gz",
            "embedding_index_pattern": "embeddings/{model_key}/index.jsonl.gz",
        },
    }
    write_json(release_dir / "expected_generated_artifacts.json", expected)

    for stale_name in [
        "openkinetics-demo-esm2-residue-vecs.zip",
        "openkinetics-demo-esmc-residue-vecs.zip",
        "openkinetics-demo-prot-t5-residue-vecs.zip",
        "openkinetics-demo-pseq2sites-scores.zip",
        "openkinetics-demo-embeddings.zip",
        "openkinetics-demo-pseq2sites.zip",
    ]:
        stale_path = release_dir / "downloads" / stale_name
        if stale_path.exists():
            stale_path.unlink()

    zip_available(
        release_dir / "downloads/openkinetics-demo-measurements.zip",
        release_dir,
        ["manifest.json", "measurements.jsonl.gz", "measurements.csv.gz", "checksums.sha256"],
    )
    zip_available(
        release_dir / "downloads/openkinetics-demo-ml-ready.zip",
        release_dir,
        [
            "manifest.json",
            "measurements.jsonl.gz",
            "sequences.fasta",
            "sequences.jsonl.gz",
            "substrates.jsonl.gz",
            "splits/random.csv",
            "splits/sequence_exclusive.csv",
            "splits/substrate_exclusive.csv",
            "splits/pair_exclusive.csv",
        ],
    )
    complete_paths = [
        str(path.relative_to(release_dir))
        for path in release_dir.rglob("*")
        if path.is_file() and "downloads/" not in str(path.relative_to(release_dir))
    ]
    zip_available(release_dir / "downloads/openkinetics-demo-complete.zip", release_dir, complete_paths)
    write_checksums(release_dir)

    print("Built release files in %s" % release_dir)


if __name__ == "__main__":
    main()
