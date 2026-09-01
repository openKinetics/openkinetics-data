from django.contrib import admin

from .models import Measurement, Release, ReleaseArtifact, Sequence, SplitAssignment, Substrate


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ("release_id", "title", "record_count", "is_latest", "generated_at")
    search_fields = ("release_id", "title")


@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    list_display = (
        "record_key",
        "enzyme_name",
        "substrate",
        "ec_number",
        "organism",
        "verification_status",
    )
    list_filter = ("release", "source_db", "verification_status", "ec_class")
    search_fields = ("record_key", "enzyme_name", "substrate__name", "primary_uniprot_id")


@admin.register(Sequence)
class SequenceAdmin(admin.ModelAdmin):
    list_display = (
        "sequence_id",
        "primary_uniprot_id",
        "length",
        "sequence_variant_status",
    )
    search_fields = ("sequence_id", "primary_uniprot_id")


@admin.register(Substrate)
class SubstrateAdmin(admin.ModelAdmin):
    list_display = ("substrate_id", "name", "pubchem_cid", "inchi_key")
    search_fields = ("substrate_id", "name", "inchi_key")


@admin.register(SplitAssignment)
class SplitAssignmentAdmin(admin.ModelAdmin):
    list_display = ("measurement", "split_family", "split")
    list_filter = ("release", "split_family", "split")


@admin.register(ReleaseArtifact)
class ReleaseArtifactAdmin(admin.ModelAdmin):
    list_display = ("artifact_key", "release", "family", "available", "relative_path")
    list_filter = ("release", "family", "available")
    search_fields = ("artifact_key", "label", "relative_path")
