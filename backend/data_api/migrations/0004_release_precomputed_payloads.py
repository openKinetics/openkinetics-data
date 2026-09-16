from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_api", "0003_remove_sequence_cache_sequence_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="release",
            name="precomputed_stats",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="release",
            name="precomputed_facets",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="release",
            name="precomputed_download_stats",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="release",
            name="precomputation_version",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="release",
            name="precomputed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
