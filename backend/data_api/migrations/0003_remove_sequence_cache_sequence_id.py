from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_api", "0002_sequence_cache_sequence_id"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="sequence",
            name="cache_sequence_id",
        ),
    ]
