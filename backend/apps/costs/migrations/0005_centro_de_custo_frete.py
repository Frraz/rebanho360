"""Centro de custo próprio do frete (pendência #36, respondida pelo cliente em
2026-10-03): o custo dos animais (DESPESA GADO), o do frete e os demais custos
da operação ficam separados.

Só cria o centro. Os custos de frete **já lançados** continuam onde estão
(DESPESA GADO): mexer em lançamento por migração passaria por cima da
auditoria. Compra corrigida ou restaurada regera os custos e o frete passa a
cair no centro novo.
"""

from django.db import migrations


def semear(apps, schema_editor):
    CostCenter = apps.get_model("costs", "CostCenter")
    CostCenter.objects.get_or_create(name="FRETE")


class Migration(migrations.Migration):

    dependencies = [
        ("costs", "0004_seed_classes_e_centros"),
    ]

    operations = [
        migrations.RunPython(semear, migrations.RunPython.noop),
    ]
