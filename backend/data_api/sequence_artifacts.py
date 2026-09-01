"""Helpers for predictor sequence artifact downloads.

The predictor app stores sequence artifacts under media/sequence_info using
seqmap IDs generated from sha256(sequence)[:12], with suffixes only if a rare
ID collision occurs. The data portal mounts that directory read-only.
"""

from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import zipfile

from django.conf import settings

from .npy_utils import NpyReadError, read_npy_flat_numbers, read_npy_metadata


SEQUENCE_ARTIFACT_DEFINITIONS = {
    "esm2_residue": {
        "label": "ESM2 residue embeddings",
        "description": "ZIP package containing the sequence metadata and full per-residue ESM2 .npy matrix.",
        "content_type": "application/zip",
        "raw_filename_suffix": "esm2_residue.npy",
        "download_filename_suffix": "esm2_residue.zip",
        "root_setting": "esm2_residue",
        "array_kind": "embedding",
        "array_path": "embeddings/esm2/residue_vecs/{sequence_id}.npy",
    },
    "esmc_residue": {
        "label": "ESMC residue embeddings",
        "description": "ZIP package containing the sequence metadata and full per-residue ESMC .npy matrix.",
        "content_type": "application/zip",
        "raw_filename_suffix": "esmc_residue.npy",
        "download_filename_suffix": "esmc_residue.zip",
        "root_setting": "esmc_residue",
        "array_kind": "embedding",
        "array_path": "embeddings/esmc/residue_vecs/{sequence_id}.npy",
    },
    "prot_t5_residue": {
        "label": "ProtT5 residue embeddings",
        "description": "ZIP package containing the sequence metadata and full per-residue ProtT5 .npy matrix.",
        "content_type": "application/zip",
        "raw_filename_suffix": "prot_t5_residue.npy",
        "download_filename_suffix": "prot_t5_residue.zip",
        "root_setting": "prot_t5_residue",
        "array_kind": "embedding",
        "array_path": "embeddings/prot_t5/residue_vecs/{sequence_id}.npy",
    },
    "pseq2sites_scores": {
        "label": "Pseq2Sites binding-site scores",
        "description": "ZIP package containing the sequence metadata, raw .npy scores, and readable per-residue scores.",
        "content_type": "application/zip",
        "raw_filename_suffix": "pseq2sites_scores.npy",
        "download_filename_suffix": "pseq2sites_scores.zip",
        "root_setting": "pseq2sites_scores",
        "array_kind": "scores",
        "array_path": "pseq2sites/scores/{sequence_id}.npy",
    },
}

PSEQ2SITES_PREVIEW_LIMIT = 10000


def sequence_sha256(sequence):
    return hashlib.sha256(sequence.encode("utf-8")).hexdigest()


def fallback_sequence_id(sequence):
    return sequence_sha256(sequence)[:12]


def resolve_sequence_id(sequence):
    """Return the predictor seqmap ID if the mounted DB exists, otherwise sha12."""
    root = Path(settings.SEQUENCE_INFO_ROOT)
    db_path = root / "seqmap.sqlite3"
    sha = sequence_sha256(sequence)
    if db_path.exists():
        try:
            uri = "file:%s?mode=ro" % db_path
            with sqlite3.connect(uri, uri=True) as connection:
                row = connection.execute("SELECT id FROM sequences WHERE sha256=?", (sha,)).fetchone()
                if row and row[0]:
                    return row[0]
        except sqlite3.Error:
            pass
    return fallback_sequence_id(sequence)


