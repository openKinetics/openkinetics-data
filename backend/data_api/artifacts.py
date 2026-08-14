"""Release artifact definitions for the data portal."""

from pathlib import Path
import hashlib

from django.conf import settings


ARTIFACT_DEFINITIONS = [
    {
        "artifact_key": "manifest",
        "family": "metadata",
        "label": "Release manifest",
        "description": "Machine-readable release metadata, counts, attribution, and schema notes.",
        "relative_path": "manifest.json",
        "content_type": "application/json",
    },
    {
        "artifact_key": "checksums",
        "family": "metadata",
        "label": "SHA-256 checksums",
        "description": "Checksums for release files and download bundles.",
        "relative_path": "checksums.sha256",
        "content_type": "text/plain",
    },
    {
        "artifact_key": "measurements_jsonl",
        "family": "measurements",
        "label": "Measurements JSONL",
        "description": "One normalized measurement record per line.",
        "relative_path": "measurements.jsonl.gz",
        "content_type": "application/gzip",
    },
    {
        "artifact_key": "measurements_csv",
        "family": "measurements",
        "label": "Measurements CSV",
        "description": "Flat measurement table for spreadsheet and quick-analysis workflows.",
        "relative_path": "measurements.csv.gz",
        "content_type": "application/gzip",
    },
    {
        "artifact_key": "sequences_fasta",
        "family": "sequences",
        "label": "Protein sequences FASTA",
        "description": "Unique protein sequences keyed by sequence_id.",
        "relative_path": "sequences.fasta",
        "content_type": "text/plain",
    },
    {
        "artifact_key": "sequences_jsonl",
        "family": "sequences",
        "label": "Protein sequences JSONL",
        "description": "Sequence metadata and UniProt source links keyed by sequence_id.",
        "relative_path": "sequences.jsonl.gz",
        "content_type": "application/gzip",
    },
    {
        "artifact_key": "substrates_jsonl",
        "family": "substrates",
        "label": "Substrates JSONL",
        "description": "Substrate identifiers, PubChem IDs, SMILES, and InChIKeys.",
        "relative_path": "substrates.jsonl.gz",
        "content_type": "application/gzip",
    },
    {
        "artifact_key": "record_details_jsonl",
        "family": "measurements",
        "label": "Record details JSONL",
        "description": "Nested record detail objects matching the API detail schema.",
        "relative_path": "record_details.jsonl.gz",
        "content_type": "application/gzip",
    },
    {
        "artifact_key": "split_random",
        "family": "splits",
        "label": "Random split assignments",
        "description": "Train/val/test assignment keyed by measurement and record IDs.",
        "relative_path": "splits/random.csv",
        "content_type": "text/csv",
    },
    {
        "artifact_key": "split_sequence_exclusive",
        "family": "splits",
        "label": "Sequence-exclusive split assignments",
        "description": "Split assignment with each sequence_id confined to one split.",
        "relative_path": "splits/sequence_exclusive.csv",
        "content_type": "text/csv",
    },
    {
        "artifact_key": "split_substrate_exclusive",
        "family": "splits",
        "label": "Substrate-exclusive split assignments",
        "description": "Split assignment with each substrate_id confined to one split.",
        "relative_path": "splits/substrate_exclusive.csv",
        "content_type": "text/csv",
    },
    {
        "artifact_key": "split_pair_exclusive",
        "family": "splits",
        "label": "Pair-exclusive split assignments",
        "description": "Split assignment keyed by sequence-substrate pair.",
        "relative_path": "splits/pair_exclusive.csv",
        "content_type": "text/csv",
    },
    {
        "artifact_key": "embedding_esm2",
        "family": "embeddings",
        "label": "ESM2 embeddings",
        "description": "Precomputed ESM2 sequence embeddings keyed by sequence_id.",
        "relative_path": "embeddings/esm2/sequence_embeddings.npz",
        "content_type": "application/octet-stream",
        "metadata": {"model_key": "esm2"},
    },
    {
        "artifact_key": "embedding_esmc",
        "family": "embeddings",
        "label": "ESMC embeddings",
        "description": "Precomputed ESMC sequence embeddings keyed by sequence_id.",
        "relative_path": "embeddings/esmc/sequence_embeddings.npz",
        "content_type": "application/octet-stream",
        "metadata": {"model_key": "esmc"},
    },
    {
        "artifact_key": "embedding_prot_t5",
        "family": "embeddings",
        "label": "ProtT5 embeddings",
        "description": "Precomputed ProtT5 sequence embeddings keyed by sequence_id.",
        "relative_path": "embeddings/prot_t5/sequence_embeddings.npz",
        "content_type": "application/octet-stream",
        "metadata": {"model_key": "prot_t5"},
    },
    {
        "artifact_key": "pseq2sites_binding_sites",
        "family": "pseq2sites",
        "label": "Pseq2Sites binding-site predictions",
        "description": "Per-residue Pseq2Sites outputs keyed by sequence_id.",
        "relative_path": "pseq2sites/binding_sites_by_sequence_id.tsv.gz",
        "content_type": "application/gzip",
        "metadata": {"model_key": "pseq2sites"},
    },
    {
        "artifact_key": "bundle_measurements",
        "family": "bundles",
        "label": "Measurements bundle",
        "description": "Zip bundle containing JSONL and CSV measurement tables.",
        "relative_path": "downloads/openkinetics-demo-measurements.zip",
        "content_type": "application/zip",
    },
    {
        "artifact_key": "bundle_ml_ready",
        "family": "bundles",
        "label": "ML-ready bundle",
        "description": "Zip bundle containing measurements, sequences, substrates, and splits.",
        "relative_path": "downloads/openkinetics-demo-ml-ready.zip",
        "content_type": "application/zip",
    },
    {
        "artifact_key": "bundle_embeddings",
        "family": "bundles",
        "label": "Embeddings bundle",
        "description": "Zip bundle for ESM2, ESMC, and ProtT5 embeddings.",
        "relative_path": "downloads/openkinetics-demo-embeddings.zip",
        "content_type": "application/zip",
    },
    {
        "artifact_key": "bundle_pseq2sites",
        "family": "bundles",
        "label": "Pseq2Sites bundle",
        "description": "Zip bundle for binding-site prediction artifacts.",
        "relative_path": "downloads/openkinetics-demo-pseq2sites.zip",
        "content_type": "application/zip",
    },
    {
        "artifact_key": "bundle_complete",
        "family": "bundles",
        "label": "Complete release bundle",
        "description": "Zip bundle containing all available release files.",
        "relative_path": "downloads/openkinetics-demo-complete.zip",
        "content_type": "application/zip",
    },
]


def release_dir(release_id):
    return Path(settings.RELEASES_ROOT) / release_id


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_payload(release_id, definition):
    rel_path = definition["relative_path"]
    path = release_dir(release_id) / rel_path
    available = path.exists() and path.is_file()
    url_base = settings.RELEASES_URL_BASE.rstrip("/")
    payload = {
        "artifact_key": definition["artifact_key"],
        "family": definition["family"],
        "label": definition["label"],
        "description": definition.get("description", ""),
        "relative_path": rel_path,
        "url": "%s/%s/%s" % (url_base, release_id, rel_path),
        "content_type": definition.get("content_type", ""),
        "available": available,
        "metadata": definition.get("metadata", {}),
    }
    if available:
        payload["size_bytes"] = path.stat().st_size
        payload["sha256"] = file_sha256(path)
    else:
        payload["size_bytes"] = None
        payload["sha256"] = ""
    return payload

