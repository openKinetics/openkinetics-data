#!/usr/bin/env python3
"""Build release zip bundles from mounted predictor sequence artifact caches."""

import argparse
import gzip
import hashlib
import json
import os
import zipfile
from pathlib import Path


DEFAULT_RELEASES_DIR = os.environ.get("OPENKINETICS_RELEASES_ROOT", "releases")
DEFAULT_SEQUENCE_INFO_ROOT = os.environ.get("OPENKINETICS_SEQUENCE_INFO_ROOT", "/sequence_info")

ARTIFACT_SPECS = {
    "esm2": {
        "source_root": os.environ.get("OPENKINETICS_ESM2_RESIDUE_ROOT", "esm2_layer_26/residue_vecs"),
        "bundle": "downloads/openkinetics-demo-esm2-residue-vecs.zip",
        "bundle_prefix": "embeddings/esm2/residue_vecs",
    },
    "esmc": {
        "source_root": os.environ.get("OPENKINETICS_ESMC_RESIDUE_ROOT", "esmc_layer_32/residue_vecs"),
        "bundle": "downloads/openkinetics-demo-esmc-residue-vecs.zip",
        "bundle_prefix": "embeddings/esmc/residue_vecs",
    },
    "prot_t5": {
        "source_root": os.environ.get(
            "OPENKINETICS_PROT_T5_RESIDUE_ROOT",
            "prot_t5_layer_19/residue_vecs",
        ),
        "bundle": "downloads/openkinetics-demo-prot-t5-residue-vecs.zip",
        "bundle_prefix": "embeddings/prot_t5/residue_vecs",
    },
    "pseq2sites": {
        "source_root": os.environ.get("OPENKINETICS_PSEQ2SITES_ROOT", "pseq2sites_scores"),
        "bundle": "downloads/openkinetics-demo-pseq2sites-scores.zip",
        "bundle_prefix": "pseq2sites/scores",
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


def build_model_bundle(release_dir, sequence_info_root, model_key, spec, sequences):
    source_root = (sequence_info_root / spec["source_root"]).resolve()
    bundle_path = release_dir / spec["bundle"]
    found = []
    missing = []
    for row in sequences:
        sequence_id = row["sequence_id"]
        source_path = source_root / ("%s.npy" % sequence_id)
        item = {
            "sequence_id": sequence_id,
            "source_path": str(source_path),
        }
        if source_path.exists() and source_path.is_file():
            found.append({**item, "size_bytes": source_path.stat().st_size})
        else:
            missing.append(item)

    report = {
        "model_key": model_key,
        "source_root": str(source_root),
        "total_sequences": len(sequences),
        "found": len(found),
        "missing": len(missing),
        "missing_sequences": missing,
        "join_key": "sequence_id",
        "file_format": "NumPy .npy",
    }
    write_json(release_dir / "artifact_reports" / ("%s.json" % model_key), report)

    if not found:
        remove_stale(bundle_path)
        return report

    ensure_parent(bundle_path)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.txt", bundle_readme(model_key, spec, report))
        bundle.writestr("manifest.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
        for item in found:
            source_path = Path(item["source_path"])
            arcname = "%s/%s.npy" % (spec["bundle_prefix"], item["sequence_id"])
            bundle.write(source_path, arcname=arcname)
    return report


def bundle_readme(model_key, spec, report):
    return (
        "OpenKinetics Data sequence artifact bundle\n"
        "model_key: %s\n"
        "join_key: sequence_id\n"
        "source_root: %s\n"
        "found: %s\n"
        "missing: %s\n"
        "format: NumPy .npy\n"
    ) % (
        model_key,
        spec["source_root"],
        report["found"],
        report["missing"],
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
