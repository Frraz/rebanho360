"""O ciclo inteiro, do compromisso à compra: o teste que prova que as peças
se encaixam. As regras de cada peça têm os seus testes."""

import pytest

from apps.core.reversible import Status
from apps.herd.models import HerdLedgerEntry
from apps.procurement import selectors
from apps.procurement.settlement import calcular_acerto

pytestmark = pytest.mark.django_db


def test_do_compromisso_ao_titulo(acerto, aprovar, compromisso):
    calculo = calcular_acerto(compromisso)
    assert calculo.pendencias == []
    assert calculo.valor_dos_animais == 43200

    aprovar(acerto)

    item = compromisso.items.get()
    compra = item.purchase
    assert compra.status == Status.CONFIRMADA
    assert compra.head_count == 10
    assert compra.animal_value == 43200
    assert compra.freight_value == 500
    assert sum(e.quantity for e in HerdLedgerEntry.objects.filter(lot=compra.lot)) == 10
    assert compra.invoices.count() == 2  # animais + frete
    assert selectors.etapa_do_compromisso(compromisso) == "ACERTO_APROVADO"
