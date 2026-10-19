from django.db import migrations


def criar_centros(apps, schema_editor):
    Centro=apps.get_model("costs", "CostCenter")
    for nome in ("FRETE DE COMPRA", "FRETE DE TRANSFERÊNCIA"):
        Centro.objects.get_or_create(name=nome)


class Migration(migrations.Migration):
    dependencies=[("costs", "0008_costentry_source_freight")]
    operations=[migrations.RunPython(criar_centros, migrations.RunPython.noop)]
