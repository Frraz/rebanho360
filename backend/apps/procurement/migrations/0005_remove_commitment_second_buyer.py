from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0004_comprador_adicional_vira_comissao"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="commitment",
            name="second_buyer",
        ),
    ]
