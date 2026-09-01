#!/usr/bin/env python3
"""Build release zip bundles from mounted predictor sequence artifact caches."""

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from data_api.npy_utils import NpyReadError, read_npy_flat_numbers, read_npy_metadata  # noqa: E402


DEFAULT_RELEASES_DIR = os.environ.get("OPENKINETICS_RELEASES_ROOT", "releases")
DEFAULT_SEQUENCE_INFO_ROOT = os.environ.get("OPENKINETICS_SEQUENCE_INFO_ROOT", "/sequence_info")
SEQUENCE_METADATA_PATH = "metadata/sequences.jsonl"
ARTIFACT_METADATA_PATH = "metadata/artifacts.jsonl"

ARTIFACT_SPECS = {
    "esm2": {
        "source_root": os.environ.get("OPENKINETICS_ESM2_RESIDUE_ROOT", "esm2_layer_33/residue_vecs"),
        "bundle": "downloads/openkinetics-demo-esm2-residue-vecs.zip",
        "bundle_prefix": "embeddings/esm2/residue_vecs",
        "array_kind": "embedding",
        "records_path": "embeddings/esm2/index.jsonl.gz",
    },
    "esmc": {
        "source_root": os.environ.get("OPENKINETICS_ESMC_RESIDUE_ROOT", "esmc_layer_32/residue_vecs"),
        "bundle": "downloads/openkinetics-demo-esmc-residue-vecs.zip",
        "bundle_prefix": "embeddings/esmc/residue_vecs",
        "array_kind": "embedding",
        "records_path": "embeddings/esmc/index.jsonl.gz",
    },
    "prot_t5": {
        "source_root": os.environ.get(
            "OPENKINETICS_PROT_T5_RESIDUE_ROOT",
            "prot_t5_last/residue_vecs",
        ),
        "bundle": "downloads/openkinetics-demo-prot-t5-residue-vecs.zip",
        "bundle_prefix": "embeddings/prot_t5/residue_vecs",
        "array_kind": "embedding",
        "records_path": "embeddings/prot_t5/index.jsonl.gz",
    },
    "pseq2sites": {
        "source_root": os.environ.get("OPENKINETICS_PSEQ2SITES_ROOT", "pseq2sites_scores"),
        "bundle": "downloads/openkinetics-demo-pseq2sites-scores.zip",
        "bundle_prefix": "pseq2sites/scores",
        "array_kind": "scores",
        "records_path": "pseq2sites/scores.jsonl.gz",
    },
}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_sequences(release_dir):
    path = release_dir / "sequences.jsonl.gz"
    sequences = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            sequences.append(row)
    return sequences


def ensure_parent(path):
    path.parent.mkdir(parents=True, exist_ok=True)


def remove_stale(path):
    if path.exists():
        path.unlink()


def write_json(path, payload):
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def jsonl_text(rows):
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def gzip_text(text):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(text.encode("utf-8"))
    return buffer.getvalue()


def public_sequence_fields(row):
    return {
        "sequence_id": row["sequence_id"],
        "sequence": row["sequence"],
        "length": row.get("length"),
        "primary_uniprot_id": row.get("primary_uniprot_id"),
        "fasta_header": row.get("fasta_header"),
        "source_url": row.get("source_url"),
        "sequence_variant_status": row.get("sequence_variant_status"),
        "mutation_signature": row.get("mutation_signature"),
        "wild_type": row.get("wild_type"),
    }


def public_record(record):
    return {
        key: value
        for key, value in record.items()
        if key not in ("source_path",)
    }


def sequence_artifact_record(row, source_path, archive_path, available):
    record = {
        **public_sequence_fields(row),
        "artifact_available": available,
        "artifact_path": archive_path if available else "",
        "array_shape": None,
        "array_dtype": "",
        "size_bytes": None,
        "sha256": "",
    }
    if not available:
        return record
    try:
        metadata = read_npy_metadata(source_path)
        record["array_shape"] = metadata["shape"]
        record["array_dtype"] = metadata["dtype"]
    except (OSError, NpyReadError) as exc:
        record["array_metadata_error"] = str(exc)
    record["size_bytes"] = source_path.stat().st_size
    record["sha256"] = sha256_file(source_path)
    return record


def score_rows(found):
    rows = []
    errors = []
    for item in found:
        source_path = Path(item["source_path"])
        try:
            scores = read_npy_flat_numbers(source_path, max_items=max(item.get("length") or 0, 10000))
        except (OSError, NpyReadError) as exc:
            errors.append({"sequence_id": item["sequence_id"], "error": str(exc)})
            continue
        finite_scores = [score for score in scores if score is not None]
        summary = {
            "min": min(finite_scores) if finite_scores else None,
            "max": max(finite_scores) if finite_scores else None,
            "mean": sum(finite_scores) / len(finite_scores) if finite_scores else None,
        }
        rows.append(
            {
                "sequence_id": item["sequence_id"],
                "sequence": item["sequence"],
                "scores": scores,
                "score_count": len(scores),
                "aligned_to_sequence": len(scores) == len(item["sequence"]),
                "summary": summary,
            }
        )
    return rows, errors


