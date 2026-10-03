"""O "comprador adicional" (só informativo, sem comissão) vira uma linha de
comissão de valor zero. Em migração própria: misturar `INSERT` e `ALTER TABLE`
na mesma transação do Postgres dá "pending trigger events"."""

from django.db import migrations


def levar_comprador_adicional(apps, schema_editor):
    """O "comprador adicional" (só informativo, sem comissão) vira uma linha de
    comissão de valor zero: o comprador continua no compromisso e o usuário
    informa a comissão dele quando houver."""
    Commitment = apps.get_model("procurement", "Commitment")
    Commission = apps.get_model("procurement", "Commission")
    for c in Commitment.objects.exclude(second_buyer__isnull=True):
        if Commission.objects.filter(commitment=c, payee=c.second_buyer).exists():
            continue
        proxima = Commission.objects.filter(commitment=c).count() + 1
        Commission.objects.create(
            commitment=c,
            payee=c.second_buyer,
            position=max(proxima, 2),
            source="MANUAL",
            type="VALOR",
            base="BRUTO",
            value=0,
            extra_amount=0,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0003_settlementallocation_alter_commission_options_and_more"),
    ]

    operations = [
        migrations.RunPython(levar_comprador_adicional, migrations.RunPython.noop),
    ]
