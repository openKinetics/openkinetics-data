"""Release artifact definitions for the data portal."""

from pathlib import Path
import hashlib

from django.conf import settings


MEASUREMENT_FIELDS = [
    "record_key",
    "measurement_key",
    "measurement_id",
    "review_key",
    "enzyme_name",
    "ec_number",
    "organism",
    "primary_uniprot_id",
    "sequence_id",
    "sequence_length",
    "sequence_variant_status",
    "mutation_signature",
    "wild_type",
    "sequence_artifact_input_was_truncated",
    "sequence_artifact_input_strategy",
    "sequence_artifact_input_length",
    "sequence_artifact_input_sha256",
    "substrate_id",
    "substrate_name",
    "pubchem_cid",
    "smiles",
    "inchi_key",
    "pair_id",
    "kcat",
    "kcat_unit",
    "km",
    "km_unit",
    "ki",
    "ki_unit",
    "kcat_over_km",
    "kcat_over_km_unit",
    "ph",
    "temperature_c",
    "source_db",
    "source_record_count",
    "pmid_count",
    "doi_count",
    "verification_status",
    "evidence_confidence_tier",
    "paper_grounding_status",
    "has_proof_excerpt",
]

SEQUENCE_FIELDS = [
    "sequence_id",
    "primary_uniprot_id",
    "length",
    "sequence",
    "fasta_header",
    "source_url",
    "sequence_variant_status",
    "mutation_signature",
    "wild_type",
    "sequence_artifact_generation",
    "sequence_artifact_input_was_truncated",
    "sequence_artifact_input_strategy",
    "sequence_artifact_input_length",
    "sequence_artifact_input_sha256",
]

SUBSTRATE_FIELDS = [
    "substrate_id",
    "name",
    "pubchem_query",
    "pubchem_cid",
    "smiles",
    "canonical_smiles",
    "isomeric_smiles",
    "inchi_key",
    "iupac_name",
    "molecular_formula",
    "source",
    "source_url",
]

SPLIT_FIELDS = [
    "record_key",
    "measurement_key",
    "measurement_id",
    "sequence_id",
    "substrate_id",
    "pair_id",
    "split_family",
    "split",
]

SEQUENCE_ARTIFACT_INDEX_FIELDS = [
    "sequence_id",
    "sequence",
    "length",
    "primary_uniprot_id",
    "artifact_available",
    "artifact_path",
    "array_shape",
    "array_dtype",
    "size_bytes",
    "sha256",
    "sequence_artifact_generation",
    "sequence_artifact_input_was_truncated",
    "sequence_artifact_input_strategy",
    "sequence_artifact_input_length",
    "sequence_artifact_input_sha256",
]


def file_detail(path, file_format, description):
    return {
        "path": path,
        "format": file_format,
        "description": description,
    }


def details(summary, files, fields=None, notes=None):
    return {
        "summary": summary,
        "files": files,
        "fields": fields or [],
        "notes": notes or [],
    }


def gzip_jsonl_details(path, fields, description):
    return details(
        description,
        [file_detail(path, "Gzip-compressed JSON Lines", "One UTF-8 JSON object per line.")],
        fields,
        ["Decompress with gzip before reading as line-delimited JSON."],
    )


def gzip_csv_details(path, fields, description):
    return details(
        description,
        [file_detail(path, "Gzip-compressed CSV", "UTF-8 comma-separated table with a header row.")],
        fields,
        ["Decompress with gzip before reading as CSV."],
    )


def split_details(path):
    return details(
        "Split assignment CSV with one row per measurement for this split family.",
        [file_detail(path, "CSV", "UTF-8 comma-separated table with a header row.")],
        SPLIT_FIELDS,
        ["The split column is one of train, val, or test."],
    )