def artifact_path(sequence_id, artifact_key):
    definition = SEQUENCE_ARTIFACT_DEFINITIONS.get(artifact_key)
    if not definition:
        return None
    rel_root = settings.SEQUENCE_ARTIFACT_ROOTS[definition["root_setting"]]
    root = (Path(settings.SEQUENCE_INFO_ROOT) / rel_root).resolve()
    path = (root / ("%s.npy" % sequence_id)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def sequence_metadata(sequence):
    return {
        "sequence_id": sequence.sequence_id,
        "sequence": sequence.sequence,
        "length": sequence.length,
        "primary_uniprot_id": sequence.primary_uniprot_id,
        "fasta_header": sequence.fasta_header,
        "source": sequence.source,
        "source_url": sequence.source_url,
        "sequence_variant_status": sequence.sequence_variant_status,
        "mutation_signature": sequence.mutation_signature,
        "wild_type": sequence.wild_type,
    }


def sequence_artifact_format_details(artifact_key):
    definition = SEQUENCE_ARTIFACT_DEFINITIONS[artifact_key]
    array_path = definition["array_path"]
    files = [
        {
            "path": "README.txt",
            "format": "UTF-8 text",
            "description": "Human-readable summary of this single-sequence artifact package.",
        },
        {
            "path": "manifest.json",
            "format": "JSON object",
            "description": "Package metadata, artifact key, sequence_id, sequence length, array path, dtype, and shape.",
        },
        {
            "path": "sequence.json",
            "format": "JSON object",
            "description": "The full amino-acid sequence plus UniProt/source metadata.",
        },
        {
            "path": array_path,
            "format": "NumPy .npy array",
            "description": "The original predictor artifact array for this sequence.",
        },
    ]
    if definition["array_kind"] == "scores":
        files.append(
            {
                "path": "pseq2sites/scores.json",
                "format": "JSON object",
                "description": "sequence_id, sequence, and a scores array aligned one value per residue when parsing succeeds.",
            }
        )
    return {
        "summary": "Single-sequence ZIP package with the sequence metadata and predictor artifact array.",
        "files": files,
        "notes": [
            "All residue-level arrays are aligned to the amino-acid sequence by 1-based residue position.",
            "Use sequence_id as the stable join key across release tables, sequence metadata, and arrays.",
        ],
    }


def _array_metadata(path):
    try:
        return read_npy_metadata(path)
    except (OSError, NpyReadError) as exc:
        return {"error": str(exc)}


def _score_summary(scores):
    finite_scores = [score for score in scores if score is not None]
    if not finite_scores:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": min(finite_scores),
        "max": max(finite_scores),
        "mean": sum(finite_scores) / len(finite_scores),
    }


def pseq2sites_prediction_payload(sequence):
    sequence_id = sequence.sequence_id or fallback_sequence_id(sequence.sequence)
    path = artifact_path(sequence_id, "pseq2sites_scores")
    payload = {
        "artifact_key": "pseq2sites_scores",
        "sequence_id": sequence_id,
        "available": False,
        "scores": [],
        "score_count": 0,
        "residue_count": len(sequence.sequence),
        "aligned_to_sequence": False,
        "summary": {"min": None, "max": None, "mean": None},
        "message": "Pseq2Sites score file is not available for this sequence.",
    }
    if not path or not path.exists() or not path.is_file():
        return payload
    try:
        scores = read_npy_flat_numbers(path, max_items=PSEQ2SITES_PREVIEW_LIMIT)
    except (OSError, NpyReadError) as exc:
        payload["message"] = str(exc)
        return payload
    payload.update(
        {
            "available": True,
            "scores": scores,
            "score_count": len(scores),
            "aligned_to_sequence": len(scores) == len(sequence.sequence),
            "summary": _score_summary(scores),
            "message": "",
        }
    )
    return payload


