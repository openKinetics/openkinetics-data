from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="sequence",
            name="cache_sequence_id",
            field=models.CharField(blank=True, db_index=True, max_length=80),
        ),
    ]

