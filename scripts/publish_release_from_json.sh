#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/publish_release_from_json.sh /path/to/openkinetics_release.json [options]

Builds release files, indexes existing sequence artifacts, imports the release
into Django as latest, and starts/restarts the website.

Options:
  --public-api-base-url URL   Public API base used in generated embedding commands.
                              Defaults to $OPENKINETICS_PUBLIC_API_BASE_URL.
  --generate-artifacts        Generate missing artifacts through the GPU service before
                              building indexes/bundles. Default is to use existing files.
  --gpu-service-url URL       GPU service URL. Defaults to $GPU_EMBED_SERVICE_URL.
                              Only required with --generate-artifacts.
  --gpu-service-token TOKEN   GPU service token. Defaults to $GPU_EMBED_SERVICE_TOKEN.
                              Only required with --generate-artifacts.
  --sequence-info-root PATH   Host sequence_info root. Defaults to
                              $OPENKINETICS_SEQUENCE_INFO_HOST_DIR or
                              /home/saleh/webKinPred/media/sequence_info.
  --runtime-host-dir PATH      Host runtime dir. Defaults to $OPENKINETICS_RUNTIME_HOST_DIR
                              or ./runtime.
  --releases-host-dir PATH     Host releases dir. Defaults to $OPENKINETICS_RELEASES_HOST_DIR
                              or ./releases.
  --http-timeout SECONDS      HTTP timeout for GPU service calls. Defaults to 120.
  --gpu-job-timeout SECONDS   GPU job wait timeout. Defaults to script default.
  --models "LIST"             Space-separated models, e.g. "prot_t5 esm2 esmc".
  --force                     Regenerate artifacts even if files already exist.
                              Only used with --generate-artifacts.
  --submit-only               Submit GPU job and stop before import/restart.
                              Only valid with --generate-artifacts.
  --skip-build                Do not rebuild Docker images.
  --skip-artifacts            Build/import release metadata without sequence artifact
                              indexes, helper scripts, or bundles.
  --skip-import               Do not import the release into the backend DB.
  --skip-up                   Do not run docker compose up -d at the end.
  --dry-run                   Print generation work without executing GPU jobs.
  -h, --help                  Show this help.

Generated release files are written to the host releases dir through /data/releases.
The input JSON is mounted read-only and is not copied into git-tracked paths.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

dotenv_value() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path

key = sys.argv[1]
path = Path(".env")
if not path.exists():
    raise SystemExit(0)
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = line.split("=", 1)
    if name.strip() != key:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    print(value)
    break
PY
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

