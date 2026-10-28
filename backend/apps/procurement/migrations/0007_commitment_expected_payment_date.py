from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0006_commitment_operation_type_freightsupplement_and_more")
    ]
    operations = [
        migrations.AddField(
            model_name="commitment",
            name="expected_payment_date",
            field=models.DateField("Data prevista de pagamento", null=True, blank=True),
        )
    ]
