from django.db import models


class Release(models.Model):
    release_id = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=240)
    generated_at = models.DateTimeField(null=True, blank=True)
    record_count = models.PositiveIntegerField(default=0)
    manifest = models.JSONField(default=dict, blank=True)
    schema = models.JSONField(default=dict, blank=True)
    attribution = models.JSONField(default=dict, blank=True)
    source_sha256 = models.CharField(max_length=64, blank=True)
    is_latest = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-generated_at", "-created_at"]

    def __str__(self):
        return self.release_id


class Sequence(models.Model):
    sequence_id = models.CharField(max_length=80, unique=True)
    cache_sequence_id = models.CharField(max_length=80, blank=True, db_index=True)
    primary_uniprot_id = models.CharField(max_length=40, db_index=True)
    sequence = models.TextField()
    length = models.PositiveIntegerField()
    fasta_header = models.TextField(blank=True)
    source = models.CharField(max_length=120, blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    sequence_variant_status = models.CharField(max_length=120, blank=True, db_index=True)
    mutation_signature = models.CharField(max_length=240, blank=True)
    wild_type = models.BooleanField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["primary_uniprot_id", "sequence_id"]

    def __str__(self):
        return self.sequence_id


class Substrate(models.Model):
    substrate_id = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=240, db_index=True)
    pubchem_query = models.CharField(max_length=240, blank=True)
    pubchem_cid = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    smiles = models.TextField(blank=True)
    canonical_smiles = models.TextField(blank=True)
    isomeric_smiles = models.TextField(blank=True)
    inchi_key = models.CharField(max_length=80, blank=True, db_index=True)
    iupac_name = models.TextField(blank=True)
    molecular_formula = models.CharField(max_length=120, blank=True)
    source = models.CharField(max_length=120, blank=True)
    source_url = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["name", "substrate_id"]

    def __str__(self):
        return self.name


class Measurement(models.Model):
    release = models.ForeignKey(Release, related_name="measurements", on_delete=models.CASCADE)
    record_key = models.CharField(max_length=80)
    measurement_key = models.CharField(max_length=80, db_index=True)
    measurement_id = models.CharField(max_length=80, db_index=True)
    review_key = models.CharField(max_length=80, blank=True)

    enzyme_name = models.CharField(max_length=240, db_index=True)
    ec_number = models.CharField(max_length=40, blank=True, db_index=True)
    ec_class = models.CharField(max_length=10, blank=True, db_index=True)
    organism = models.CharField(max_length=240, blank=True, db_index=True)
    primary_uniprot_id = models.CharField(max_length=40, blank=True, db_index=True)
    identity_resolution_state = models.CharField(max_length=120, blank=True)
    uniprot_candidate_ids = models.JSONField(default=list, blank=True)

    sequence = models.ForeignKey(Sequence, related_name="measurements", on_delete=models.PROTECT)
    substrate = models.ForeignKey(Substrate, related_name="measurements", on_delete=models.PROTECT)
    pair_id = models.CharField(max_length=80, db_index=True)

    kcat = models.FloatField(null=True, blank=True)
    kcat_unit = models.CharField(max_length=80, blank=True)
    km = models.FloatField(null=True, blank=True)
    km_unit = models.CharField(max_length=80, blank=True)
    ki = models.FloatField(null=True, blank=True)
    ki_unit = models.CharField(max_length=80, blank=True)
    kcat_over_km = models.FloatField(null=True, blank=True)
    kcat_over_km_unit = models.CharField(max_length=80, blank=True)

    ph = models.FloatField(null=True, blank=True)
    temperature_c = models.FloatField(null=True, blank=True)
    temperature_k = models.FloatField(null=True, blank=True)
    temperature_display = models.CharField(max_length=80, blank=True)

    source_db = models.CharField(max_length=80, blank=True, db_index=True)
    source_record_count = models.PositiveIntegerField(default=0)
    has_literature_id = models.BooleanField(default=False)
    pmid_count = models.PositiveIntegerField(default=0)
    doi_count = models.PositiveIntegerField(default=0)
    literature_id_count = models.PositiveIntegerField(default=0)
    literature_linkage = models.CharField(max_length=120, blank=True)

    verification_status = models.CharField(max_length=120, blank=True, db_index=True)
    evidence_confidence_tier = models.CharField(max_length=120, blank=True, db_index=True)
    paper_grounding_status = models.CharField(max_length=120, blank=True, db_index=True)
    has_proof_excerpt = models.BooleanField(default=False)
    compact_evidence_summary = models.TextField(blank=True)

    raw = models.JSONField(default=dict, blank=True)
    search_text = models.TextField(blank=True, db_index=True)

    class Meta:
        ordering = ["enzyme_name", "substrate__name", "record_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["release", "record_key"],
                name="unique_measurement_record_per_release",
            )
        ]
        indexes = [
            models.Index(fields=["release", "ec_class"], name="data_api_me_release_d4651e_idx"),
            models.Index(fields=["release", "source_db"], name="data_api_me_release_6ecff2_idx"),
            models.Index(
                fields=["release", "verification_status"],
                name="data_api_me_release_28965b_idx",
            ),
            models.Index(
                fields=["release", "primary_uniprot_id"],
                name="data_api_me_release_a2b2d5_idx",
            ),
        ]

    def __str__(self):
        return "%s / %s" % (self.enzyme_name, self.substrate.name)


class SplitAssignment(models.Model):
    measurement = models.ForeignKey(
        Measurement,
        related_name="split_assignments",
        on_delete=models.CASCADE,
    )
    release = models.ForeignKey(Release, related_name="split_assignments", on_delete=models.CASCADE)
    split_family = models.CharField(max_length=80, db_index=True)
    split = models.CharField(max_length=20, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["measurement", "split_family"],
                name="unique_split_family_per_measurement",
            )
        ]


class ReleaseArtifact(models.Model):
    release = models.ForeignKey(Release, related_name="artifacts", on_delete=models.CASCADE)
    artifact_key = models.CharField(max_length=120)
    family = models.CharField(max_length=80, db_index=True)
    label = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    relative_path = models.CharField(max_length=400)
    url = models.CharField(max_length=500, blank=True)
    content_type = models.CharField(max_length=120, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    available = models.BooleanField(default=False, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["family", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["release", "artifact_key"],
                name="unique_artifact_key_per_release",
            )
        ]

    def __str__(self):
        return "%s:%s" % (self.release.release_id, self.artifact_key)
