# OpenKinetics Data

Data portal for CatLog-derived enzyme kinetics data served by OpenKinetics.

This project backs `data.openkinetics.org`. It is separate from the predictor
application, but is designed to deploy on the same server and match the
predictor site's general visual style.

## Current Demo Data

The current demo sample is:

```text
data/sample/openkinetics_demo_100.json
```

It contains 100 CatLog-derived datapoints with UniProt sequences and PubChem
substrate structures joined in for the demo. The sample is a demo release, not
the full CatLog source snapshot.

## Attribution

This data resource is built from CatLog, developed by the Chowdhury Lab and
collaborators. The full CatLog publication is coming soon. For now, please cite:

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
python backend/manage.py import_demo_release
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

## Production Layout

Recommended server path:

```text
/home/saleh/data-openkinetics/
  backend/
  frontend/
  releases/
  data/
  scripts/
```

Large release files and zip bundles should be served directly by Nginx from the
`releases/` directory. Django stores searchable metadata and returns file URLs,
checksums, and release manifests.