def embedding_command_details(model_key, array_path):
    return details(
        "Command-based bulk download for all available %s residue embedding arrays." % model_key,
        [
            file_detail(
                "artifact_indexes/{artifact_key}.jsonl.gz",
                "Gzip-compressed JSON Lines",
                "One row per available array with sequence_id, local path, raw download URL, size, dtype, shape, and sequence metadata.",
            ),
            file_detail(
                "downloads/{release_id}-{model_key}-download.sh",
                "Shell script",
                "Resumable curl commands that download raw .npy arrays into an openkinetics_embeddings folder.",
            ),
            file_detail(
                "downloads/{release_id}-{model_key}.urls.txt",
                "Plain text",
                "One raw .npy URL per line for aria2c or other parallel download tools.",
            ),
            file_detail(array_path, "NumPy .npy array", "Downloaded per-residue embedding matrix for one sequence."),
        ],
        SEQUENCE_ARTIFACT_INDEX_FIELDS,
        [
            "Use sequence_id to join rows to measurements.csv.gz and sequences.jsonl.gz.",
            "For sequences up to 1024 residues, each .npy matrix is aligned to the full sequence by residue order.",
            "For sequences longer than 1024 residues, embeddings are generated from the first 512 and last 512 residues, saved under the original sequence_id, and marked by sequence_artifact_input_was_truncated.",
            "Bulk embedding files are not pre-zipped in the release folder; copy the generated commands to download raw .npy files from the mounted artifact store.",
        ],
    )


def pseq2sites_bundle_details():
    return details(
        "ZIP archive containing sequence metadata, raw Pseq2Sites arrays, and readable per-residue score rows.",
        [
            file_detail("README.txt", "UTF-8 text", "Plain-language archive summary."),
            file_detail("manifest.json", "JSON object", "Archive counts, source root, join key, and file layout."),
            file_detail(
                "metadata/sequences.jsonl",
                "JSON Lines",
                "One row per release sequence, including the full amino-acid sequence and artifact availability.",
            ),
            file_detail(
                "metadata/artifacts.jsonl",
                "JSON Lines",
                "One row per available score array, including sequence, artifact path, dtype, shape, size, and checksum.",
            ),
            file_detail(
                "pseq2sites/scores.jsonl.gz",
                "Gzip-compressed JSON Lines",
                "One row per parsed score file with sequence_id, sequence, scores, score_count, and alignment summary.",
            ),
            file_detail(
                "pseq2sites/scores/{sequence_id}.npy",
                "NumPy .npy array",
                "Raw per-residue 0-1 binding-site probability vector for one sequence.",
            ),
        ],
        SEQUENCE_ARTIFACT_INDEX_FIELDS
        + [
            "scores",
            "score_count",
            "aligned_to_sequence",
            "aligned_to_sequence_artifact_input",
            "summary",
        ],
        [
            "Scores are aligned one value per residue when score_count equals sequence length.",
            "For sequences longer than 1024 residues, scores are generated from the first 512 and last 512 residues and marked by sequence_artifact_input_was_truncated.",
        ],
    )


