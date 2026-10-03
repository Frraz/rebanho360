"""Condições de pagamento de partida — os exemplos que o cliente deu
(2026-10-03). São só um começo: o usuário cria, edita e desativa as dele."""

from django.db import migrations

CONDICOES = [
    ("À vista", "0", 1),
    ("4 dias", "4", 2),
    ("7 dias", "7", 3),
    ("15 dias", "15", 4),
    ("30 dias", "30", 5),
    ("Parcelado em 30, 60 e 90 dias", "30,60,90", 6),
]


def semear(apps, schema_editor):
    PaymentCondition = apps.get_model("commercial", "PaymentCondition")
    for nome, dias, ordem in CONDICOES:
        PaymentCondition.objects.get_or_create(
            name=nome, defaults={"days": dias, "display_order": ordem}
        )


class Migration(migrations.Migration):

    dependencies = [
        ("commercial", "0003_paymentcondition_taxtype_effect_and_more"),
    ]

    operations = [
        migrations.RunPython(semear, migrations.RunPython.noop),
    ]
