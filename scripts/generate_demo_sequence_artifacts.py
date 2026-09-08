#!/usr/bin/env python3
"""Generate OpenKinetics demo sequence artifact arrays via the GPU service.

Default mode is for the production data server:

  python3 scripts/generate_demo_sequence_artifacts.py

It resolves the committed demo sequences through the predictor seqmap DB,
submits the missing sequence IDs to the remote GPU embedding service, waits for
completion, validates the shared artifact cache, then rebuilds release bundles.

GPU worker mode is for GPU_EMBED_STEP_CMD_OPENKINETICS_DEMO_SEQUENCE_ARTIFACTS:

  python3 scripts/generate_demo_sequence_artifacts.py --worker-mode \
    --seq-id-to-seq-file {seq_id_to_seq_file}
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import csv
import gzip
import hashlib
import importlib.util
import json
import os
import pickle
import queue
import shutil
import shlex
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


DEFAULT_RELEASE_ID = "openkinetics-catlog-demo-2026-08"
OPENKINETICS_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_PATH = OPENKINETICS_REPO_ROOT / "data" / "sample" / "openkinetics_demo_100.json"
TRUNCATED_ARTIFACT_N_TERMINAL_RESIDUES = 512
TRUNCATED_ARTIFACT_C_TERMINAL_RESIDUES = 512
TRUNCATED_ARTIFACT_INPUT_LENGTH = (
    TRUNCATED_ARTIFACT_N_TERMINAL_RESIDUES + TRUNCATED_ARTIFACT_C_TERMINAL_RESIDUES
)
DEFAULT_RELEASES_DIR = Path(
    os.environ.get("OPENKINETICS_RELEASES_ROOT", str(OPENKINETICS_REPO_ROOT / "releases"))
)
DEFAULT_WEBKINPRED_ROOT = Path(os.environ.get("GPU_EMBED_REPO_ROOT", "/home/saleh/webKinPred"))
DEFAULT_GPU_STEP_KEY = "openkinetics_demo_sequence_artifacts"
DEFAULT_GPU_WORKER_SCRIPT = Path(
    os.environ.get(
        "OPENKINETICS_GPU_WORKER_SCRIPT",
        str(
            Path(os.environ.get("OPENKINETICS_GPU_REPO_ROOT", str(OPENKINETICS_REPO_ROOT)))
            / "scripts"
            / "generate_demo_sequence_artifacts.py"
        ),
    )
)

MODEL_ORDER = ("prot_t5", "esm2", "esmc", "pseq2sites")
ARTIFACT_ROOTS = {
    "prot_t5": "prot_t5_last/residue_vecs",
    "esm2": "esm2_layer_33/residue_vecs",
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
STREAM_EVENT_MODEL_KEYS = {
    ("t5", "prot_t5_last"): "prot_t5",
    ("esm2", "esm2_layer_33"): "esm2",
    ("esmc", "esmc_layer_32"): "esmc",
}
STREAM_HEADER_LEN_BYTES = 8
STREAM_MAX_HEADER_BYTES = 1024 * 1024
STREAM_MAX_PAYLOAD_BYTES = 512 * 1024 * 1024


class StreamProtocolError(RuntimeError):
    pass


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


@dataclass
class StreamWorkerState:
    name: str
    attempts: int = 0
    process: subprocess.Popen | None = None
    tmp_inputs_dir: Path | None = None
    active_seq_ids: set[str] = field(default_factory=set)
    active_seq_count: int = 0
    started_at_monotonic: float | None = None
    stream_done_received: bool = False
    waiting_for_stream_done_since: float | None = None
    pseq_batch_size: int | None = None


@dataclass
class _StreamServerClient:
    sock: socket.socket
    send_lock: threading.Lock = field(default_factory=threading.Lock)


class LocalSeqmapDb:
    """Fallback copy of tools/seqmap/utils/db.py for production-only checkouts."""

    @staticmethod
    def open_db(db_path: str) -> sqlite3.Connection:
        con = sqlite3.connect(
            db_path,
            timeout=5,
            isolation_level=None,
            check_same_thread=False,
        )
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA temp_store=MEMORY")
        return con

    @staticmethod
    def get_or_create_id(con: sqlite3.Connection, sequence: str) -> str:
        sha = hashlib.sha256(sequence.encode("utf-8")).hexdigest()
        con.execute(
            "UPDATE sequences SET last_seen_at=CURRENT_TIMESTAMP, "
            "uses_count=uses_count+1 WHERE sha256=?",
            (sha,),
        )
        row = con.execute("SELECT id FROM sequences WHERE sha256=?", (sha,)).fetchone()
        if row:
            return str(row[0])

        base = sha[:12]
        suffix = 0
        while True:
            candidate = base if suffix == 0 else f"{base}_{suffix}"
            try:
                con.execute(
                    "INSERT INTO sequences(id, seq, sha256, len, created_at, last_seen_at, uses_count) "
                    "VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)",
                    (candidate, sequence, sha, len(sequence)),
                )
                return candidate
            except sqlite3.IntegrityError:
                row = con.execute("SELECT id FROM sequences WHERE sha256=?", (sha,)).fetchone()
                if row:
                    return str(row[0])
                suffix += 1


def positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def repo_path(raw: str | Path) -> Path:
    return Path(raw).expanduser().resolve()


def default_sequence_info_root() -> str:
    configured = str(os.environ.get("OPENKINETICS_SEQUENCE_INFO_ROOT", "")).strip()
    if configured:
        return configured
    media_path = str(os.environ.get("KINFORM_MEDIA_PATH", "")).strip()
    if media_path:
        return str((Path(media_path).expanduser() / "sequence_info").resolve())
    candidate = Path("/sequence_info")
    if candidate.exists():
        return str(candidate)
    return str((DEFAULT_WEBKINPRED_ROOT / "media" / "sequence_info").resolve())


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
        return LocalSeqmapDb
    spec = importlib.util.spec_from_file_location("webkinpred_seqmap_db", module_path)
    if spec is None or spec.loader is None:
        return LocalSeqmapDb
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dry_run_resolve_seqmap_ids(
    raw_rows: list[tuple[str, str]],
    *,
    seqmap_db: Path,
) -> list[DemoSequence] | None:
    if not seqmap_db.exists():
        print(f"seqmap_db={seqmap_db} is missing; dry run will use committed sequence IDs.")
        found_ids: dict[str, str] = {}
    else:
        sha_by_sequence = {
            sequence: hashlib.sha256(sequence.encode("utf-8")).hexdigest()
            for _source_sequence_id, sequence in raw_rows
        }
        found_ids = {}
        uri = f"file:{seqmap_db}?mode=ro"
        with sqlite3.connect(uri, uri=True) as con:
            for sequence, sha in sha_by_sequence.items():
                row = con.execute("SELECT id FROM sequences WHERE sha256=?", (sha,)).fetchone()
                if row:
                    found_ids[sequence] = str(row[0])

    by_sequence: dict[str, dict[str, object]] = {}
    for source_sequence_id, sequence in raw_rows:
        sequence_id = found_ids.get(sequence)
        if not sequence_id:
            sequence_id = source_sequence_id or hashlib.sha256(sequence.encode("utf-8")).hexdigest()[:12]
        item = by_sequence.setdefault(
            sequence,
            {
                "sequence_id": sequence_id,
                "source_sequence_id": source_sequence_id or sequence_id,
                "record_count": 0,
            },
        )
        item["record_count"] = int(item["record_count"]) + 1
    return sorted(
        [
            DemoSequence(
                sequence_id=str(item["sequence_id"]),
                source_sequence_id=str(item["source_sequence_id"]),
                sequence=sequence,
                record_count=int(item["record_count"]),
            )
            for sequence, item in by_sequence.items()
        ],
        key=lambda row: row.sequence_id,
    )


def clean_sequence(sequence: str) -> str:
    return "".join(str(sequence).split()).upper()


def sequence_artifact_input_sequence(sequence: str) -> str:
    if len(sequence) <= TRUNCATED_ARTIFACT_INPUT_LENGTH:
        return sequence
    return (
        sequence[:TRUNCATED_ARTIFACT_N_TERMINAL_RESIDUES]
        + sequence[-TRUNCATED_ARTIFACT_C_TERMINAL_RESIDUES:]
    )


def sequence_artifact_input_length(sequence: str) -> int:
    return len(sequence_artifact_input_sequence(sequence))


def sequence_artifact_generation_summary(sequence: str) -> dict[str, object]:
    input_sequence = sequence_artifact_input_sequence(sequence)
    was_truncated = len(input_sequence) != len(sequence)
    summary = {
        "input_sequence_was_truncated": was_truncated,
        "input_strategy": "first_512_last_512" if was_truncated else "full_sequence",
        "original_sequence_length": len(sequence),
        "input_sequence_length": len(input_sequence),
        "input_sequence_sha256": hashlib.sha256(input_sequence.encode("utf-8")).hexdigest(),
    }
    if was_truncated:
        summary.update(
            {
                "truncation_n_terminal_residues": TRUNCATED_ARTIFACT_N_TERMINAL_RESIDUES,
                "truncation_c_terminal_residues": TRUNCATED_ARTIFACT_C_TERMINAL_RESIDUES,
                "truncation_note": (
                    "Sequence artifact arrays are stored under the original sequence_id, "
                    "but model input used the first 512 and last 512 residues."
                ),
            }
        )
    return summary


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


def load_sequences_from_worker_file(path: Path) -> list[DemoSequence]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected seq_id_to_seq object in {path}")
    rows = [
        DemoSequence(
            sequence_id=str(sequence_id).strip(),
            source_sequence_id=str(sequence_id).strip(),
            sequence=clean_sequence(sequence),
            record_count=1,
        )
        for sequence_id, sequence in payload.items()
        if str(sequence_id).strip() and clean_sequence(sequence)
    ]
    return sorted(rows, key=lambda row: row.sequence_id)


def resolve_demo_sequences(
    raw_rows: list[tuple[str, str]],
    *,
    seqmap_db: Path,
    webkinpred_root: Path,
    allow_id_mismatch: bool,
    dry_run: bool,
) -> list[DemoSequence]:
    if dry_run:
        return dry_run_resolve_seqmap_ids(raw_rows, seqmap_db=seqmap_db) or []

    if not seqmap_db.exists():
        raise SystemExit(f"seqmap DB not found: {seqmap_db}")

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


def artifact_path(sequence_info_root: Path, model_key: str, sequence_id: str) -> Path:
    return sequence_info_root / ARTIFACT_ROOTS[model_key] / f"{sequence_id}.npy"


def expected_artifact_shape(model_key: str, sequence: str) -> tuple[int, ...] | None:
    expected_length = sequence_artifact_input_length(sequence)
    if model_key == "pseq2sites":
        return (expected_length,)
    return (expected_length, -1)


def artifact_shape_matches(model_key: str, sequence: str, path: Path) -> bool:
    try:
        shape = read_npy_shape(path)
    except Exception:
        return False
    expected = expected_artifact_shape(model_key, sequence)
    if expected is None:
        return True
    if model_key == "pseq2sites":
        return shape == expected
    return len(shape) == 2 and int(shape[0]) == expected[0]


def missing_artifact_ids(
    sequences: list[DemoSequence],
    *,
    sequence_info_root: Path,
    model_key: str,
    force: bool,
) -> list[str]:
    if force:
        return [row.sequence_id for row in sequences]
    return [
        row.sequence_id
        for row in sequences
        if (
            not artifact_path(sequence_info_root, model_key, row.sequence_id).exists()
            or not artifact_shape_matches(
                model_key,
                row.sequence,
                artifact_path(sequence_info_root, model_key, row.sequence_id),
            )
        )
    ]


def ids_missing_any_artifact(
    sequences: list[DemoSequence],
    *,
    sequence_info_root: Path,
    models: list[str],
    force: bool,
) -> list[str]:
    if force:
        return [row.sequence_id for row in sequences]
    missing: set[str] = set()
    for model_key in models:
        missing.update(
            missing_artifact_ids(
                sequences,
                sequence_info_root=sequence_info_root,
                model_key=model_key,
                force=False,
            )
        )
    return sorted(missing)


@contextmanager
def prepared_inputs(
    sequences: list[DemoSequence],
    sequence_ids: list[str] | None = None,
) -> Iterator[PreparedInputs]:
    selected_ids = set(sequence_ids or [row.sequence_id for row in sequences])
    seq_id_to_seq = {
        row.sequence_id: sequence_artifact_input_sequence(row.sequence)
        for row in sequences
        if row.sequence_id in selected_ids
    }
    truncated_count = sum(
        1
        for row in sequences
        if row.sequence_id in selected_ids
        and sequence_artifact_input_length(row.sequence) != row.length
    )
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
        if truncated_count:
            print(
                "artifact_input_truncation "
                f"sequences={truncated_count} strategy=first_512_last_512 "
                "outputs_keyed_by=original_sequence_id"
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


def env_bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _safe_job_slug(raw: str | None) -> str:
    value = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in str(raw or "").strip()
    ).strip("_")
    return value or "openkinetics"


def _recvn(sock: socket.socket, nbytes: int) -> bytes:
    out = bytearray()
    while len(out) < nbytes:
        chunk = sock.recv(nbytes - len(out))
        if not chunk:
            raise EOFError("Socket closed while reading stream frame.")
        out.extend(chunk)
    return bytes(out)


def stream_send_frame(sock: socket.socket, header: dict[str, Any], payload: bytes = b"") -> None:
    header_copy = dict(header)
    header_copy["payload_nbytes"] = int(len(payload))
    header_bytes = json.dumps(
        header_copy,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")
    sock.sendall(
        len(header_bytes).to_bytes(STREAM_HEADER_LEN_BYTES, byteorder="big", signed=False)
    )
    sock.sendall(header_bytes)
    if payload:
        sock.sendall(payload)


def stream_recv_frame(sock: socket.socket) -> tuple[dict[str, Any], bytes]:
    header_len = int.from_bytes(
        _recvn(sock, STREAM_HEADER_LEN_BYTES),
        byteorder="big",
        signed=False,
    )
    if header_len <= 0:
        raise StreamProtocolError(f"Invalid stream header size: {header_len}")
    if header_len > STREAM_MAX_HEADER_BYTES:
        raise StreamProtocolError(
            f"Stream header too large: {header_len} > {STREAM_MAX_HEADER_BYTES}"
        )
    try:
        header = json.loads(_recvn(sock, header_len).decode("utf-8"))
    except Exception as exc:
        raise StreamProtocolError("Could not decode stream frame header.") from exc
    if not isinstance(header, dict):
        raise StreamProtocolError("Stream frame header must be a JSON object.")
    payload_nbytes = int(header.get("payload_nbytes", 0))
    if payload_nbytes < 0:
        raise StreamProtocolError(f"Invalid stream payload size: {payload_nbytes}")
    if payload_nbytes > STREAM_MAX_PAYLOAD_BYTES:
        raise StreamProtocolError(
            f"Stream payload too large: {payload_nbytes} > {STREAM_MAX_PAYLOAD_BYTES}"
        )
    payload = _recvn(sock, payload_nbytes) if payload_nbytes else b""
    return header, payload


def save_array_atomic(path: Path, arr: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".npy", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        np.save(tmp_path, np.ascontiguousarray(arr))
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


class AsyncNpyWriter:
    def __init__(self, max_workers: int) -> None:
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="openkinetics-npy-writer",
        )
        self._futures: list[concurrent.futures.Future] = []
        self._lock = threading.Lock()

    def submit(self, path: Path, arr: Any) -> None:
        import numpy as np

        arr_copy = np.ascontiguousarray(arr).copy()
        future = self._pool.submit(save_array_atomic, path, arr_copy)
        with self._lock:
            self._futures.append(future)

    def join(self) -> None:
        while True:
            with self._lock:
                futures, self._futures = self._futures, []
            if not futures:
                return
            for future in futures:
                future.result()

    def check(self) -> None:
        with self._lock:
            futures, self._futures = self._futures, []
        pending: list[concurrent.futures.Future] = []
        try:
            for future in futures:
                if future.done():
                    future.result()
                else:
                    pending.append(future)
        finally:
            if pending:
                with self._lock:
                    self._futures.extend(pending)

    def shutdown(self) -> None:
        self.join()
        self._pool.shutdown(wait=True)


class StreamEventServer:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.events: queue.Queue[tuple[str, int, dict[str, Any] | None, bytes | None]] = queue.Queue()
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._clients: dict[int, _StreamServerClient] = {}
        self._client_threads: dict[int, threading.Thread] = {}
        self._accept_thread: threading.Thread | None = None
        self._next_client_id = 1

    def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.socket_path))
        sock.listen(16)
        sock.settimeout(0.2)
        self._sock = sock
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="openkinetics-stream-accept",
            daemon=True,
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except Exception:
                if self._stop.is_set():
                    return
                continue
            conn.settimeout(None)
            with self._lock:
                client_id = self._next_client_id
                self._next_client_id += 1
                self._clients[client_id] = _StreamServerClient(sock=conn)
            self.events.put(("connect", client_id, None, None))
            thread = threading.Thread(
                target=self._client_loop,
                args=(client_id, conn),
                name=f"openkinetics-stream-client-{client_id}",
                daemon=True,
            )
            with self._lock:
                self._client_threads[client_id] = thread
            thread.start()

    def _client_loop(self, client_id: int, conn: socket.socket) -> None:
        try:
            while not self._stop.is_set():
                header, payload = stream_recv_frame(conn)
                self.events.put(("event", client_id, header, payload))
        except EOFError:
            pass
        except Exception as exc:
            self.events.put(("error", client_id, {"error": str(exc)}, None))
        finally:
            self.events.put(("disconnect", client_id, None, None))
            with self._lock:
                client = self._clients.pop(client_id, None)
                self._client_threads.pop(client_id, None)
            if client is not None:
                try:
                    client.sock.close()
                except Exception:
                    pass

    def send(self, client_id: int, header: dict[str, Any], payload: bytes = b"") -> None:
        with self._lock:
            client = self._clients.get(client_id)
        if client is None:
            raise RuntimeError(f"Stream client {client_id} is not connected.")
        with client.send_lock:
            stream_send_frame(client.sock, header, payload)

    def recv_event(
        self,
        timeout_seconds: float,
    ) -> tuple[str, int, dict[str, Any] | None, bytes | None] | None:
        try:
            return self.events.get(timeout=max(0.0, timeout_seconds))
        except queue.Empty:
            return None

    def drain_events(
        self,
        *,
        max_items: int,
    ) -> list[tuple[str, int, dict[str, Any] | None, bytes | None]]:
        out: list[tuple[str, int, dict[str, Any] | None, bytes | None]] = []
        while len(out) < max_items:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                break
        return out

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
            threads = list(self._client_threads.values())
            self._client_threads.clear()
        for client in clients:
            try:
                client.sock.close()
            except Exception:
                pass
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1.0)
        for thread in threads:
            thread.join(timeout=1.0)
        self.socket_path.unlink(missing_ok=True)


def decode_stream_array(header: dict[str, Any], payload: bytes):
    import numpy as np

    dtype = np.dtype(str(header.get("dtype") or "float32"))
    raw_shape = header.get("shape")
    if not isinstance(raw_shape, list | tuple) or not raw_shape:
        raise RuntimeError(f"Invalid stream array shape in header: {header}")
    shape = tuple(int(value) for value in raw_shape)
    expected_nbytes = int(dtype.itemsize)
    for dim in shape:
        expected_nbytes *= dim
    if expected_nbytes != len(payload):
        raise RuntimeError(
            f"Stream payload size mismatch: payload={len(payload)} expected={expected_nbytes}"
        )
    return np.frombuffer(payload, dtype=dtype).reshape(shape).astype(np.float32, copy=False)


def validate_stream_array_shape(
    *,
    model_key: str,
    row: DemoSequence,
    arr: Any,
) -> None:
    expected_length = sequence_artifact_input_length(row.sequence)
    shape = tuple(int(value) for value in getattr(arr, "shape", ()))
    if model_key == "pseq2sites":
        if shape != (expected_length,):
            raise RuntimeError(
                f"{model_key}:{row.sequence_id} streamed shape={shape} expected=({expected_length},)"
            )
        return
    if len(shape) != 2 or shape[0] != expected_length:
        raise RuntimeError(
            f"{model_key}:{row.sequence_id} streamed shape={shape} expected first dim {expected_length}"
        )


def write_worker_inputs(seq_id_to_seq: dict[str, str]) -> tuple[Path, Path, Path]:
    tmp_dir = Path(tempfile.mkdtemp(prefix="openkinetics_stream_worker_"))
    seq_file = tmp_dir / "seq_ids.txt"
    id_to_seq_pkl = tmp_dir / "id_to_seq.pkl"
    seq_map_json = tmp_dir / "seq_id_to_seq.json"

    with seq_file.open("w", encoding="utf-8") as handle:
        for seq_id in seq_id_to_seq:
            handle.write(f"{seq_id}\n")
    with id_to_seq_pkl.open("wb") as handle:
        pickle.dump(seq_id_to_seq, handle, protocol=4)
    seq_map_json.write_text(json.dumps(seq_id_to_seq), encoding="utf-8")
    return seq_file, id_to_seq_pkl, seq_map_json


def cleanup_worker_inputs(state: StreamWorkerState) -> None:
    if state.tmp_inputs_dir is None:
        return
    tmp_dir = state.tmp_inputs_dir
    state.tmp_inputs_dir = None
    shutil.rmtree(tmp_dir, ignore_errors=True)


def terminate_worker(state: StreamWorkerState) -> None:
    if state.process is None:
        return
    if state.process.poll() is None:
        state.process.terminate()
        try:
            state.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            state.process.kill()
            state.process.wait(timeout=10)
    state.process = None


def start_stream_worker(
    cmd: list[str],
    env: dict[str, str],
    *,
    cwd: Path,
    dry_run: bool,
) -> subprocess.Popen | None:
    print("+ " + shlex.join(cmd))
    if dry_run:
        return None
    return subprocess.Popen(cmd, env=env, cwd=str(cwd))


def load_npy_array(path: Path):
    import numpy as np

    return np.load(path).astype(np.float32, copy=False)


def pseq_retry_batch_plan(env: dict[str, str], start_batch_size: int) -> list[int]:
    plan = [max(1, int(start_batch_size))]
    for candidate in (4, 2, 1):
        if candidate < plan[0] and candidate not in plan:
            plan.append(candidate)
    return plan


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
            cmd.extend(["--layers", "None"])
        elif model_key == "esm2":
            cmd.extend(["--models", "esm2", "--layers", "33"])
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


def pseq2sites_tsv_ids_needing_scores(
    sequences: list[DemoSequence],
    existing_rows: dict[str, str],
    *,
    force: bool,
) -> list[str]:
    if force:
        return [row.sequence_id for row in sequences]
    missing = []
    for row in sequences:
        score_text = existing_rows.get(row.sequence_id)
        if not score_text:
            missing.append(row.sequence_id)
            continue
        try:
            score_count = len(score_text_to_values(score_text))
        except ValueError:
            missing.append(row.sequence_id)
            continue
        if score_count != sequence_artifact_input_length(row.sequence):
            missing.append(row.sequence_id)
    return missing


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
if "PDB" in bs_df.columns and not bs_df.empty:
    bs_df = bs_df[~bs_df["PDB"].astype(str).isin(seq_map.keys())]
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


def run_parallel_stream_worker(
    *,
    sequences: list[DemoSequence],
    models: list[str],
    env: dict[str, str],
    webkinpred_root: Path,
    media_path: Path,
    sequence_info_root: Path,
    batch_sizes: dict[str, int],
    force: bool,
    dry_run: bool,
) -> None:
    seq_by_id = {row.sequence_id: row for row in sequences}
    seq_ids = [row.sequence_id for row in sequences]
    seq_id_to_input = {
        row.sequence_id: sequence_artifact_input_sequence(row.sequence)
        for row in sequences
    }
    truncated_count = sum(
        1
        for row in sequences
        if sequence_artifact_input_length(row.sequence) != row.length
    )

    stream_env = dict(env)
    stream_env.setdefault("KINFORM_PARALLEL_MAX_GPU_WORKERS", "2")
    stream_env.setdefault("KINFORM_PARALLEL_INCLUDE_PSEQ_IN_GPU_CAP", "1")
    stream_env.setdefault("KINFORM_PARALLEL_ASYNC_WRITE_WORKERS", "16")
    stream_env.setdefault("KINFORM_PARALLEL_PSEQ_SEND_QUEUE_SIZE", "256")
    stream_env.setdefault("KINFORM_PARALLEL_PSEQ_SENDS_PER_TICK", "10000")
    stream_env.setdefault("KINFORM_PARALLEL_STREAM_RECV_TIMEOUT_SECONDS", "0.05")
    stream_env.setdefault("KINFORM_PARALLEL_STREAM_MAX_EVENTS_PER_TICK", "512")
    stream_env.setdefault("KINFORM_PARALLEL_WORKER_DONE_WAIT_SECONDS", "30")
    stream_env.setdefault("KINFORM_PARALLEL_PSEQ_STREAM_READ_EXISTING_ON_START", "0")
    stream_env["KINFORM_STREAM_WRITE_MEAN_FILES"] = "0"
    stream_env.setdefault("KINFORM_REQUIRE_CUDA", "1")

    missing_by_model: dict[str, set[str]] = {
        model_key: set(
            missing_artifact_ids(
                sequences,
                sequence_info_root=sequence_info_root,
                model_key=model_key,
                force=force,
            )
        )
        for model_key in models
    }
    for model_key in MODEL_ORDER:
        missing_by_model.setdefault(model_key, set())

    pseq_targets = set(missing_by_model["pseq2sites"]) if "pseq2sites" in models else set()

    def has_valid_artifact(model_key: str, seq_id: str) -> bool:
        row = seq_by_id[seq_id]
        path = artifact_path(sequence_info_root, model_key, seq_id)
        return path.exists() and artifact_shape_matches(model_key, row.sequence, path)

    t5_needed_for_pseq = {
        seq_id
        for seq_id in pseq_targets
        if not has_valid_artifact("prot_t5", seq_id)
    }
    save_targets: dict[str, set[str]] = {
        "prot_t5": set(missing_by_model["prot_t5"]) | t5_needed_for_pseq,
        "esm2": set(missing_by_model["esm2"]),
        "esmc": set(missing_by_model["esmc"]),
        "pseq2sites": set(pseq_targets),
    }

    print(
        "openkinetics_parallel_stream_worker=1 "
        f"sequences={len(seq_ids)} "
        f"missing_prot_t5={len(missing_by_model['prot_t5'])} "
        f"missing_esm2={len(missing_by_model['esm2'])} "
        f"missing_esmc={len(missing_by_model['esmc'])} "
        f"missing_pseq2sites={len(pseq_targets)} "
        f"t5_dependency_for_pseq={len(t5_needed_for_pseq)} "
        f"truncated_artifact_inputs={truncated_count}"
    )

    if not any(save_targets.values()):
        print("openkinetics_parallel_stream: all selected artifacts already exist.")
        return

    t5_script = webkinpred_root / KINFORM_MODEL_SCRIPTS["prot_t5"]
    prot_script = webkinpred_root / KINFORM_MODEL_SCRIPTS["esm2"]
    pseq_stream_script = (
        webkinpred_root
        / "models"
        / "KinForm"
        / "code"
        / "pseq2sites"
        / "pseq2sites_stream_worker.py"
    )
    binding_sites_path = media_path / "pseq2sites" / "binding_sites_all.tsv"
    job_id = _safe_job_slug(os.environ.get("GPU_EMBED_JOB_ID") or os.environ.get("JOB_ID"))

    pseq_retry_plan = pseq_retry_batch_plan(stream_env, batch_sizes["pseq2sites"])
    max_gpu_workers = max(1, env_int(stream_env, ("KINFORM_PARALLEL_MAX_GPU_WORKERS",), 2))
    include_pseq_in_gpu_cap = env_bool(
        stream_env,
        "KINFORM_PARALLEL_INCLUDE_PSEQ_IN_GPU_CAP",
        True,
    )
    async_write_workers = max(
        1,
        env_int(stream_env, ("KINFORM_PARALLEL_ASYNC_WRITE_WORKERS",), 16),
    )
    pseq_send_queue_size = max(
        4,
        env_int(stream_env, ("KINFORM_PARALLEL_PSEQ_SEND_QUEUE_SIZE",), 256),
    )
    pseq_sends_per_tick = max(
        1,
        env_int(stream_env, ("KINFORM_PARALLEL_PSEQ_SENDS_PER_TICK",), 10000),
    )
    stream_recv_timeout_seconds = max(
        0.01,
        float(stream_env.get("KINFORM_PARALLEL_STREAM_RECV_TIMEOUT_SECONDS", "0.05")),
    )
    max_events_per_tick = max(
        16,
        env_int(stream_env, ("KINFORM_PARALLEL_STREAM_MAX_EVENTS_PER_TICK",), 512),
    )
    worker_done_wait_seconds = max(
        1.0,
        float(stream_env.get("KINFORM_PARALLEL_WORKER_DONE_WAIT_SECONDS", "30")),
    )

    socket_dir = Path(
        stream_env.get("KINFORM_PARALLEL_STREAM_SOCKET_DIR", "/tmp/webkinpred-gpu-embed/kinform")
    ).resolve()
    socket_path = socket_dir / f"{job_id}_{os.getpid()}_{int(time.time() * 1000) % 1000000}.sock"

    workers: dict[str, StreamWorkerState] = {
        "t5": StreamWorkerState(name="t5"),
        "esm2": StreamWorkerState(name="esm2"),
        "esmc": StreamWorkerState(name="esmc"),
        "pseq2sites": StreamWorkerState(name="pseq2sites"),
    }
    completed: dict[str, set[str]] = {model_key: set() for model_key in MODEL_ORDER}
    submitted_paths: set[Path] = set()
    t5_ready_for_pseq: set[str] = set()
    pseq_client_id: int | None = None
    pseq_client_lock = threading.Lock()
    sent_to_pseq: set[str] = set()
    queued_to_pseq: set[str] = set()
    pseq_finish_sent = False
    pseq_send_queue: queue.Queue[tuple[str, dict[str, Any], bytes] | None] = queue.Queue(
        maxsize=pseq_send_queue_size
    )
    pseq_send_results: queue.Queue[tuple[str, str, str]] = queue.Queue()
    pseq_sender_stop = threading.Event()
    server = StreamEventServer(socket_path)
    async_writer = AsyncNpyWriter(max_workers=async_write_workers)

    print(
        "openkinetics_parallel_stream_config "
        f"max_gpu_workers={max_gpu_workers} "
        f"include_pseq_in_gpu_cap={include_pseq_in_gpu_cap} "
        f"batch_t5={batch_sizes['prot_t5']} "
        f"batch_esm2={batch_sizes['esm2']} "
        f"batch_esmc={batch_sizes['esmc']} "
        f"batch_pseq_plan={','.join(str(value) for value in pseq_retry_plan)} "
        f"async_write_workers={async_write_workers} "
        f"socket={socket_path}"
    )

    def selected_force_regen(model_key: str, seq_id: str) -> bool:
        return force and seq_id in missing_by_model.get(model_key, set())

    def target_done(model_key: str, seq_id: str) -> bool:
        if seq_id in completed[model_key]:
            return True
        if selected_force_regen(model_key, seq_id):
            return False
        return has_valid_artifact(model_key, seq_id)

    def remaining_targets(model_key: str) -> set[str]:
        return {seq_id for seq_id in save_targets[model_key] if not target_done(model_key, seq_id)}

    def pseq_done(seq_id: str) -> bool:
        if seq_id in completed["pseq2sites"]:
            return True
        if selected_force_regen("pseq2sites", seq_id):
            return False
        return has_valid_artifact("pseq2sites", seq_id)

    def get_pseq_client_id() -> int | None:
        with pseq_client_lock:
            return pseq_client_id

    def set_pseq_client_id(value: int | None) -> None:
        nonlocal pseq_client_id
        with pseq_client_lock:
            pseq_client_id = value

    def drain_pseq_send_results() -> bool:
        updated = False
        while True:
            try:
                status, seq_id, detail = pseq_send_results.get_nowait()
            except queue.Empty:
                break
            updated = True
            queued_to_pseq.discard(seq_id)
            if status == "sent":
                sent_to_pseq.add(seq_id)
            else:
                sent_to_pseq.discard(seq_id)
                if detail:
                    print(f"openkinetics_parallel_stream pseq_send_retry seq_id={seq_id} reason={detail}")
        return updated

    def reset_pseq_send_state() -> None:
        set_pseq_client_id(None)
        sent_to_pseq.clear()
        queued_to_pseq.clear()
        while True:
            try:
                pseq_send_queue.get_nowait()
            except queue.Empty:
                break
        while True:
            try:
                pseq_send_results.get_nowait()
            except queue.Empty:
                break

    def pseq_sender_loop() -> None:
        while not pseq_sender_stop.is_set():
            try:
                item = pseq_send_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                return
            seq_id, header, payload = item
            client_id = get_pseq_client_id()
            if client_id is None:
                pseq_send_results.put(("retry", seq_id, "pseq client not connected"))
                continue
            try:
                server.send(client_id, header, payload)
                pseq_send_results.put(("sent", seq_id, ""))
            except Exception as exc:
                pseq_send_results.put(("retry", seq_id, str(exc)))

    pseq_sender_thread = threading.Thread(
        target=pseq_sender_loop,
        name=f"openkinetics-pseq-sender-{job_id}",
        daemon=True,
    )

    def queue_t5_for_pseq(seq_id: str, arr: Any | None = None) -> bool:
        if seq_id not in pseq_targets or pseq_done(seq_id):
            return False
        if seq_id in queued_to_pseq or seq_id in sent_to_pseq:
            return False
        if get_pseq_client_id() is None:
            return False
        row = seq_by_id[seq_id]
        if arr is None:
            path = artifact_path(sequence_info_root, "prot_t5", seq_id)
            if not path.exists() or not artifact_shape_matches("prot_t5", row.sequence, path):
                return False
            arr = load_npy_array(path)
        validate_stream_array_shape(model_key="prot_t5", row=row, arr=arr)
        payload = arr.astype("float32", copy=False).tobytes(order="C")
        header = {
            "type": "PSEQ_RESIDUE",
            "job_id": job_id,
            "seq_id": seq_id,
            "sequence": seq_id_to_input[seq_id],
            "dtype": "float32",
            "shape": [int(value) for value in arr.shape],
        }
        try:
            pseq_send_queue.put_nowait((seq_id, header, payload))
        except queue.Full:
            return False
        queued_to_pseq.add(seq_id)
        return True

    def needed_ids(worker_name: str) -> set[str]:
        if worker_name == "t5":
            out = set(remaining_targets("prot_t5"))
            for seq_id in pseq_targets:
                if pseq_done(seq_id):
                    continue
                if seq_id in queued_to_pseq or seq_id in sent_to_pseq:
                    continue
                if has_valid_artifact("prot_t5", seq_id) or seq_id in t5_ready_for_pseq:
                    continue
                out.add(seq_id)
            return out
        if worker_name in {"esm2", "esmc"}:
            return remaining_targets(worker_name)
        if worker_name == "pseq2sites":
            return {seq_id for seq_id in pseq_targets if not pseq_done(seq_id)}
        raise RuntimeError(f"Unknown stream worker: {worker_name}")

    def build_worker_cmd(
        worker_name: str,
        seq_file: Path,
        id_to_seq_pkl: Path,
        seq_map_json: Path,
        *,
        pseq_batch_size: int | None = None,
    ) -> list[str]:
        common_stream = [
            "--stream-mode",
            "--stream-socket",
            str(socket_path),
            "--stream-job-id",
            job_id,
            "--worker-name",
            worker_name,
        ]
        if worker_name == "t5":
            return [
                stream_env["KINFORM_T5_PATH"],
                str(t5_script),
                "--seq_file",
                str(seq_file),
                "--id_to_seq_file",
                str(id_to_seq_pkl),
                "--batch_size",
                str(batch_sizes["prot_t5"]),
                "--setting",
                "residue+mean",
                "--layers",
                "None",
                *common_stream,
            ]
        if worker_name == "esm2":
            return [
                stream_env["KINFORM_ESM_PATH"],
                str(prot_script),
                "--seq_file",
                str(seq_file),
                "--models",
                "esm2",
                "--layers",
                "33",
                "--setting",
                "residue+mean",
                "--id_to_seq_file",
                str(id_to_seq_pkl),
                "--batch_size",
                str(batch_sizes["esm2"]),
                *common_stream,
            ]
        if worker_name == "esmc":
            return [
                stream_env["KINFORM_ESMC_PATH"],
                str(prot_script),
                "--seq_file",
                str(seq_file),
                "--models",
                "esmc",
                "--layers",
                "32",
                "--setting",
                "residue+mean",
                "--id_to_seq_file",
                str(id_to_seq_pkl),
                "--batch_size",
                str(batch_sizes["esmc"]),
                *common_stream,
            ]
        if worker_name == "pseq2sites":
            return [
                stream_env["KINFORM_PSEQ2SITES_PATH"],
                str(pseq_stream_script),
                "--seq-id-to-seq-file",
                str(seq_map_json),
                "--binding-sites-path",
                str(binding_sites_path),
                "--batch-size",
                str(max(1, int(pseq_batch_size or batch_sizes["pseq2sites"]))),
                "--stream-mode",
                "--stream-socket",
                str(socket_path),
                "--stream-job-id",
                job_id,
                "--worker-name",
                worker_name,
            ]
        raise RuntimeError(f"Unknown stream worker: {worker_name}")

    gpu_capped_workers = (
        ("t5", "esm2", "esmc", "pseq2sites")
        if include_pseq_in_gpu_cap
        else ("t5", "esm2", "esmc")
    )
    launch_order = ("t5", "pseq2sites", "esm2", "esmc")

    def active_gpu_workers() -> int:
        return sum(1 for name in gpu_capped_workers if workers[name].process is not None)

    def can_launch(worker_name: str) -> bool:
        if worker_name not in gpu_capped_workers:
            return True
        return active_gpu_workers() < max_gpu_workers

    def launch_worker(worker_name: str) -> bool:
        state = workers[worker_name]
        if state.process is not None or not can_launch(worker_name):
            return False
        run_ids = needed_ids(worker_name)
        if not run_ids:
            return False
        max_attempts = len(pseq_retry_plan) if worker_name == "pseq2sites" else 2
        if state.attempts >= max_attempts:
            raise RuntimeError(
                f"{worker_name} exhausted retries with remaining_seq_count={len(run_ids)}"
            )
        seq_subset = {seq_id: seq_id_to_input[seq_id] for seq_id in seq_ids if seq_id in run_ids}
        seq_file, id_to_seq_pkl, seq_map_json = write_worker_inputs(seq_subset)
        state.tmp_inputs_dir = seq_file.parent
        pseq_batch_size = (
            pseq_retry_plan[state.attempts] if worker_name == "pseq2sites" else None
        )
        cmd = build_worker_cmd(
            worker_name,
            seq_file,
            id_to_seq_pkl,
            seq_map_json,
            pseq_batch_size=pseq_batch_size,
        )
        state.process = start_stream_worker(cmd, stream_env, cwd=webkinpred_root, dry_run=dry_run)
        state.active_seq_ids = set(run_ids)
        state.active_seq_count = len(run_ids)
        state.started_at_monotonic = time.monotonic()
        state.stream_done_received = False
        state.waiting_for_stream_done_since = None
        state.pseq_batch_size = pseq_batch_size
        if worker_name == "pseq2sites":
            reset_pseq_send_state()
        state.attempts += 1
        print(
            "openkinetics_parallel_stream_launch "
            f"worker={worker_name} attempt={state.attempts} seq_count={len(run_ids)}"
            + (f" pseq_batch_size={pseq_batch_size}" if pseq_batch_size else "")
        )
        return True

    def poll_worker(worker_name: str) -> bool:
        state = workers[worker_name]
        if state.process is None:
            return False
        rc = state.process.poll()
        if rc is None:
            return False
        if rc == 0 and not state.stream_done_received:
            now = time.monotonic()
            if state.waiting_for_stream_done_since is None:
                state.waiting_for_stream_done_since = now
                return False
            if now - state.waiting_for_stream_done_since < worker_done_wait_seconds:
                return False

        elapsed = 0.0
        if state.started_at_monotonic is not None:
            elapsed = max(0.0, time.monotonic() - state.started_at_monotonic)
        print(
            "openkinetics_parallel_stream_done "
            f"worker={worker_name} attempt={state.attempts} "
            f"seq_count={state.active_seq_count} elapsed_s={elapsed:.3f} rc={rc}"
        )
        cleanup_worker_inputs(state)
        state.process = None
        state.active_seq_ids = set()
        state.active_seq_count = 0
        state.started_at_monotonic = None
        state.waiting_for_stream_done_since = None

        remaining = needed_ids(worker_name)
        if rc == 0 and not remaining:
            return True
        max_attempts = len(pseq_retry_plan) if worker_name == "pseq2sites" else 2
        if remaining and state.attempts < max_attempts:
            return launch_worker(worker_name)
        if remaining:
            preview = ", ".join(sorted(remaining)[:8])
            raise RuntimeError(
                f"worker={worker_name} failed to produce {len(remaining)} remaining artifacts: {preview}"
            )
        return True

    def all_targets_done() -> bool:
        for model_key in ("prot_t5", "esm2", "esmc"):
            for seq_id in save_targets[model_key]:
                if not target_done(model_key, seq_id):
                    return False
        for seq_id in pseq_targets:
            if not pseq_done(seq_id):
                return False
        return True

    if dry_run:
        for name in launch_order:
            launch_worker(name)
            cleanup_worker_inputs(workers[name])
            workers[name].process = None
        print("openkinetics_parallel_stream: dry run stopped before launching workers.")
        return

    pseq_sender_thread.start()
    server.start()
    started_at = time.monotonic()
    last_progress_at = 0.0

    try:
        for name in launch_order:
            launch_worker(name)

        while True:
            had_activity = False
            async_writer.check()
            if drain_pseq_send_results():
                had_activity = True

            event = server.recv_event(timeout_seconds=stream_recv_timeout_seconds)
            pending_events: list[tuple[str, int, dict[str, Any] | None, bytes | None]] = []
            if event is not None:
                pending_events.append(event)
            pending_events.extend(
                server.drain_events(max_items=max_events_per_tick - len(pending_events))
            )

            for kind, client_id, header, payload in pending_events:
                had_activity = True
                if kind == "disconnect":
                    if get_pseq_client_id() == client_id:
                        set_pseq_client_id(None)
                        print(f"openkinetics_parallel_stream pseq_client_disconnected id={client_id}")
                    continue
                if kind == "error":
                    print(f"openkinetics_parallel_stream client_error id={client_id} detail={header}")
                    continue
                if kind != "event" or header is None:
                    continue

                evt_type = str(header.get("type", "")).strip().upper()
                if evt_type == "PSEQ_REGISTER":
                    set_pseq_client_id(client_id)
                    print(f"openkinetics_parallel_stream pseq_client_registered id={client_id}")
                    continue
                if evt_type == "WORKER_ERROR":
                    print(
                        "openkinetics_parallel_stream worker_error "
                        f"worker={header.get('worker')} message={header.get('message')}"
                    )
                    continue
                if evt_type == "WORKER_DONE":
                    worker_name = str(header.get("worker", "")).strip()
                    if worker_name in workers:
                        workers[worker_name].stream_done_received = True
                    continue
                if evt_type == "RESIDUE_READY":
                    family = str(header.get("family", "")).strip().lower()
                    root = str(header.get("root", "")).strip()
                    seq_id = str(header.get("seq_id", "")).strip()
                    model_key = STREAM_EVENT_MODEL_KEYS.get((family, root))
                    if not model_key:
                        continue
                    if seq_id not in seq_by_id:
                        raise RuntimeError(f"Stream returned unknown seq_id={seq_id}")
                    if payload is None:
                        raise RuntimeError(f"{model_key}:{seq_id} stream event missing payload")
                    arr = decode_stream_array(header, payload)
                    row = seq_by_id[seq_id]
                    validate_stream_array_shape(model_key=model_key, row=row, arr=arr)

                    if seq_id in save_targets[model_key] and not target_done(model_key, seq_id):
                        out_path = artifact_path(sequence_info_root, model_key, seq_id)
                        submitted_paths.add(out_path)
                        async_writer.submit(out_path, arr)
                        completed[model_key].add(seq_id)
                    if model_key == "prot_t5" and seq_id in pseq_targets:
                        t5_ready_for_pseq.add(seq_id)
                        queue_t5_for_pseq(seq_id, arr)
                    continue
                if evt_type == "BS_READY":
                    seq_id = str(header.get("seq_id", "")).strip()
                    if seq_id not in seq_by_id:
                        raise RuntimeError(f"Pseq2Sites returned unknown seq_id={seq_id}")
                    if payload is None:
                        raise RuntimeError(f"pseq2sites:{seq_id} stream event missing payload")
                    arr = decode_stream_array(header, payload).reshape(-1)
                    row = seq_by_id[seq_id]
                    validate_stream_array_shape(model_key="pseq2sites", row=row, arr=arr)
                    if seq_id in pseq_targets and not pseq_done(seq_id):
                        out_path = artifact_path(sequence_info_root, "pseq2sites", seq_id)
                        submitted_paths.add(out_path)
                        async_writer.submit(out_path, arr)
                        completed["pseq2sites"].add(seq_id)
                    sent_to_pseq.add(seq_id)
                    queued_to_pseq.discard(seq_id)
                    continue

            if get_pseq_client_id() is not None:
                sent_this_tick = 0
                for seq_id in sorted(pseq_targets):
                    if pseq_done(seq_id):
                        continue
                    if queue_t5_for_pseq(seq_id):
                        had_activity = True
                        sent_this_tick += 1
                        if sent_this_tick >= pseq_sends_per_tick:
                            break

            if all_targets_done():
                if not pseq_finish_sent and get_pseq_client_id() is not None:
                    try:
                        server.send(
                            get_pseq_client_id(),
                            {"type": "PSEQ_FINISH", "job_id": job_id},
                            b"",
                        )
                    except Exception:
                        pass
                    pseq_finish_sent = True
                if all(state.process is None for state in workers.values()):
                    break

            for name in launch_order:
                if poll_worker(name):
                    had_activity = True
            for name in launch_order:
                if workers[name].process is None and launch_worker(name):
                    had_activity = True

            if all_targets_done() and not pseq_finish_sent and get_pseq_client_id() is not None:
                try:
                    server.send(
                        get_pseq_client_id(),
                        {"type": "PSEQ_FINISH", "job_id": job_id},
                        b"",
                    )
                except Exception:
                    pass
                pseq_finish_sent = True

            now = time.monotonic()
            if now - last_progress_at >= 10.0:
                last_progress_at = now
                done_counts = {
                    model_key: len(save_targets[model_key]) - len(remaining_targets(model_key))
                    for model_key in ("prot_t5", "esm2", "esmc")
                }
                pseq_done_count = len([seq_id for seq_id in pseq_targets if pseq_done(seq_id)])
                print(
                    "openkinetics_parallel_stream_progress "
                    f"prot_t5={done_counts['prot_t5']}/{len(save_targets['prot_t5'])} "
                    f"esm2={done_counts['esm2']}/{len(save_targets['esm2'])} "
                    f"esmc={done_counts['esmc']}/{len(save_targets['esmc'])} "
                    f"pseq2sites={pseq_done_count}/{len(pseq_targets)} "
                    f"pseq_sent={len(sent_to_pseq)} "
                    f"pseq_queued={len(queued_to_pseq)} "
                    f"queue_depth={pseq_send_queue.qsize()} "
                    f"elapsed_s={now - started_at:.3f}"
                )

            if not had_activity:
                time.sleep(0.05)
    finally:
        total_elapsed = max(0.0, time.monotonic() - started_at)
        print(f"openkinetics_parallel_stream_total elapsed_s={total_elapsed:.3f}")
        pseq_sender_stop.set()
        try:
            pseq_send_queue.put_nowait(None)
        except queue.Full:
            pass
        if pseq_sender_thread.is_alive():
            pseq_sender_thread.join(timeout=1.0)
        for state in workers.values():
            terminate_worker(state)
            cleanup_worker_inputs(state)
        async_writer.shutdown()
        server.close()

    print("openkinetics_parallel_stream: completed streamed generation.")


def score_text_to_values(score_text: str) -> list[float]:
    return [float(part) for part in score_text.split(",") if part.strip()]


def save_float32_vector_npy_atomic(path: Path, values: list[float]) -> None:
    header = {
        "descr": "<f4",
        "fortran_order": False,
        "shape": (len(values),),
    }
    header_text = repr(header)
    header_len = len(header_text) + 1
    padding = (16 - ((10 + header_len) % 16)) % 16
    header_bytes = (header_text + (" " * padding) + "\n").encode("latin1")
    data = struct.pack("<%sf" % len(values), *values) if values else b""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp.npy")
    try:
        with tmp_path.open("wb") as handle:
            handle.write(b"\x93NUMPY")
            handle.write(bytes([1, 0]))
            handle.write(struct.pack("<H", len(header_bytes)))
            handle.write(header_bytes)
            handle.write(data)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def read_npy_shape(path: Path) -> tuple[int, ...]:
    with path.open("rb") as handle:
        if handle.read(6) != b"\x93NUMPY":
            raise ValueError("not a .npy file")
        major, _minor = handle.read(2)
        if major == 1:
            header_length = struct.unpack("<H", handle.read(2))[0]
        elif major in (2, 3):
            header_length = struct.unpack("<I", handle.read(4))[0]
        else:
            raise ValueError(f"unsupported .npy version: {major}")
        header = ast.literal_eval(handle.read(header_length).decode("latin1").strip())
    return tuple(int(value) for value in header.get("shape") or ())


def convert_pseq2sites_scores(
    *,
    sequences: list[DemoSequence],
    media_path: Path,
    sequence_info_root: Path,
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
        out_path = artifact_path(sequence_info_root, "pseq2sites", row.sequence_id)
        if out_path.exists() and not force:
            skipped += 1
            continue
        values = score_text_to_values(rows[row.sequence_id])
        expected_length = sequence_artifact_input_length(row.sequence)
        if len(values) != expected_length:
            raise SystemExit(
                f"Pseq2Sites score length mismatch for {row.sequence_id}: "
                f"scores={len(values)} artifact_input_sequence={expected_length} "
                f"original_sequence={row.length}"
            )
        print(f"pseq2sites: {'would write' if dry_run else 'writing'} {out_path}")
        if not dry_run:
            save_float32_vector_npy_atomic(out_path, values)
        wrote += 1
    print(f"pseq2sites: score arrays wrote={wrote} skipped={skipped}")


def validate_artifacts(
    *,
    sequences: list[DemoSequence],
    sequence_info_root: Path,
    models: list[str],
) -> None:
    errors: list[str] = []
    for model_key in models:
        for row in sequences:
            path = artifact_path(sequence_info_root, model_key, row.sequence_id)
            if not path.exists():
                errors.append(f"{model_key}:{row.sequence_id} missing {path}")
                continue
            try:
                shape = read_npy_shape(path)
            except Exception as exc:
                errors.append(f"{model_key}:{row.sequence_id} unreadable {exc}")
                continue
            if model_key == "pseq2sites":
                expected_length = sequence_artifact_input_length(row.sequence)
                if shape != (expected_length,):
                    errors.append(
                        f"{model_key}:{row.sequence_id} shape={shape} expected=({expected_length},)"
                    )
            else:
                expected_length = sequence_artifact_input_length(row.sequence)
                if len(shape) != 2 or int(shape[0]) != expected_length:
                    errors.append(
                        f"{model_key}:{row.sequence_id} shape={shape} expected first dim {expected_length}"
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
    sequence_info_root: Path,
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
        str(sequence_info_root),
    ]
    run_command(cmd, env=dict(os.environ), cwd=OPENKINETICS_REPO_ROOT, dry_run=dry_run)


def auth_headers(token: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def http_json(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    body: bytes | None = None
    headers = auth_headers(token)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url=url, method=method.upper(), data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object from {url}, got {type(data).__name__}")
    return data


def fetch_job_log_tail(base_url: str, job_id: str, *, token: str, tail: int, timeout: float) -> str:
    try:
        payload = http_json(
            "GET",
            f"{base_url}/embed/jobs/{urllib.parse.quote(job_id)}/logs?tail={tail}",
            token=token,
            timeout=timeout,
        )
    except Exception as exc:
        return f"(could not fetch GPU job logs: {exc})"
    return str(payload.get("log_tail") or "")


def submit_gpu_service_job(
    *,
    base_url: str,
    token: str,
    step_key: str,
    sequence_ids: list[str],
    sequences: list[DemoSequence],
    timeout: float,
    dry_run: bool,
) -> str | None:
    selected_ids = set(sequence_ids)
    seq_id_to_seq = {
        row.sequence_id: sequence_artifact_input_sequence(row.sequence)
        for row in sequences
        if row.sequence_id in selected_ids
    }
    truncated_count = sum(
        1
        for row in sequences
        if row.sequence_id in selected_ids
        and sequence_artifact_input_length(row.sequence) != row.length
    )
    payload = {
        "method_key": "OpenKinetics-Data",
        "target": "demo_sequence_artifacts",
        "profile": "release_residue_matrices",
        "step_work": {step_key: sequence_ids},
        "seq_id_to_seq": seq_id_to_seq,
        "sequence_artifact_generation": {
            row.sequence_id: sequence_artifact_generation_summary(row.sequence)
            for row in sequences
            if row.sequence_id in selected_ids
        },
    }
    print(
        "gpu_service_submit "
        f"url={base_url}/embed/jobs step={step_key} sequences={len(sequence_ids)} "
        f"truncated_artifact_inputs={truncated_count}"
    )
    if dry_run:
        print(json.dumps({**payload, "seq_id_to_seq": f"<{len(seq_id_to_seq)} sequences>"}, indent=2))
        return None
    response = http_json(
        "POST",
        f"{base_url}/embed/jobs",
        token=token,
        payload=payload,
        timeout=timeout,
    )
    job_id = str(response.get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError(f"GPU service did not return job_id: {response}")
    print(f"gpu_job_id={job_id}")
    return job_id


def wait_for_gpu_job(
    *,
    base_url: str,
    token: str,
    job_id: str,
    poll_interval: float,
    timeout_seconds: int,
    http_timeout: float,
    log_interval: int,
    log_tail: int,
) -> dict[str, Any]:
    started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    next_log_at = started_at + log_interval
    last_status = ""
    while True:
        status = http_json(
            "GET",
            f"{base_url}/embed/jobs/{urllib.parse.quote(job_id)}",
            token=token,
            timeout=http_timeout,
        )
        state = str(status.get("status") or "").strip().lower()
        if state != last_status:
            print(f"gpu_job_status={state or 'unknown'}")
            last_status = state
        if state in {"done", "completed"}:
            return status
        if state in {"failed", "error"}:
            logs = fetch_job_log_tail(
                base_url,
                job_id,
                token=token,
                tail=log_tail,
                timeout=http_timeout,
            )
            raise RuntimeError(f"GPU job failed: {status}\n--- GPU log tail ---\n{logs}")

        now = time.monotonic()
        if now >= deadline:
            logs = fetch_job_log_tail(
                base_url,
                job_id,
                token=token,
                tail=log_tail,
                timeout=http_timeout,
            )
            raise RuntimeError(
                f"Timed out waiting for GPU job {job_id} after {timeout_seconds}s.\n"
                f"--- GPU log tail ---\n{logs}"
            )
        if now >= next_log_at:
            logs = fetch_job_log_tail(
                base_url,
                job_id,
                token=token,
                tail=log_tail,
                timeout=http_timeout,
            )
            if logs:
                print("--- GPU log tail ---")
                print(logs)
            next_log_at = now + log_interval
        time.sleep(poll_interval)


def check_gpu_health(base_url: str, *, token: str, timeout: float, dry_run: bool) -> None:
    print(f"gpu_service_health url={base_url}/health")
    if dry_run:
        return
    health = http_json("GET", f"{base_url}/health", token=token, timeout=timeout)
    if not health.get("online", True):
        raise RuntimeError(f"GPU service is offline: {health}")
    print(
        "gpu_service_online "
        f"gpu={health.get('gpu_name') or 'unknown'} "
        f"active_jobs={health.get('active_jobs')} queued_jobs={health.get('queued_jobs')}"
    )


def gpu_step_command_export(step_key: str, worker_script: Path) -> str:
    env_key = f"GPU_EMBED_STEP_CMD_{step_key.upper()}"
    command = (
        f"/usr/bin/python3 {worker_script} --worker-mode "
        "--seq-id-to-seq-file {seq_id_to_seq_file}"
    )
    return f'export {env_key}="{command}"'


def selected_models(args: argparse.Namespace) -> list[str]:
    requested = set(args.models)
    return [model for model in MODEL_ORDER if model in requested]


def run_worker_mode(args: argparse.Namespace) -> int:
    if args.seq_id_to_seq_file:
        sequences = load_sequences_from_worker_file(repo_path(args.seq_id_to_seq_file))
    else:
        webkinpred_root = repo_path(args.webkinpred_root)
        sequence_info_root = repo_path(args.sequence_info_root)
        seqmap_db = repo_path(args.seqmap_db) if args.seqmap_db else (
            sequence_info_root / "seqmap.sqlite3"
        ).resolve()
        releases_dir = repo_path(args.releases_dir)
        if args.source == "sample":
            raw_rows, _source_count = load_sequences_from_sample(repo_path(args.sample_path))
        else:
            raw_rows, _source_count = load_sequences_from_release(releases_dir / args.release_id)
        sequences = resolve_demo_sequences(
            raw_rows,
            seqmap_db=seqmap_db,
            webkinpred_root=webkinpred_root,
            allow_id_mismatch=args.allow_id_mismatch,
            dry_run=args.dry_run,
        )

    if not sequences:
        raise SystemExit("No protein sequences found for worker mode.")

    webkinpred_root = repo_path(args.webkinpred_root)
    media_path = repo_path(args.media_path) if args.media_path else (webkinpred_root / "media").resolve()
    tools_path = repo_path(args.tools_path) if args.tools_path else (webkinpred_root / "tools").resolve()
    sequence_info_root = media_path / "sequence_info"
    env = build_kinform_env(webkinpred_root, media_path, tools_path)
    models = selected_models(args)
    batch_sizes = {
        "prot_t5": args.prot_t5_batch_size or env_int(env, BATCH_SIZE_ENVS["prot_t5"], 2),
        "esm2": args.esm2_batch_size or env_int(env, BATCH_SIZE_ENVS["esm2"], 2),
        "esmc": args.esmc_batch_size or env_int(env, BATCH_SIZE_ENVS["esmc"], 2),
        "pseq2sites": args.pseq2sites_batch_size or env_int(env, BATCH_SIZE_ENVS["pseq2sites"], 16),
    }

    print(f"worker_mode=1 unique_sequences={len(sequences)} media_path={media_path}")
    print(f"sequence_info_root={sequence_info_root}")
    print(f"models={','.join(models)}")
    for model_key in models:
        print(f"{model_key}_artifact_root={sequence_info_root / ARTIFACT_ROOTS[model_key]}")
    if args.validate_only:
        validate_artifacts(sequences=sequences, sequence_info_root=sequence_info_root, models=models)
        return 0

    if not args.sequential_worker:
        run_parallel_stream_worker(
            sequences=sequences,
            models=models,
            env=env,
            webkinpred_root=webkinpred_root,
            media_path=media_path,
            sequence_info_root=sequence_info_root,
            batch_sizes=batch_sizes,
            force=args.force,
            dry_run=args.dry_run,
        )
        if not args.skip_validation and not args.dry_run:
            validate_artifacts(
                sequences=sequences,
                sequence_info_root=sequence_info_root,
                models=models,
            )
        return 0

    for model_key in models:
        if model_key == "pseq2sites":
            continue
        sequence_ids = missing_artifact_ids(
            sequences,
            sequence_info_root=sequence_info_root,
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

    if "pseq2sites" in models:
        binding_sites_path = media_path / "pseq2sites" / "binding_sites_all.tsv"
        existing_rows = read_binding_site_rows(binding_sites_path)
        missing_tsv_ids = pseq2sites_tsv_ids_needing_scores(
            sequences,
            existing_rows,
            force=args.force,
        )
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
                sequence_info_root=sequence_info_root,
                force=args.force,
                dry_run=args.dry_run,
            )
        else:
            print("pseq2sites: dry run skipped TSV-to-npy conversion.")

    if not args.skip_validation and not args.dry_run:
        validate_artifacts(sequences=sequences, sequence_info_root=sequence_info_root, models=models)
    return 0


def run_production_mode(args: argparse.Namespace) -> int:
    webkinpred_root = repo_path(args.webkinpred_root)
    sequence_info_root = repo_path(args.sequence_info_root)
    releases_dir = repo_path(args.releases_dir)
    seqmap_db = repo_path(args.seqmap_db) if args.seqmap_db else (
        sequence_info_root / "seqmap.sqlite3"
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
        dry_run=args.dry_run or args.validate_only,
    )
    if not sequences:
        raise SystemExit("No protein sequences found.")

    models = selected_models(args)
    print(f"source={args.source} source_rows={source_count} raw_sequence_rows={len(raw_rows)}")
    print(f"unique_sequences={len(sequences)} seqmap_db={seqmap_db}")
    print(f"sequence_info_root={sequence_info_root}")
    print(f"models={','.join(models)}")

    if args.validate_only:
        validate_artifacts(sequences=sequences, sequence_info_root=sequence_info_root, models=models)
        return 0

    missing_ids = ids_missing_any_artifact(
        sequences,
        sequence_info_root=sequence_info_root,
        models=models,
        force=args.force,
    )
    print(f"sequences_missing_any_selected_artifact={len(missing_ids)}")

    if missing_ids:
        base_url = str(args.gpu_service_url).strip().rstrip("/")
        token = str(args.gpu_service_token).strip()
        if not base_url and not args.dry_run:
            raise SystemExit("GPU_EMBED_SERVICE_URL is required.")
        if not token and not args.dry_run:
            raise SystemExit("GPU_EMBED_SERVICE_TOKEN is required.")
        if base_url:
            check_gpu_health(
                base_url,
                token=token,
                timeout=args.http_timeout,
                dry_run=args.dry_run,
            )
        job_id = submit_gpu_service_job(
            base_url=base_url or "<GPU_EMBED_SERVICE_URL>",
            token=token,
            step_key=args.gpu_step_key,
            sequence_ids=missing_ids,
            sequences=sequences,
            timeout=args.http_timeout,
            dry_run=args.dry_run,
        )
        if job_id and not args.submit_only:
            wait_for_gpu_job(
                base_url=base_url,
                token=token,
                job_id=job_id,
                poll_interval=args.poll_interval,
                timeout_seconds=args.gpu_job_timeout,
                http_timeout=args.http_timeout,
                log_interval=args.log_interval,
                log_tail=args.log_tail,
            )
        elif job_id:
            print(f"submitted_only gpu_job_id={job_id}")
            return 0
    else:
        print("All selected sequence artifacts already exist; skipping GPU service submission.")

    if not args.skip_validation and not args.dry_run:
        validate_artifacts(sequences=sequences, sequence_info_root=sequence_info_root, models=models)

    if not args.skip_release_bundles:
        build_release_bundles(
            release_id=args.release_id,
            releases_dir=releases_dir,
            sequence_info_root=sequence_info_root,
            dry_run=args.dry_run,
        )
    return 0


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
    parser.add_argument("--sequence-info-root", default=default_sequence_info_root())
    parser.add_argument("--webkinpred-root", default=str(DEFAULT_WEBKINPRED_ROOT))
    parser.add_argument(
        "--media-path",
        default=os.environ.get("KINFORM_MEDIA_PATH", ""),
        help="GPU worker KinForm media root. Defaults to {webkinpred-root}/media.",
    )
    parser.add_argument(
        "--tools-path",
        default="",
        help="GPU worker webKinPred tools root. Defaults to {webkinpred-root}/tools.",
    )
    parser.add_argument(
        "--seqmap-db",
        default=os.environ.get("SEQMAP_DB", ""),
        help="Predictor seqmap.sqlite3 path. Defaults to {sequence-info-root}/seqmap.sqlite3.",
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
    parser.add_argument("--dry-run", action="store_true", help="Print work without executing it.")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing artifacts.")
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--skip-release-bundles", action="store_true")
    parser.add_argument("--worker-mode", action="store_true")
    parser.add_argument(
        "--sequential-worker",
        action="store_true",
        help="Use the legacy sequential GPU worker instead of the parallel stream worker.",
    )
    parser.add_argument(
        "--seq-id-to-seq-file",
        default="",
        help="GPU worker JSON mapping created by gpu_embed_service.",
    )
    parser.add_argument("--gpu-service-url", default=os.environ.get("GPU_EMBED_SERVICE_URL", ""))
    parser.add_argument("--gpu-service-token", default=os.environ.get("GPU_EMBED_SERVICE_TOKEN", ""))
    parser.add_argument("--gpu-step-key", default=os.environ.get("OPENKINETICS_GPU_STEP_KEY", DEFAULT_GPU_STEP_KEY))
    parser.add_argument("--gpu-worker-script", default=str(DEFAULT_GPU_WORKER_SCRIPT))
    parser.add_argument("--print-gpu-step-command", action="store_true")
    parser.add_argument("--gpu-job-timeout", type=positive_int, default=21600)
    parser.add_argument("--http-timeout", type=float, default=5.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--log-interval", type=positive_int, default=120)
    parser.add_argument("--log-tail", type=positive_int, default=200)
    parser.add_argument("--submit-only", action="store_true")
    parser.add_argument("--prot-t5-batch-size", type=positive_int, default=None)
    parser.add_argument("--esm2-batch-size", type=positive_int, default=None)
    parser.add_argument("--esmc-batch-size", type=positive_int, default=None)
    parser.add_argument("--pseq2sites-batch-size", type=positive_int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.print_gpu_step_command:
        print(gpu_step_command_export(args.gpu_step_key, repo_path(args.gpu_worker_script)))
        return 0
    if args.worker_mode:
        return run_worker_mode(args)
    return run_production_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
