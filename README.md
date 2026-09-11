# OpenKinetics Data

Data portal for CatLog-derived enzyme kinetics data served by OpenKinetics.

This project backs `data.openkinetics.org`. It is separate from the predictor
application, but is designed to deploy on the same server and match the
predictor site's general visual style.

## Current Sample Data

The current sample artifact is:

```text
data/sample/openkinetics_demo_100.json
```

It contains 100 CatLog-derived datapoints with UniProt sequences and PubChem
substrate structures joined in. The sample is not the full CatLog source
snapshot.

## Attribution

This data resource is built from CatLog, developed by the
[Chowdhury Lab](https://chowdhurylab.github.io/) and collaborators. The full
CatLog publication is coming soon. For now, please cite:

Sajeevan et al., Robust Prediction of Enzyme Variant Kinetics with RealKcat,
bioRxiv 2025, DOI: https://doi.org/10.1101/2025.02.10.637555

CatLog static browser:
https://chowdhurylab.github.io/tools/catlog-static/

## Local Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python backend/manage.py migrate
python scripts/build_release_files.py
python backend/manage.py import_release
python backend/manage.py runserver 8001
```

## Local Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the Django API at `http://localhost:8001` unless
`VITE_API_BASE_URL` is set.

## Docker Deployment

Production is expected to run from:

```text
/home/saleh/openkinetics-data
```

The Docker setup builds two images:

- `backend`: Django + Gunicorn on port `8010` inside the Compose network.
- `frontend`: Vite build served by Nginx on host port `8082`, or the bind
  address set by `OPENKINETICS_FRONTEND_BIND`.

Persistent state lives on the server and is bind-mounted into containers:

- `${OPENKINETICS_RUNTIME_HOST_DIR:-./runtime}:/data/runtime` stores the SQLite database.
- `${OPENKINETICS_RELEASES_HOST_DIR:-./releases}:/data/releases` stores release files and zip downloads.
- `/home/saleh/webKinPred/media/sequence_info:/sequence_info:ro` exposes
  existing predictor sequence artifacts without copying them.

`runtime/` and `releases/` are deployment state. Keep them on the server and
out of git. For production, set `OPENKINETICS_RELEASES_HOST_DIR` to a persistent
server directory such as `/srv/openkinetics-data/releases` if you do not want
release outputs under the repo checkout at all.

Create `.env` from `.env.example`. On production, set
`OPENKINETICS_FRONTEND_BIND=10.1.2.12:8082`, then run:

```bash
mkdir -p runtime releases
docker compose build
docker compose run --rm backend python backend/manage.py migrate
docker compose run --rm backend python scripts/build_release_files.py
docker compose run --rm backend python scripts/build_sequence_artifact_bundles.py
docker compose run --rm backend python backend/manage.py import_release
docker compose up -d
```

For a full release JSON, the preferred production command is:

```bash
scripts/publish_release_from_json.sh /path/to/openkinetics_release.json
```

The script builds release files under `./releases`, generates missing sequence
artifacts through the GPU service, imports the release as latest, and restarts
the website. If `OPENKINETICS_RELEASES_HOST_DIR` is set, the script writes there
instead. Set `GPU_EMBED_SERVICE_URL` and `GPU_EMBED_SERVICE_TOKEN` in the
environment or pass `--gpu-service-url` and `--gpu-service-token`.

The frontend container serves the React app, proxies `/api/`, `/admin/`, and
`/sequence-artifacts/` to Django, and serves `/releases/` from the mounted
release directory.

Sequence artifact files are keyed by `sequence_id`, matching the predictor
`seqmap.sqlite3` ID where possible and otherwise using `sha256(sequence)[:12]`.
Mounted source arrays live at paths such as:

```text
/sequence_info/esm2_layer_33/residue_vecs/{sequence_id}.npy
/sequence_info/esmc_layer_32/residue_vecs/{sequence_id}.npy
/sequence_info/prot_t5_last/residue_vecs/{sequence_id}.npy
/sequence_info/pseq2sites_scores/{sequence_id}.npy
```

Per-record artifact downloads are served as ZIP packages containing
`README.txt`, `manifest.json`, `sequence.json`, and the raw `.npy` array.
Pseq2Sites downloads also include a readable `pseq2sites/scores.json` payload
with `sequence_id`, `sequence`, and per-residue scores when the score vector can
be parsed. Release-level embedding and Pseq2Sites bundles include
`metadata/sequences.jsonl` and `metadata/artifacts.jsonl` so every array is
distributed with its amino-acid sequence.
