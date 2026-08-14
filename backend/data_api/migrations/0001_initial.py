# Generated for the OpenKinetics Data demo scaffold.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Release",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("release_id", models.SlugField(max_length=80, unique=True)),
                ("title", models.CharField(max_length=240)),
                ("generated_at", models.DateTimeField(blank=True, null=True)),
                ("record_count", models.PositiveIntegerField(default=0)),
                ("manifest", models.JSONField(blank=True, default=dict)),
                ("schema", models.JSONField(blank=True, default=dict)),
                ("attribution", models.JSONField(blank=True, default=dict)),
                ("source_sha256", models.CharField(blank=True, max_length=64)),
                ("is_latest", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-generated_at", "-created_at"]},
        ),
        migrations.CreateModel(
            name="Sequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence_id", models.CharField(max_length=80, unique=True)),
                ("primary_uniprot_id", models.CharField(db_index=True, max_length=40)),
                ("sequence", models.TextField()),
                ("length", models.PositiveIntegerField()),
                ("fasta_header", models.TextField(blank=True)),
                ("source", models.CharField(blank=True, max_length=120)),
                ("source_url", models.URLField(blank=True, max_length=500)),
                ("sequence_variant_status", models.CharField(blank=True, db_index=True, max_length=120)),
                ("mutation_signature", models.CharField(blank=True, max_length=240)),
                ("wild_type", models.BooleanField(blank=True, db_index=True, null=True)),
            ],
            options={"ordering": ["primary_uniprot_id", "sequence_id"]},
        ),
        migrations.CreateModel(
            name="Substrate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("substrate_id", models.CharField(max_length=80, unique=True)),
                ("name", models.CharField(db_index=True, max_length=240)),
                ("pubchem_query", models.CharField(blank=True, max_length=240)),
                ("pubchem_cid", models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                ("smiles", models.TextField(blank=True)),
                ("canonical_smiles", models.TextField(blank=True)),
                ("isomeric_smiles", models.TextField(blank=True)),
                ("inchi_key", models.CharField(blank=True, db_index=True, max_length=80)),
                ("iupac_name", models.TextField(blank=True)),
                ("molecular_formula", models.CharField(blank=True, max_length=120)),
                ("source", models.CharField(blank=True, max_length=120)),
                ("source_url", models.URLField(blank=True, max_length=500)),
            ],
            options={"ordering": ["name", "substrate_id"]},
        ),
        migrations.CreateModel(
            name="Measurement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("record_key", models.CharField(max_length=80)),
                ("measurement_key", models.CharField(db_index=True, max_length=80)),
                ("measurement_id", models.CharField(db_index=True, max_length=80)),
                ("review_key", models.CharField(blank=True, max_length=80)),
                ("enzyme_name", models.CharField(db_index=True, max_length=240)),
                ("ec_number", models.CharField(blank=True, db_index=True, max_length=40)),
                ("ec_class", models.CharField(blank=True, db_index=True, max_length=10)),
                ("organism", models.CharField(blank=True, db_index=True, max_length=240)),
                ("primary_uniprot_id", models.CharField(blank=True, db_index=True, max_length=40)),
                ("identity_resolution_state", models.CharField(blank=True, max_length=120)),
                ("uniprot_candidate_ids", models.JSONField(blank=True, default=list)),
                ("pair_id", models.CharField(db_index=True, max_length=80)),
                ("kcat", models.FloatField(blank=True, null=True)),
                ("kcat_unit", models.CharField(blank=True, max_length=80)),
                ("km", models.FloatField(blank=True, null=True)),
                ("km_unit", models.CharField(blank=True, max_length=80)),
                ("ki", models.FloatField(blank=True, null=True)),
                ("ki_unit", models.CharField(blank=True, max_length=80)),
                ("kcat_over_km", models.FloatField(blank=True, null=True)),
                ("kcat_over_km_unit", models.CharField(blank=True, max_length=80)),
                ("ph", models.FloatField(blank=True, null=True)),
                ("temperature_c", models.FloatField(blank=True, null=True)),
                ("temperature_k", models.FloatField(blank=True, null=True)),
                ("temperature_display", models.CharField(blank=True, max_length=80)),
                ("source_db", models.CharField(blank=True, db_index=True, max_length=80)),
                ("source_record_count", models.PositiveIntegerField(default=0)),
                ("has_literature_id", models.BooleanField(default=False)),
                ("pmid_count", models.PositiveIntegerField(default=0)),
                ("doi_count", models.PositiveIntegerField(default=0)),
                ("literature_id_count", models.PositiveIntegerField(default=0)),
                ("literature_linkage", models.CharField(blank=True, max_length=120)),
                ("verification_status", models.CharField(blank=True, db_index=True, max_length=120)),
                ("evidence_confidence_tier", models.CharField(blank=True, db_index=True, max_length=120)),
                ("paper_grounding_status", models.CharField(blank=True, db_index=True, max_length=120)),
                ("has_proof_excerpt", models.BooleanField(default=False)),
                ("compact_evidence_summary", models.TextField(blank=True)),
                ("raw", models.JSONField(blank=True, default=dict)),
                ("search_text", models.TextField(blank=True, db_index=True)),
                (
                    "release",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="measurements", to="data_api.release"),
                ),
                (
                    "sequence",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="measurements", to="data_api.sequence"),
                ),
                (
                    "substrate",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="measurements", to="data_api.substrate"),
                ),
            ],
            options={
                "ordering": ["enzyme_name", "substrate__name", "record_key"],
                "indexes": [
                    models.Index(fields=["release", "ec_class"], name="data_api_me_release_d4651e_idx"),
                    models.Index(fields=["release", "source_db"], name="data_api_me_release_6ecff2_idx"),
                    models.Index(fields=["release", "verification_status"], name="data_api_me_release_28965b_idx"),
                    models.Index(fields=["release", "primary_uniprot_id"], name="data_api_me_release_a2b2d5_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ReleaseArtifact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("artifact_key", models.CharField(max_length=120)),
                ("family", models.CharField(db_index=True, max_length=80)),
                ("label", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("relative_path", models.CharField(max_length=400)),
                ("url", models.CharField(blank=True, max_length=500)),
                ("content_type", models.CharField(blank=True, max_length=120)),
                ("size_bytes", models.BigIntegerField(blank=True, null=True)),
                ("sha256", models.CharField(blank=True, max_length=64)),
                ("available", models.BooleanField(db_index=True, default=False)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "release",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="artifacts", to="data_api.release"),
                ),
            ],
            options={"ordering": ["family", "label"]},
        ),
        migrations.CreateModel(
            name="SplitAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("split_family", models.CharField(db_index=True, max_length=80)),
                ("split", models.CharField(db_index=True, max_length=20)),
                (
                    "measurement",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="split_assignments", to="data_api.measurement"),
                ),
                (
                    "release",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="split_assignments", to="data_api.release"),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="measurement",
            constraint=models.UniqueConstraint(fields=("release", "record_key"), name="unique_measurement_record_per_release"),
        ),
        migrations.AddConstraint(
            model_name="releaseartifact",
            constraint=models.UniqueConstraint(fields=("release", "artifact_key"), name="unique_artifact_key_per_release"),
        ),
        migrations.AddConstraint(
            model_name="splitassignment",
            constraint=models.UniqueConstraint(fields=("measurement", "split_family"), name="unique_split_family_per_measurement"),
        ),
    ]

