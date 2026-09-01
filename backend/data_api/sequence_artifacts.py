"""Helpers for predictor sequence artifact downloads.

The predictor app stores sequence artifacts under media/sequence_info using
seqmap IDs generated from sha256(sequence)[:12], with suffixes only if a rare
ID collision occurs. The data portal mounts that directory read-only.
"""

from pathlib import Path
import hashlib
import sqlite3

from django.conf import settings


SEQUENCE_ARTIFACT_DEFINITIONS = {
    "esm2_residue": {
        "label": "ESM2 residue embeddings",
        "description": "Full per-residue ESM2 matrix, stored as an .npy file.",
        "content_type": "application/octet-stream",
        "filename_suffix": "esm2_residue.npy",
        "root_setting": "esm2_residue",
    },
    "esmc_residue": {
        "label": "ESMC residue embeddings",
        "description": "Full per-residue ESMC matrix, stored as an .npy file.",
        "content_type": "application/octet-stream",
        "filename_suffix": "esmc_residue.npy",
        "root_setting": "esmc_residue",
    },
    "prot_t5_residue": {
        "label": "ProtT5 residue embeddings",
        "description": "Full per-residue ProtT5 matrix, stored as an .npy file.",
        "content_type": "application/octet-stream",
        "filename_suffix": "prot_t5_residue.npy",
        "root_setting": "prot_t5_residue",
    },
    "pseq2sites_scores": {
        "label": "Pseq2Sites binding-site scores",
        "description": "Per-residue 0-1 binding-site probabilities, stored as an .npy file.",
        "content_type": "application/octet-stream",
        "filename_suffix": "pseq2sites_scores.npy",
        "root_setting": "pseq2sites_scores",
    },
}


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
        "size_bytes": path.stat().st_size if available else None,
        "relative_path": relative_path,
    }
    return payload


def sequence_artifacts_payload(sequence):
    return [
        sequence_artifact_payload(sequence, artifact_key)
        for artifact_key in SEQUENCE_ARTIFACT_DEFINITIONS
    ]
