from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("partners", "0002_indices_de_desempenho")]
    operations = [
        migrations.AddField(
            model_name="partner",
            name="fax",
            field=models.CharField("Fax", max_length=20, blank=True),
        )
    ]
