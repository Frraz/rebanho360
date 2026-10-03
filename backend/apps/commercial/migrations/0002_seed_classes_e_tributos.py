"""Semeia as seis classificações de carcaça e os tipos de tributo/taxa do
legado (`04_Conferencia_do_Acerto`).

Dado de referência, não de demonstração. As naturezas dos tipos são
provisórias (pendência #21) e mudam em Tributos e taxas, sem código. A lista
é uma cópia congelada de `apps/commercial/seed.py` — migração não importa
código vivo.
"""

from django.db import migrations

CLASSES = [
    ("MAGRO", "Magro", 1),
    ("AUSENTE", "Gordura ausente", 2),
    ("ESCASSA", "Gordura escassa", 3),
    ("MEDIANA", "Gordura mediana", 4),
    ("UNIFORME", "Gordura uniforme", 5),
    ("LESAO", "Lesão traumática", 6),
]

TIPOS = [
    ("Funrural", "TRIBUTO"),
    ("Fundepec", "TAXA"),
    ("GTA", "TAXA"),
    ("ICMS", "TRIBUTO"),
    ("Taxa de abate", "TAXA"),
    ("Indenização", "TAXA"),
    ("Idaterra", "TAXA"),
    ("Incentivo Precoce", "CREDITO"),
    ("Crédito GR-3", "CREDITO"),
    ("Desconto", "DESCONTO"),
    ("Adiantamento", "ADIANTAMENTO"),
]


def semear(apps, schema_editor):
    CarcassClass = apps.get_model("commercial", "CarcassClass")
    TaxType = apps.get_model("commercial", "TaxType")
    for codigo, nome, ordem in CLASSES:
        CarcassClass.objects.get_or_create(
            code=codigo, defaults={"name": nome, "display_order": ordem}
        )
    for ordem, (nome, natureza) in enumerate(TIPOS, start=1):
        TaxType.objects.get_or_create(
            name=nome, defaults={"nature": natureza, "display_order": ordem}
        )


class Migration(migrations.Migration):

    dependencies = [
        ("commercial", "0001_initial"),
    ]

    operations = [
        # Sem reverso: apagar os cadastros reverteria dados já usados em romaneios.
        migrations.RunPython(semear, migrations.RunPython.noop),
    ]