json_path=""
gpu_service_url="${GPU_EMBED_SERVICE_URL:-}"
gpu_service_token="${GPU_EMBED_SERVICE_TOKEN:-}"
public_api_base_url="${OPENKINETICS_PUBLIC_API_BASE_URL:-}"
sequence_info_root="${OPENKINETICS_SEQUENCE_INFO_HOST_DIR:-${OPENKINETICS_SEQUENCE_INFO_ROOT_HOST:-/home/saleh/webKinPred/media/sequence_info}}"
runtime_host_dir="${OPENKINETICS_RUNTIME_HOST_DIR:-./runtime}"
releases_host_dir="${OPENKINETICS_RELEASES_HOST_DIR:-./releases}"
sequence_info_root_cli=0
runtime_host_dir_cli=0
releases_host_dir_cli=0
http_timeout="120"
gpu_job_timeout=""
models=()
force=0
generate_artifacts=0
submit_only=0
skip_build=0
skip_artifacts=0
skip_import=0
skip_up=0
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --gpu-service-url)
      [[ $# -ge 2 ]] || die "--gpu-service-url requires a value"
      gpu_service_url="$2"
      shift 2
      ;;
    --public-api-base-url)
      [[ $# -ge 2 ]] || die "--public-api-base-url requires a value"
      public_api_base_url="$2"
      shift 2
      ;;
    --gpu-service-token)
      [[ $# -ge 2 ]] || die "--gpu-service-token requires a value"
      gpu_service_token="$2"
      shift 2
      ;;
    --sequence-info-root)
      [[ $# -ge 2 ]] || die "--sequence-info-root requires a value"
      sequence_info_root="$2"
      sequence_info_root_cli=1
      shift 2
      ;;
    --runtime-host-dir)
      [[ $# -ge 2 ]] || die "--runtime-host-dir requires a value"
      runtime_host_dir="$2"
      runtime_host_dir_cli=1
      shift 2
      ;;
    --releases-host-dir)
      [[ $# -ge 2 ]] || die "--releases-host-dir requires a value"
      releases_host_dir="$2"
      releases_host_dir_cli=1
      shift 2
      ;;
    --http-timeout)
      [[ $# -ge 2 ]] || die "--http-timeout requires a value"
      http_timeout="$2"
      shift 2
      ;;
    --gpu-job-timeout)
      [[ $# -ge 2 ]] || die "--gpu-job-timeout requires a value"
      gpu_job_timeout="$2"
      shift 2
      ;;
    --models)
      [[ $# -ge 2 ]] || die "--models requires a quoted space-separated value"
      read -r -a models <<< "$2"
      shift 2
      ;;
    --force)
      force=1
      shift
      ;;
    --generate-artifacts)
      generate_artifacts=1
      shift
      ;;
    --submit-only)
      submit_only=1
      shift
      ;;
    --skip-build)
      skip_build=1
      shift
      ;;
    --skip-artifacts)
      skip_artifacts=1
      shift
      ;;
    --skip-import)
      skip_import=1
      shift
      ;;
    --skip-up)
      skip_up=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --*)
      die "unknown option: $1"
      ;;
    *)
      if [[ -n "$json_path" ]]; then
        die "only one JSON path may be provided"
      fi
      json_path="$1"
      shift
      ;;
  esac
done

[[ -n "$json_path" ]] || die "missing release JSON path"
[[ -f .env ]] || die ".env not found; copy .env.example to .env and set production values first"

if [[ -z "$gpu_service_url" ]]; then
  gpu_service_url="$(dotenv_value GPU_EMBED_SERVICE_URL)"
fi
if [[ -z "$gpu_service_token" ]]; then
  gpu_service_token="$(dotenv_value GPU_EMBED_SERVICE_TOKEN)"
fi
if [[ -z "$public_api_base_url" ]]; then
  public_api_base_url="$(dotenv_value OPENKINETICS_PUBLIC_API_BASE_URL)"
fi
if [[ "$runtime_host_dir_cli" -eq 0 && -z "${OPENKINETICS_RUNTIME_HOST_DIR:-}" ]]; then
  runtime_from_env_file="$(dotenv_value OPENKINETICS_RUNTIME_HOST_DIR)"
  if [[ -n "$runtime_from_env_file" ]]; then
    runtime_host_dir="$runtime_from_env_file"
  fi
fi
if [[ "$releases_host_dir_cli" -eq 0 && -z "${OPENKINETICS_RELEASES_HOST_DIR:-}" ]]; then
  releases_from_env_file="$(dotenv_value OPENKINETICS_RELEASES_HOST_DIR)"
  if [[ -n "$releases_from_env_file" ]]; then
    releases_host_dir="$releases_from_env_file"
  fi
fi
if [[ "$sequence_info_root_cli" -eq 0 && -z "${OPENKINETICS_SEQUENCE_INFO_HOST_DIR:-}" && -z "${OPENKINETICS_SEQUENCE_INFO_ROOT_HOST:-}" ]]; then
  sequence_info_from_env_file="$(dotenv_value OPENKINETICS_SEQUENCE_INFO_HOST_DIR)"
  if [[ -n "$sequence_info_from_env_file" ]]; then
    sequence_info_root="$sequence_info_from_env_file"
  fi
fi

json_abs="$(python3 - "$json_path" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
[[ -f "$json_abs" ]] || die "release JSON not found: $json_abs"

sequence_info_abs="$(python3 - "$sequence_info_root" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
[[ -d "$sequence_info_abs" ]] || die "sequence_info root not found: $sequence_info_abs"
if [[ "$generate_artifacts" -eq 1 ]]; then
  [[ -f "$sequence_info_abs/seqmap.sqlite3" ]] || die "seqmap DB not found: $sequence_info_abs/seqmap.sqlite3"
fi
if [[ "$submit_only" -eq 1 && "$generate_artifacts" -eq 0 ]]; then
  die "--submit-only requires --generate-artifacts"
fi
if [[ "$skip_artifacts" -eq 0 && -z "$public_api_base_url" ]]; then
  die "OPENKINETICS_PUBLIC_API_BASE_URL is required for generated embedding commands; set it in .env or pass --public-api-base-url"
fi

runtime_host_abs="$(python3 - "$runtime_host_dir" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
releases_host_abs="$(python3 - "$releases_host_dir" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

release_id="$(python3 - "$json_abs" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
release_id = str((payload.get("manifest") or {}).get("release_id") or "").strip()
if not release_id:
    raise SystemExit("release JSON manifest.release_id is required")
print(release_id)
PY
)"

