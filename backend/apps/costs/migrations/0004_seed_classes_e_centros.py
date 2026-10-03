"""Semeia as 2 classes e os 11 centros de custo reais da planilha
(docs/regras-negocio/02#costcenter--centro-de-custo).

Dado de referência, não de demonstração: o sistema precisa deles em
produção também — o importador de custos e a confirmação de compra
procuram DESPESA GADO, COMISSÃO e IMPOSTO E TAXAS pelo nome.
"""

from django.db import migrations

CLASSES = ["CUSTEIO", "INVESTIMENTO"]

CENTROS = [
    "FUNCIONARIO",
    "PARQUE DE MÁQUINAS",
    "DESPESA GADO",
    "INFRAESTRUTURA",
    "OUTROS",
    "NUTRIÇÃO",
    "PASTAGEM",
    "IMPOSTO E TAXAS",
    "COMISSÃO",
    "SANIDADE",
    "FERPAM",
]


def semear(apps, schema_editor):
    CostClass = apps.get_model("costs", "CostClass")
    CostCenter = apps.get_model("costs", "CostCenter")
    for nome in CLASSES:
        CostClass.objects.get_or_create(name=nome)
    for nome in CENTROS:
        CostCenter.objects.get_or_create(name=nome)


class Migration(migrations.Migration):

    dependencies = [
        ("costs", "0003_costentry_source_purchase_costentry_updated_by_and_more"),
    ]

    operations = [
        # Sem reverso: apagar centros reverteria dados que já podem ter lançamentos.
        migrations.RunPython(semear, migrations.RunPython.noop),
    ]
