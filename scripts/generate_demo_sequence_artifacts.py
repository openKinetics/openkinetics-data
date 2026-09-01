#!/usr/bin/env python3
"""Generate demo sequence embeddings and Pseq2Sites score artifacts.

This script is intended to run on the GPU server that has the webKinPred
checkout, predictor seqmap database, KinForm models, and conda environments.
It resolves the committed demo sequences through the predictor seqmap DB, then
generates the release-facing per-sequence arrays under:

  {KINFORM_MEDIA_PATH}/sequence_info/esm2_layer_26/residue_vecs/{sequence_id}.npy
  {KINFORM_MEDIA_PATH}/sequence_info/esmc_layer_32/residue_vecs/{sequence_id}.npy
  {KINFORM_MEDIA_PATH}/sequence_info/prot_t5_layer_19/residue_vecs/{sequence_id}.npy
  {KINFORM_MEDIA_PATH}/sequence_info/pseq2sites_scores/{sequence_id}.npy
"""

from __future__ import annotations

import argparse
import csv
import gzip
import importlib.util
import json
import os
import pickle
import shlex
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


DEFAULT_RELEASE_ID = "openkinetics-catlog-demo-2026-08"
OPENKINETICS_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_PATH = OPENKINETICS_REPO_ROOT / "data" / "sample" / "openkinetics_demo_100.json"
DEFAULT_RELEASES_DIR = Path(
    os.environ.get("OPENKINETICS_RELEASES_ROOT", str(OPENKINETICS_REPO_ROOT / "releases"))
)
DEFAULT_WEBKINPRED_ROOT = Path(os.environ.get("GPU_EMBED_REPO_ROOT", "/home/saleh/webKinPred"))

MODEL_ORDER = ("prot_t5", "esm2", "esmc", "pseq2sites")
ARTIFACT_ROOTS = {
    "prot_t5": "prot_t5_layer_19/residue_vecs",
    "esm2": "esm2_layer_26/residue_vecs",
    "esmc": "esmc_layer_32/residue_vecs",
    "pseq2sites": "pseq2sites_scores",
}
KINFORM_MODEL_SCRIPTS = {
    "prot_t5": "models/KinForm/code/protein_embeddings/t5_embeddings.py",
    "esm2": "models/KinForm/code/protein_embeddings/prot_embeddings.py",
    "esmc": "models/KinForm/code/protein_embeddings/prot_embeddings.py",
}
KINFORM_MODEL_PYTHONS = {
    "prot_t5": "KINFORM_T5_PATH",
    "esm2": "KINFORM_ESM_PATH",
    "esmc": "KINFORM_ESMC_PATH",
}
BATCH_SIZE_ENVS = {
    "prot_t5": (
        "OPENKINETICS_PROT_T5_BATCH_SIZE",
        "KINFORM_PARALLEL_STREAM_T5_BATCH_SIZE",
        "KINFORM_PARALLEL_T5_BATCH_SIZE",
    ),
    "esm2": (
        "OPENKINETICS_ESM2_BATCH_SIZE",
        "KINFORM_PARALLEL_STREAM_ESM2_BATCH_SIZE",
        "KINFORM_PARALLEL_ESM2_BATCH_SIZE",
    ),
    "esmc": (
        "OPENKINETICS_ESMC_BATCH_SIZE",
        "KINFORM_PARALLEL_STREAM_ESMC_BATCH_SIZE",
        "KINFORM_PARALLEL_ESMC_BATCH_SIZE",
    ),
    "pseq2sites": (
        "OPENKINETICS_PSEQ2SITES_BATCH_SIZE",
        "KINFORM_PARALLEL_PSEQ_STREAM_BATCH_SIZE",
    ),
}


@dataclass(frozen=True)
class DemoSequence:
    sequence_id: str
    sequence: str
    source_sequence_id: str
    record_count: int

    @property
    def length(self) -> int:
        return len(self.sequence)


@dataclass(frozen=True)
class PreparedInputs:
    tmp_dir: Path
    seq_file: Path
    id_to_seq_pkl: Path
    seq_id_to_seq_json: Path


def positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def repo_path(raw: str | Path) -> Path:
    return Path(raw).expanduser().resolve()


def python_in_home_env(env_name: str) -> str:
    return str(Path.home() / "miniconda3" / "envs" / env_name / "bin" / "python")


def env_int(env: dict[str, str], names: tuple[str, ...], default: int) -> int:
    for name in names:
        raw = str(env.get(name, "")).strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value > 0:
            return value
    return default


def load_seqmap_db_module(webkinpred_root: Path):
    module_path = webkinpred_root / "tools" / "seqmap" / "utils" / "db.py"
    if not module_path.exists():
        raise SystemExit(f"Seqmap DB helper not found: {module_path}")
    spec = importlib.util.spec_from_file_location("webkinpred_seqmap_db", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load seqmap DB helper: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_sequence(sequence: str) -> str:
    return "".join(str(sequence).split()).upper()


def load_sequences_from_sample(path: Path) -> tuple[list[tuple[str, str]], int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    datapoints = payload.get("datapoints", [])
    rows: list[tuple[str, str]] = []
    for datapoint in datapoints:
        sequence_info = datapoint.get("sequence") or {}
        sequence = clean_sequence(sequence_info.get("sequence") or "")
        sequence_id = str(sequence_info.get("sequence_id") or "").strip()
        if sequence:
            rows.append((sequence_id, sequence))
    return rows, len(datapoints)


def load_sequences_from_release(release_dir: Path) -> tuple[list[tuple[str, str]], int]:
    path = release_dir / "sequences.jsonl.gz"
    rows: list[tuple[str, str]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            sequence = clean_sequence(row.get("sequence") or "")
            sequence_id = str(row.get("sequence_id") or "").strip()
            if sequence:
                rows.append((sequence_id, sequence))
    return rows, len(rows)


def resolve_demo_sequences(
    raw_rows: list[tuple[str, str]],
    *,
    seqmap_db: Path,
    webkinpred_root: Path,
    allow_id_mismatch: bool,
) -> list[DemoSequence]:
    seqmap_db.parent.mkdir(parents=True, exist_ok=True)
    seqmap_module = load_seqmap_db_module(webkinpred_root)
    con = seqmap_module.open_db(str(seqmap_db))
    by_sequence: dict[str, dict[str, object]] = {}
    mismatches: list[tuple[str, str, str]] = []
    try:
        for source_sequence_id, sequence in raw_rows:
            sequence_id = str(seqmap_module.get_or_create_id(con, sequence))
            if source_sequence_id and source_sequence_id != sequence_id:
                mismatches.append((source_sequence_id, sequence_id, sequence[:24]))
            item = by_sequence.setdefault(
                sequence,
                {
                    "sequence_id": sequence_id,
                    "source_sequence_id": source_sequence_id,
                    "record_count": 0,
                },
            )
            item["record_count"] = int(item["record_count"]) + 1
    finally:
        con.close()

    if mismatches and not allow_id_mismatch:
        preview = "; ".join(
            f"source={source_id} seqmap={seqmap_id} seq_prefix={prefix}"
            for source_id, seqmap_id, prefix in mismatches[:5]
        )
        raise SystemExit(
            "Demo sequence IDs do not match the predictor seqmap DB. "
            "Regenerate/normalize the release data first, or pass "
            f"--allow-id-mismatch to generate by seqmap IDs anyway. Examples: {preview}"
        )

    sequences = [
        DemoSequence(
            sequence_id=str(item["sequence_id"]),
            source_sequence_id=str(item["source_sequence_id"]),
            sequence=sequence,
            record_count=int(item["record_count"]),
        )
        for sequence, item in by_sequence.items()
    ]
    return sorted(sequences, key=lambda row: row.sequence_id)


def build_kinform_env(webkinpred_root: Path, media_path: Path, tools_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GPU_REPO_ROOT"] = str(webkinpred_root)
    env.setdefault("GPU_EMBED_REPO_ROOT", str(webkinpred_root))
    env["KINFORM_MEDIA_PATH"] = str(media_path)
    env["KINFORM_TOOLS_PATH"] = str(tools_path)
    env.setdefault(
        "KINFORM_DATA",
        str((webkinpred_root / "models" / "KinForm" / "results").resolve()),
    )
    env.setdefault("KINFORM_ESM_PATH", python_in_home_env("esm"))
    env.setdefault("KINFORM_ESMC_PATH", python_in_home_env("esmc"))
    env.setdefault("KINFORM_T5_PATH", python_in_home_env("prot_t5"))
    env.setdefault("KINFORM_PSEQ2SITES_PATH", python_in_home_env("pseq2sites"))

    t5_model_default = (
        webkinpred_root
        / "models"
        / "UniKP-main"
        / "models"
        / "protT5_xl"
        / "prot_t5_xl_uniref50"
    ).resolve()
    if t5_model_default.exists():
        env.setdefault("KINFORM_T5_MODEL_PATH", str(t5_model_default))

    env.setdefault("KINFORM_REQUIRE_CUDA", "1")
    repo_root_str = str(webkinpred_root)
    existing_pythonpath = str(env.get("PYTHONPATH", "")).strip()
    if existing_pythonpath:
        parts = [part for part in existing_pythonpath.split(os.pathsep) if part]
        if repo_root_str not in parts:
            env["PYTHONPATH"] = os.pathsep.join([repo_root_str] + parts)
    else:
        env["PYTHONPATH"] = repo_root_str
    return env


def artifact_path(media_path: Path, model_key: str, sequence_id: str) -> Path:
    return media_path / "sequence_info" / ARTIFACT_ROOTS[model_key] / f"{sequence_id}.npy"


def missing_artifact_ids(
    sequences: list[DemoSequence],
    *,
    media_path: Path,
    model_key: str,
    force: bool,
) -> list[str]:
    if force:
        return [row.sequence_id for row in sequences]
    return [
        row.sequence_id
        for row in sequences
        if not artifact_path(media_path, model_key, row.sequence_id).exists()
    ]


@contextmanager
def prepared_inputs(
    sequences: list[DemoSequence],
    sequence_ids: list[str] | None = None,
) -> Iterator[PreparedInputs]:
    selected_ids = set(sequence_ids or [row.sequence_id for row in sequences])
    seq_id_to_seq = {
        row.sequence_id: row.sequence
        for row in sequences
        if row.sequence_id in selected_ids
    }
    with tempfile.TemporaryDirectory(prefix="openkinetics_sequence_artifacts_") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        seq_file = tmp_dir / "seq_ids.txt"
        id_to_seq_pkl = tmp_dir / "id_to_seq.pkl"
        seq_id_to_seq_json = tmp_dir / "seq_id_to_seq.json"

        with seq_file.open("w", encoding="utf-8") as handle:
            for sequence_id in seq_id_to_seq:
                handle.write(f"{sequence_id}\n")

        with id_to_seq_pkl.open("wb") as handle:
            pickle.dump(seq_id_to_seq, handle, protocol=4)

        seq_id_to_seq_json.write_text(
            json.dumps(seq_id_to_seq, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        yield PreparedInputs(
            tmp_dir=tmp_dir,
            seq_file=seq_file,
            id_to_seq_pkl=id_to_seq_pkl,
            seq_id_to_seq_json=seq_id_to_seq_json,
        )


def run_command(cmd: list[str], *, env: dict[str, str], cwd: Path, dry_run: bool) -> None:
    print("+ " + shlex.join(cmd))
    if dry_run:
        return
    subprocess.run(cmd, env=env, cwd=str(cwd), check=True)


def generate_residue_embeddings(
    *,
    model_key: str,
    sequence_ids: list[str],
    sequences: list[DemoSequence],
    env: dict[str, str],
    webkinpred_root: Path,
    dry_run: bool,
    batch_size: int,
) -> None:
    if not sequence_ids:
        print(f"{model_key}: all residue arrays already exist.")
        return

    script = webkinpred_root / KINFORM_MODEL_SCRIPTS[model_key]
    python_path = env[KINFORM_MODEL_PYTHONS[model_key]]
    with prepared_inputs(sequences, sequence_ids) as inputs:
        cmd = [
            python_path,
            str(script),
            "--seq_file",
            str(inputs.seq_file),
            "--id_to_seq_file",
            str(inputs.id_to_seq_pkl),
            "--batch_size",
            str(batch_size),
            "--setting",
            "residue",
        ]
        if model_key == "prot_t5":
            cmd.extend(["--layers", "19"])
        elif model_key == "esm2":
            cmd.extend(["--models", "esm2", "--layers", "26"])
        elif model_key == "esmc":
            cmd.extend(["--models", "esmc", "--layers", "32"])
        else:
            raise ValueError(f"Unknown embedding model: {model_key}")
        print(f"{model_key}: generating {len(sequence_ids)} residue arrays.")
        run_command(cmd, env=env, cwd=webkinpred_root, dry_run=dry_run)


def read_binding_site_rows(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    rows: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            return rows
        key_col = "PDB" if "PDB" in reader.fieldnames else reader.fieldnames[0]
        score_col = (
            "Pred_BS_Scores"
            if "Pred_BS_Scores" in reader.fieldnames
            else (reader.fieldnames[1] if len(reader.fieldnames) > 1 else "")
        )
        if not score_col:
            return rows
        for row in reader:
            sequence_id = str(row.get(key_col, "")).strip()
            scores = str(row.get(score_col, "")).strip()
            if sequence_id and scores:
                rows[sequence_id] = scores
    return rows


def run_pseq2sites(
    *,
    sequences: list[DemoSequence],
    sequence_ids: list[str],
    env: dict[str, str],
    webkinpred_root: Path,
    dry_run: bool,
    batch_size: int,
) -> None:
    if not sequence_ids:
        print("pseq2sites: binding-site TSV already has all selected sequence IDs.")
        return

    code = r"""
import json
import os
import sys
from pathlib import Path

import pandas as pd

repo_root = Path(os.environ["GPU_REPO_ROOT"]).resolve()
sys.path.insert(0, str(repo_root / "models" / "KinForm" / "code"))

from config import BS_PRED_PATH
from pseq2sites.get_sites import get_sites

seq_map = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
batch_size = int(sys.argv[2])
bs_path = Path(BS_PRED_PATH)
bs_path.parent.mkdir(parents=True, exist_ok=True)
if bs_path.exists():
    bs_df = pd.read_csv(bs_path, sep="\t")
else:
    bs_df = pd.DataFrame(columns=["PDB", "Pred_BS_Scores"])
get_sites(seq_map, bs_df, batch_size=batch_size, save_path=str(bs_path), return_prot_t5=False)
"""

    with prepared_inputs(sequences, sequence_ids) as inputs:
        cmd = [
            env["KINFORM_PSEQ2SITES_PATH"],
            "-c",
            code,
            str(inputs.seq_id_to_seq_json),
            str(batch_size),
        ]
        print(f"pseq2sites: predicting {len(sequence_ids)} missing TSV rows.")
        run_command(cmd, env=env, cwd=webkinpred_root, dry_run=dry_run)


def score_text_to_array(score_text: str):
    import numpy as np

    values = [float(part) for part in score_text.split(",") if part.strip()]
    return np.asarray(values, dtype=np.float32)


def save_npy_atomic(path: Path, array) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp.npy")
    try:
        np.save(tmp_path, array)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def convert_pseq2sites_scores(
    *,
    sequences: list[DemoSequence],
    media_path: Path,
    force: bool,
    dry_run: bool,
) -> None:
    binding_sites_path = media_path / "pseq2sites" / "binding_sites_all.tsv"
    rows = read_binding_site_rows(binding_sites_path)
    missing_rows = [row.sequence_id for row in sequences if row.sequence_id not in rows]
    if missing_rows:
        preview = ", ".join(missing_rows[:8])
        raise SystemExit(
            "Pseq2Sites TSV is still missing scores for "
            f"{len(missing_rows)} sequences: {preview}"
        )

    wrote = 0
    skipped = 0
    for row in sequences:
        out_path = artifact_path(media_path, "pseq2sites", row.sequence_id)
        if out_path.exists() and not force:
            skipped += 1
            continue
        array = score_text_to_array(rows[row.sequence_id])
        if array.shape[0] != row.length:
            raise SystemExit(
                f"Pseq2Sites score length mismatch for {row.sequence_id}: "
                f"scores={array.shape[0]} sequence={row.length}"
            )
        print(f"pseq2sites: {'would write' if dry_run else 'writing'} {out_path}")
        if not dry_run:
            save_npy_atomic(out_path, array)
        wrote += 1
    print(f"pseq2sites: score arrays wrote={wrote} skipped={skipped}")


def validate_artifacts(
    *,
    sequences: list[DemoSequence],
    media_path: Path,
    models: list[str],
) -> None:
    import numpy as np

    errors: list[str] = []
    for model_key in models:
        for row in sequences:
            path = artifact_path(media_path, model_key, row.sequence_id)
            if not path.exists():
                errors.append(f"{model_key}:{row.sequence_id} missing {path}")
                continue
            try:
                array = np.load(path, mmap_mode="r")
            except Exception as exc:
                errors.append(f"{model_key}:{row.sequence_id} unreadable {exc}")
                continue
            if model_key == "pseq2sites":
                if tuple(array.shape) != (row.length,):
                    errors.append(
                        f"{model_key}:{row.sequence_id} shape={array.shape} expected=({row.length},)"
                    )
            else:
                if len(array.shape) != 2 or int(array.shape[0]) != row.length:
                    errors.append(
                        f"{model_key}:{row.sequence_id} shape={array.shape} expected first dim {row.length}"
                    )
    if errors:
        print("Artifact validation failed:")
        for error in errors[:50]:
            print(f"  - {error}")
        if len(errors) > 50:
            print(f"  - ... {len(errors) - 50} more")
        raise SystemExit(1)
    print(
        "Artifact validation passed for "
        f"{len(sequences)} sequences across {', '.join(models)}."
    )


def build_release_bundles(
    *,
    release_id: str,
    releases_dir: Path,
    media_path: Path,
    dry_run: bool,
) -> None:
    cmd = [
        sys.executable,
        str(OPENKINETICS_REPO_ROOT / "scripts" / "build_sequence_artifact_bundles.py"),
        "--release-id",
        release_id,
        "--releases-dir",
        str(releases_dir),
        "--sequence-info-root",
        str(media_path / "sequence_info"),
    ]
    run_command(cmd, env=dict(os.environ), cwd=OPENKINETICS_REPO_ROOT, dry_run=dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-path", default=str(DEFAULT_SAMPLE_PATH))
    parser.add_argument(
        "--source",
        choices=("sample", "release"),
        default="sample",
        help="Read demo sequences from the sample JSON or release sequences.jsonl.gz.",
    )
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument("--releases-dir", default=str(DEFAULT_RELEASES_DIR))
    parser.add_argument("--webkinpred-root", default=str(DEFAULT_WEBKINPRED_ROOT))
    parser.add_argument(
        "--media-path",
        default=os.environ.get("KINFORM_MEDIA_PATH", ""),
        help="KinForm media root. Defaults to {webkinpred-root}/media.",
    )
    parser.add_argument(
        "--tools-path",
        default="",
        help="webKinPred tools root. Defaults to {webkinpred-root}/tools.",
    )
    parser.add_argument(
        "--seqmap-db",
        default=os.environ.get("SEQMAP_DB", ""),
        help="Predictor seqmap.sqlite3 path. Defaults to {media-path}/sequence_info/seqmap.sqlite3.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=MODEL_ORDER,
        default=list(MODEL_ORDER),
        help="Artifact families to generate.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate files even when outputs exist.")
    parser.add_argument(
        "--allow-id-mismatch",
        action="store_true",
        help="Continue if committed sequence_id values differ from predictor seqmap IDs.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing artifacts.")
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--skip-release-bundles", action="store_true")
    parser.add_argument("--prot-t5-batch-size", type=positive_int, default=None)
    parser.add_argument("--esm2-batch-size", type=positive_int, default=None)
    parser.add_argument("--esmc-batch-size", type=positive_int, default=None)
    parser.add_argument("--pseq2sites-batch-size", type=positive_int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    webkinpred_root = repo_path(args.webkinpred_root)
    media_path = repo_path(args.media_path) if args.media_path else (webkinpred_root / "media").resolve()
    tools_path = repo_path(args.tools_path) if args.tools_path else (webkinpred_root / "tools").resolve()
    releases_dir = repo_path(args.releases_dir)
    seqmap_db = repo_path(args.seqmap_db) if args.seqmap_db else (
        media_path / "sequence_info" / "seqmap.sqlite3"
    ).resolve()

    if args.source == "sample":
        raw_rows, source_count = load_sequences_from_sample(repo_path(args.sample_path))
    else:
        raw_rows, source_count = load_sequences_from_release(releases_dir / args.release_id)
    sequences = resolve_demo_sequences(
        raw_rows,
        seqmap_db=seqmap_db,
        webkinpred_root=webkinpred_root,
        allow_id_mismatch=args.allow_id_mismatch,
    )
    if not sequences:
        raise SystemExit("No protein sequences found.")

    env = build_kinform_env(webkinpred_root, media_path, tools_path)
    selected_models = [model for model in MODEL_ORDER if model in set(args.models)]
    batch_sizes = {
        "prot_t5": args.prot_t5_batch_size or env_int(env, BATCH_SIZE_ENVS["prot_t5"], 1),
        "esm2": args.esm2_batch_size or env_int(env, BATCH_SIZE_ENVS["esm2"], 1),
        "esmc": args.esmc_batch_size or env_int(env, BATCH_SIZE_ENVS["esmc"], 1),
        "pseq2sites": args.pseq2sites_batch_size or env_int(env, BATCH_SIZE_ENVS["pseq2sites"], 4),
    }

    print(f"source={args.source} source_rows={source_count} raw_sequence_rows={len(raw_rows)}")
    print(f"unique_sequences={len(sequences)} seqmap_db={seqmap_db}")
    print(f"media_path={media_path}")
    print(f"models={','.join(selected_models)}")

    if args.validate_only:
        validate_artifacts(sequences=sequences, media_path=media_path, models=selected_models)
        return 0

    for model_key in selected_models:
        if model_key == "pseq2sites":
            continue
        sequence_ids = missing_artifact_ids(
            sequences,
            media_path=media_path,
            model_key=model_key,
            force=args.force,
        )
        generate_residue_embeddings(
            model_key=model_key,
            sequence_ids=sequence_ids,
            sequences=sequences,
            env=env,
            webkinpred_root=webkinpred_root,
            dry_run=args.dry_run,
            batch_size=batch_sizes[model_key],
        )

    if "pseq2sites" in selected_models:
        binding_sites_path = media_path / "pseq2sites" / "binding_sites_all.tsv"
        existing_rows = read_binding_site_rows(binding_sites_path)
        missing_tsv_ids = [
            row.sequence_id for row in sequences if row.sequence_id not in existing_rows
        ]
        run_pseq2sites(
            sequences=sequences,
            sequence_ids=missing_tsv_ids,
            env=env,
            webkinpred_root=webkinpred_root,
            dry_run=args.dry_run,
            batch_size=batch_sizes["pseq2sites"],
        )
        if not args.dry_run:
            convert_pseq2sites_scores(
                sequences=sequences,
                media_path=media_path,
                force=args.force,
                dry_run=args.dry_run,
            )
        else:
            print("pseq2sites: dry run skipped TSV-to-npy conversion.")

    if not args.skip_validation and not args.dry_run:
        validate_artifacts(sequences=sequences, media_path=media_path, models=selected_models)

    if not args.skip_release_bundles:
        build_release_bundles(
            release_id=args.release_id,
            releases_dir=releases_dir,
            media_path=media_path,
            dry_run=args.dry_run,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