FORMAT_DETAILS = {
    "manifest": details(
        "Release metadata as a single plain JSON file.",
        [
            file_detail(
                "manifest.json",
                "JSON object",
                "Release ID, title, generated timestamp, counts, attribution, schema notes, and download note.",
            )
        ],
    ),
    "checksums": details(
        "SHA-256 digest list for release files and generated bundles.",
        [
            file_detail(
                "checksums.sha256",
                "Plain text",
                "Each line is '<sha256>  <relative_path>' for one release file.",
            )
        ],
    ),
    "measurements_jsonl": gzip_jsonl_details(
        "measurements.jsonl.gz",
        MEASUREMENT_FIELDS,
        "Flat measurement records for programmatic loading.",
    ),
    "measurements_csv": gzip_csv_details(
        "measurements.csv.gz",
        MEASUREMENT_FIELDS,
        "Flat measurement records for spreadsheet and table workflows.",
    ),
    "sequences_fasta": details(
        "Unique protein sequences in FASTA format.",
        [
            file_detail(
                "sequences.fasta",
                "FASTA",
                "Headers are '>{sequence_id}|{primary_uniprot_id}|len={length}' followed by 80-character sequence lines.",
            )
        ],
    ),
    "sequences_jsonl": gzip_jsonl_details(
        "sequences.jsonl.gz",
        SEQUENCE_FIELDS,
        "Unique protein sequence metadata, including the full amino-acid sequence.",
    ),
    "substrates_jsonl": gzip_jsonl_details(
        "substrates.jsonl.gz",
        SUBSTRATE_FIELDS,
        "Unique substrate metadata, structures, and PubChem identifiers.",
    ),
    "record_details_jsonl": gzip_jsonl_details(
        "record_details.jsonl.gz",
        [
            "record_key",
            "measurement_id",
            "enzyme",
            "sequence",
            "substrate",
            "enzyme_substrate_pair",
            "measurements",
            "assay_conditions",
            "provenance",
            "evidence",
            "demo_splits",
        ],
        "Nested source objects used to import and serve record details.",
    ),
    "split_random": split_details("splits/random.csv"),
    "split_sequence_exclusive": split_details("splits/sequence_exclusive.csv"),
    "split_substrate_exclusive": split_details("splits/substrate_exclusive.csv"),
    "split_pair_exclusive": split_details("splits/pair_exclusive.csv"),
    "embedding_esm2": embedding_command_details(
        "ESM2",
        "embeddings/esm2/residue_vecs/{sequence_id}.npy",
    ),
    "embedding_esmc": embedding_command_details(
        "ESMC",
        "embeddings/esmc/residue_vecs/{sequence_id}.npy",
    ),
    "embedding_prot_t5": embedding_command_details(
        "ProtT5",
        "embeddings/prot_t5/residue_vecs/{sequence_id}.npy",
    ),
    "pseq2sites_binding_sites": pseq2sites_bundle_details(),
    "bundle_measurements": details(
        "ZIP archive containing measurement tables and release metadata.",
        [
            file_detail("manifest.json", "JSON object", "Release metadata."),
            file_detail("measurements.jsonl.gz", "Gzip-compressed JSON Lines", "Flat measurement records."),
            file_detail("measurements.csv.gz", "Gzip-compressed CSV", "Flat measurement table."),
            file_detail("checksums.sha256", "Plain text", "SHA-256 checksums when present."),
        ],
        MEASUREMENT_FIELDS,
    ),
    "bundle_ml_ready": details(
        "ZIP archive containing tabular measurements, sequence data, substrate data, and splits.",
        [
            file_detail("manifest.json", "JSON object", "Release metadata."),
            file_detail("measurements.jsonl.gz", "Gzip-compressed JSON Lines", "Flat measurement records."),
            file_detail("sequences.fasta", "FASTA", "Protein sequences keyed by sequence_id."),
            file_detail("sequences.jsonl.gz", "Gzip-compressed JSON Lines", "Protein sequence metadata with sequences."),
            file_detail("substrates.jsonl.gz", "Gzip-compressed JSON Lines", "Substrate metadata."),
            file_detail("splits/*.csv", "CSV", "Random, sequence-exclusive, substrate-exclusive, and pair-exclusive splits."),
        ],
    ),
    "bundle_complete": details(
        "ZIP archive containing release metadata and tabular data files, excluding bulk embeddings.",
        [
            file_detail(
                "manifest.json, measurements, sequences, substrates, and splits",
                "Mixed release files",
                "Metadata and ML-ready tabular files; embeddings are downloaded separately with generated commands.",
            )
        ],
    ),
}


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
        "description": "Nested source record detail objects used by the importer and API.",
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
        "label": "ESM2 residue embeddings",
        "description": "Copyable commands for downloading ESM2 .npy residue matrices into a local folder.",
        "relative_path": "downloads/{release_id}-esm2-download.sh",
        "content_type": "text/x-shellscript",
        "metadata": {
            "model_key": "esm2",
            "raw_artifact_key": "esm2_residue",
            "download_mode": "command_panel",
            "feature_kind": "residue_vecs",
            "index_path": "artifact_indexes/esm2_residue.jsonl.gz",
            "urls_path": "downloads/{release_id}-esm2.urls.txt",
            "local_folder": "openkinetics_embeddings/esm2/residue_vecs",
        },
    },
    {
        "artifact_key": "embedding_esmc",
        "family": "embeddings",
        "label": "ESMC residue embeddings",
        "description": "Copyable commands for downloading ESMC .npy residue matrices into a local folder.",
        "relative_path": "downloads/{release_id}-esmc-download.sh",
        "content_type": "text/x-shellscript",
        "metadata": {
            "model_key": "esmc",
            "raw_artifact_key": "esmc_residue",
            "download_mode": "command_panel",
            "feature_kind": "residue_vecs",
            "index_path": "artifact_indexes/esmc_residue.jsonl.gz",
            "urls_path": "downloads/{release_id}-esmc.urls.txt",
            "local_folder": "openkinetics_embeddings/esmc/residue_vecs",
        },
    },
    {
        "artifact_key": "embedding_prot_t5",
        "family": "embeddings",
        "label": "ProtT5 residue embeddings",
        "description": "Copyable commands for downloading ProtT5 .npy residue matrices into a local folder.",
        "relative_path": "downloads/{release_id}-prot-t5-download.sh",
        "content_type": "text/x-shellscript",
        "metadata": {
            "model_key": "prot_t5",
            "raw_artifact_key": "prot_t5_residue",
            "download_mode": "command_panel",
            "feature_kind": "residue_vecs",
            "index_path": "artifact_indexes/prot_t5_residue.jsonl.gz",
            "urls_path": "downloads/{release_id}-prot-t5.urls.txt",
            "local_folder": "openkinetics_embeddings/prot_t5/residue_vecs",
        },
    },
    {
        "artifact_key": "pseq2sites_binding_sites",
        "family": "pseq2sites",
        "label": "Pseq2Sites score bundle",
        "description": "Zip bundle of Pseq2Sites scores with sequence metadata and readable score rows.",
        "relative_path": "downloads/openkinetics-demo-pseq2sites-scores.zip",
        "content_type": "application/zip",
        "metadata": {"model_key": "pseq2sites", "download_mode": "zip_bundle"},
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
        "artifact_key": "bundle_complete",
        "family": "bundles",
        "label": "Complete release bundle",
        "description": "Zip bundle containing release metadata and tabular data files. Embeddings are downloaded separately with commands.",
        "relative_path": "downloads/openkinetics-demo-complete.zip",
        "content_type": "application/zip",
    },
]