def build_model_bundle(release_dir, sequence_info_root, model_key, spec, sequences):
    source_root = (sequence_info_root / spec["source_root"]).resolve()
    bundle_path = release_dir / spec["bundle"]
    found = []
    missing = []
    sequence_records = []
    for row in sequences:
        sequence_id = row["sequence_id"]
        source_path = source_root / ("%s.npy" % sequence_id)
        archive_path = "%s/%s.npy" % (spec["bundle_prefix"], sequence_id)
        available = source_path.exists() and source_path.is_file()
        artifact_record = sequence_artifact_record(row, source_path, archive_path, available)
        sequence_records.append(artifact_record)
        item = {
            **artifact_record,
            "source_path": str(source_path),
        }
        if available:
            found.append(item)
        else:
            missing.append(item)

    readable_score_rows = []
    score_parse_errors = []
    if spec["array_kind"] == "scores":
        readable_score_rows, score_parse_errors = score_rows(found)

    report = {
        "model_key": model_key,
        "source_root": str(source_root),
        "total_sequences": len(sequences),
        "found": len(found),
        "missing": len(missing),
        "missing_sequences": [public_record(row) for row in missing],
        "join_key": "sequence_id",
        "file_format": "ZIP with JSONL metadata and NumPy .npy arrays",
        "array_kind": spec["array_kind"],
        "sequence_metadata_path": SEQUENCE_METADATA_PATH,
        "artifact_metadata_path": ARTIFACT_METADATA_PATH,
        "records_path": spec["records_path"],
        "array_file_pattern": "%s/{sequence_id}.npy" % spec["bundle_prefix"],
        "score_rows": len(readable_score_rows),
        "score_parse_errors": score_parse_errors,
    }
    write_json(release_dir / "artifact_reports" / ("%s.json" % model_key), report)

    if not found:
        remove_stale(bundle_path)
        return report

    ensure_parent(bundle_path)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.txt", bundle_readme(model_key, spec, report))
        bundle.writestr("manifest.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
        bundle.writestr(SEQUENCE_METADATA_PATH, jsonl_text([public_record(row) for row in sequence_records]))
        bundle.writestr(ARTIFACT_METADATA_PATH, jsonl_text([public_record(row) for row in found]))
        if spec["array_kind"] == "scores" and readable_score_rows:
            bundle.writestr(spec["records_path"], gzip_text(jsonl_text(readable_score_rows)))
        elif spec["array_kind"] == "embedding":
            bundle.writestr(spec["records_path"], gzip_text(jsonl_text([public_record(row) for row in found])))
        for item in found:
            source_path = Path(item["source_path"])
            bundle.write(source_path, arcname=item["artifact_path"])
    return report


def bundle_readme(model_key, spec, report):
    return (
        "OpenKinetics Data sequence artifact bundle\n"
        "model_key: %s\n"
        "join_key: sequence_id\n"
        "source_root: %s\n"
        "found: %s\n"
        "missing: %s\n"
        "format: ZIP with JSONL metadata and NumPy .npy arrays\n"
        "sequence_metadata: %s\n"
        "artifact_metadata: %s\n"
        "records: %s\n"
        "array_file_pattern: %s/{sequence_id}.npy\n"
    ) % (
        model_key,
        spec["source_root"],
        report["found"],
        report["missing"],
        SEQUENCE_METADATA_PATH,
        ARTIFACT_METADATA_PATH,
        spec["records_path"],
        spec["bundle_prefix"],
    )


def build_parent_bundle(release_dir, bundle_name, child_paths):
    bundle_path = release_dir / bundle_name
    existing = [release_dir / path for path in child_paths if (release_dir / path).exists()]
    if not existing:
        remove_stale(bundle_path)
        return
    ensure_parent(bundle_path)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in existing:
            bundle.write(path, arcname=str(path.relative_to(release_dir)))


def write_checksums(release_dir):
    checksum_path = release_dir / "checksums.sha256"
    rows = []
    for path in sorted(release_dir.rglob("*")):
        if path.is_file() and path != checksum_path:
            rows.append("%s  %s" % (sha256_file(path), path.relative_to(release_dir)))
    checksum_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", default="openkinetics-catlog-demo-2026-08")
    parser.add_argument("--releases-dir", default=DEFAULT_RELEASES_DIR)
    parser.add_argument("--sequence-info-root", default=DEFAULT_SEQUENCE_INFO_ROOT)
    args = parser.parse_args()

    releases_dir = Path(args.releases_dir)
    release_dir = releases_dir / args.release_id
    sequence_info_root = Path(args.sequence_info_root)
    sequences = load_sequences(release_dir)

    reports = {}
    for model_key, spec in ARTIFACT_SPECS.items():
        reports[model_key] = build_model_bundle(
            release_dir,
            sequence_info_root,
            model_key,
            spec,
            sequences,
        )

    build_parent_bundle(
        release_dir,
        "downloads/openkinetics-demo-embeddings.zip",
        [
            ARTIFACT_SPECS["esm2"]["bundle"],
            ARTIFACT_SPECS["esmc"]["bundle"],
            ARTIFACT_SPECS["prot_t5"]["bundle"],
        ],
    )
    build_parent_bundle(
        release_dir,
        "downloads/openkinetics-demo-pseq2sites.zip",
        [ARTIFACT_SPECS["pseq2sites"]["bundle"]],
    )
    build_parent_bundle(
        release_dir,
        "downloads/openkinetics-demo-complete.zip",
        [
            "downloads/openkinetics-demo-measurements.zip",
            "downloads/openkinetics-demo-ml-ready.zip",
            "downloads/openkinetics-demo-embeddings.zip",
            "downloads/openkinetics-demo-pseq2sites.zip",
        ],
    )
    write_json(release_dir / "artifact_reports" / "summary.json", reports)
    write_checksums(release_dir)

    print("Built mounted sequence artifact bundles in %s" % release_dir)
    for model_key, report in reports.items():
        print("%s: found %s / %s" % (model_key, report["found"], report["total_sequences"]))


if __name__ == "__main__":
    main()