json_dir="$(dirname "$json_abs")"
json_file="$(basename "$json_abs")"
container_json="/release_input/$json_file"

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
else
  compose=(sudo docker compose)
fi

run_compose() {
  echo "+ ${compose[*]} $*"
  "${compose[@]}" "$@"
}

mkdir -p "$runtime_host_abs" "$releases_host_abs"
export OPENKINETICS_RUNTIME_HOST_DIR="$runtime_host_abs"
export OPENKINETICS_RELEASES_HOST_DIR="$releases_host_abs"
export OPENKINETICS_SEQUENCE_INFO_HOST_DIR="$sequence_info_abs"
export OPENKINETICS_PUBLIC_API_BASE_URL="$public_api_base_url"

echo "release_id=$release_id"
echo "input_json=$json_abs"
echo "release_output=$releases_host_abs/$release_id"
echo "sequence_info_root=$sequence_info_abs"
echo "public_api_base_url=${public_api_base_url:-not_set}"

if [[ "$skip_build" -eq 0 ]]; then
  run_compose build backend frontend
fi

run_compose run --rm backend python backend/manage.py migrate

run_compose run --rm \
  -v "$json_dir:/release_input:ro" \
  backend \
  python scripts/build_release_files.py \
    --sample "$container_json" \
    --releases-dir /data/releases

if [[ "$skip_artifacts" -eq 0 ]]; then
  if [[ "$generate_artifacts" -eq 1 ]]; then
    [[ -n "$gpu_service_url" || "$dry_run" -eq 1 ]] || die "GPU service URL is required; pass --gpu-service-url or set GPU_EMBED_SERVICE_URL"
    [[ -n "$gpu_service_token" || "$dry_run" -eq 1 ]] || die "GPU service token is required; pass --gpu-service-token or set GPU_EMBED_SERVICE_TOKEN"

    artifact_args=(
      --source release
      --release-id "$release_id"
      --releases-dir /data/releases
      --sequence-info-root /sequence_info
      --seqmap-db /tmp/seqmap.sqlite3
      --gpu-service-url "$gpu_service_url"
      --gpu-service-token "$gpu_service_token"
      --http-timeout "$http_timeout"
    )
    if [[ -n "$gpu_job_timeout" ]]; then
      artifact_args+=(--gpu-job-timeout "$gpu_job_timeout")
    fi
    if [[ "${#models[@]}" -gt 0 ]]; then
      artifact_args+=(--models "${models[@]}")
    fi
    if [[ "$force" -eq 1 ]]; then
      artifact_args+=(--force)
    fi
    if [[ "$submit_only" -eq 1 ]]; then
      artifact_args+=(--submit-only)
    fi
    if [[ "$dry_run" -eq 1 ]]; then
      artifact_args+=(--dry-run)
    fi

    run_compose run --rm \
      -e GPU_EMBED_SERVICE_URL="$gpu_service_url" \
      -e GPU_EMBED_SERVICE_TOKEN="$gpu_service_token" \
      -e OPENKINETICS_PUBLIC_API_BASE_URL="$public_api_base_url" \
      -v "$sequence_info_abs:/sequence_info:ro" \
      backend \
      sh -lc 'cp /sequence_info/seqmap.sqlite3 /tmp/seqmap.sqlite3 && exec python scripts/generate_sequence_artifacts.py "$@"' \
      sh "${artifact_args[@]}"
  else
    run_compose run --rm \
      -e OPENKINETICS_PUBLIC_API_BASE_URL="$public_api_base_url" \
      -v "$sequence_info_abs:/sequence_info:ro" \
      backend \
      python scripts/build_sequence_artifact_bundles.py \
        --release-id "$release_id" \
        --releases-dir /data/releases \
        --sequence-info-root /sequence_info
  fi
fi

if [[ "$submit_only" -eq 1 ]]; then
  echo "Submitted GPU job only. Re-run without --submit-only after artifacts finish to build bundles, import the release, and restart the site."
  exit 0
fi

if [[ "$skip_import" -eq 0 && "$dry_run" -eq 0 ]]; then
  run_compose run --rm \
    -v "$json_dir:/release_input:ro" \
    backend \
    python backend/manage.py import_release \
      --sample "$container_json" \
      --latest
fi

if [[ "$skip_up" -eq 0 && "$dry_run" -eq 0 ]]; then
  run_compose up -d
  run_compose ps
fi

echo "Release publish flow finished for $release_id."
