# Implementation Plan

## Product Scope

`data.openkinetics.org` is a public data portal for CatLog-derived enzyme
kinetics data served by OpenKinetics. It is separate from
`predictor.openkinetics.org`, but should share the same practical scientific
vibe and link back to the predictor.

The site must make CatLog attribution prominent. The full CatLog paper is
coming soon; for now the site cites RealKcat:

https://doi.org/10.1101/2025.02.10.637555

It also links to the [Chowdhury Lab](https://chowdhurylab.github.io/) CatLog browser:

https://chowdhurylab.github.io/tools/catlog-static/

## Stack

- Backend: Django
- Frontend: React + Vite
- Local database: SQLite
- Production database: Postgres
- Release files: server disk under `/home/saleh/data-openkinetics/releases`
- Large downloads: served directly by Nginx
- Public access: no login, no download gate

## Demo Release

The demo starts from:

```text
data/sample/openkinetics_demo_100.json
```

The release builder writes:

```text
releases/openkinetics-catlog-demo-2026-08/
  manifest.json
  measurements.jsonl.gz
  measurements.csv.gz
  record_details.jsonl.gz
  sequences.fasta
  sequences.jsonl.gz
  substrates.jsonl.gz
  splits/
  expected_generated_artifacts.json
  downloads/
  checksums.sha256
```

Generated embedding and binding-site artifacts are expected at:

```text
embeddings/esm2/sequence_embeddings.npz
embeddings/esmc/sequence_embeddings.npz
embeddings/prot_t5/sequence_embeddings.npz
pseq2sites/binding_sites_by_sequence_id.tsv.gz
```

All are keyed by `sequence_id`.

## Backend Milestones

1. Import the demo JSON into normalized Django models.
2. Expose stats, release metadata, measurements, record details, facets, and
   downloads through `/api/*`.
3. Index server files as release artifacts with size, checksum, URL, and
   availability.
4. Keep embeddings and Pseq2Sites out of the database.
5. Switch production to Postgres and Nginx-served release files.

## Frontend Milestones

1. Build search-first home page with stats, filters, and a dense measurement
   table.
2. Build record detail pages with measurement values, sequence, substrate,
   evidence, provenance, and split keys.
3. Build downloads page grouped by bundles, measurements, sequences, substrates,
   splits, embeddings, Pseq2Sites, and metadata.
4. Build release and citation pages.
5. Match predictor's practical React/Bootstrap feel while keeping CatLog
   attribution visibly stronger than a footer-only mention.

## Production Release Workflow

1. Receive CatLog export.
2. Normalize rows into the OpenKinetics schema.
3. Join UniProt sequences and PubChem substrate structures.
4. Generate sequence/substrate/pair IDs.
5. Generate train/val/test split assignments.
6. Generate `esm2`, `esmc`, `prot_t5`, and `pseq2sites` artifacts keyed by
   `sequence_id`.
7. Build release files and zip bundles.
8. Write checksums.
9. Import searchable metadata into Django.
10. Publish immutable release and update `latest`.