def sequence_artifact_archive(sequence, artifact_key, path):
    definition = SEQUENCE_ARTIFACT_DEFINITIONS[artifact_key]
    sequence_id = sequence.sequence_id or fallback_sequence_id(sequence.sequence)
    array_path = definition["array_path"].format(sequence_id=sequence_id)
    array_metadata = _array_metadata(path)
    sequence_payload = sequence_metadata(sequence)
    score_payload = None
    score_error = ""
    files = [
        {**item, "path": item["path"].format(sequence_id=sequence_id)}
        for item in sequence_artifact_format_details(artifact_key)["files"]
    ]
    if definition["array_kind"] == "scores":
        files = [item for item in files if item["path"] != "pseq2sites/scores.json"]
        try:
            scores = read_npy_flat_numbers(path, max_items=PSEQ2SITES_PREVIEW_LIMIT)
            score_payload = {
                "sequence_id": sequence_id,
                "sequence": sequence.sequence,
                "scores": scores,
                "score_count": len(scores),
                "aligned_to_sequence": len(scores) == len(sequence.sequence),
                "summary": _score_summary(scores),
            }
            files.append(
                {
                    "path": "pseq2sites/scores.json",
                    "format": "JSON object",
                    "description": "sequence_id, sequence, and a scores array aligned one value per residue.",
                }
            )
        except (OSError, NpyReadError) as exc:
            score_error = str(exc)
            files.append(
                {
                    "path": "pseq2sites/scores_parse_error.txt",
                    "format": "UTF-8 text",
                    "description": "Reason the score vector could not be decoded into readable JSON.",
                }
            )
    manifest = {
        "format_version": "openkinetics.sequence_artifact.v1",
        "artifact_key": artifact_key,
        "label": definition["label"],
        "sequence_id": sequence_id,
        "sequence_length": len(sequence.sequence),
        "array_kind": definition["array_kind"],
        "array_file": array_path,
        "array_format": "NumPy .npy",
        "array_metadata": array_metadata,
        "files": files,
    }

    archive = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.txt", sequence_artifact_readme(manifest))
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        bundle.writestr("sequence.json", json.dumps(sequence_payload, indent=2, sort_keys=True) + "\n")
        bundle.write(path, arcname=array_path)
        if definition["array_kind"] == "scores":
            if score_payload:
                bundle.writestr(
                    "pseq2sites/scores.json",
                    json.dumps(score_payload, indent=2, sort_keys=True) + "\n",
                )
            else:
                bundle.writestr("pseq2sites/scores_parse_error.txt", score_error + "\n")
    archive.seek(0)
    return archive


def sequence_artifact_readme(manifest):
    return (
        "OpenKinetics Data single-sequence artifact\n"
        "artifact_key: %(artifact_key)s\n"
        "sequence_id: %(sequence_id)s\n"
        "array_kind: %(array_kind)s\n"
        "array_file: %(array_file)s\n"
        "array_format: NumPy .npy\n"
        "sequence_metadata: sequence.json\n"
    ) % manifest


def sequence_artifact_payload(sequence, artifact_key):
    definition = SEQUENCE_ARTIFACT_DEFINITIONS[artifact_key]
    sequence_id = sequence.sequence_id or fallback_sequence_id(sequence.sequence)
    path = artifact_path(sequence_id, artifact_key)
    sequence_info_root = Path(settings.SEQUENCE_INFO_ROOT).resolve()
    available = bool(path and path.exists() and path.is_file())
    relative_path = ""
    if path:
        try:
            relative_path = str(path.relative_to(sequence_info_root))
        except ValueError:
            relative_path = str(path)
    url_base = settings.SEQUENCE_ARTIFACTS_URL_BASE.rstrip("/")
    payload = {
        "artifact_key": artifact_key,
        "label": definition["label"],
        "description": definition["description"],
        "sequence_id": sequence_id,
        "content_type": definition["content_type"],
        "available": available,
        "url": "%s/sequences/%s/artifacts/%s/" % (url_base, sequence_id, artifact_key),
        "source_filename": "%s.npy" % sequence_id,
        "size_bytes": path.stat().st_size if available else None,
        "relative_path": relative_path,
        "format_details": sequence_artifact_format_details(artifact_key),
    }
    return payload


def sequence_artifacts_payload(sequence):
    return [
        sequence_artifact_payload(sequence, artifact_key)
        for artifact_key in SEQUENCE_ARTIFACT_DEFINITIONS
    ]