def release_dir(release_id):
    return Path(settings.RELEASES_ROOT) / release_id


def release_path(value, release_id):
    return (value or "").format(release_id=release_id)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_payload(release_id, definition):
    rel_path = release_path(definition["relative_path"], release_id)
    path = release_dir(release_id) / rel_path
    available = path.exists() and path.is_file()
    url_base = settings.RELEASES_URL_BASE.rstrip("/")
    metadata = dict(definition.get("metadata", {}))
    for key in ("index_path", "urls_path", "local_folder"):
        if key in metadata:
            metadata[key] = release_path(metadata[key], release_id)
    if metadata.get("index_path"):
        index_path = release_dir(release_id) / metadata["index_path"]
        metadata["index_url"] = "%s/%s/%s" % (url_base, release_id, metadata["index_path"])
        metadata["index_available"] = index_path.exists() and index_path.is_file()
        metadata["index_size_bytes"] = index_path.stat().st_size if metadata["index_available"] else None
    if metadata.get("urls_path"):
        urls_path = release_dir(release_id) / metadata["urls_path"]
        metadata["urls_url"] = "%s/%s/%s" % (url_base, release_id, metadata["urls_path"])
        metadata["urls_available"] = urls_path.exists() and urls_path.is_file()
        metadata["urls_size_bytes"] = urls_path.stat().st_size if metadata["urls_available"] else None
    metadata["format_details"] = FORMAT_DETAILS.get(definition["artifact_key"], {})
    payload = {
        "artifact_key": definition["artifact_key"],
        "family": definition["family"],
        "label": definition["label"],
        "description": definition.get("description", ""),
        "relative_path": rel_path,
        "url": "%s/%s/%s" % (url_base, release_id, rel_path),
        "content_type": definition.get("content_type", ""),
        "available": available,
        "metadata": metadata,
    }
    if available:
        payload["size_bytes"] = path.stat().st_size
        payload["sha256"] = file_sha256(path)
    else:
        payload["size_bytes"] = None
        payload["sha256"] = ""
    return payload
