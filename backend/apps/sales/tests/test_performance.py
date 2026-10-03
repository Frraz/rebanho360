"""F3-06 (lado da venda) — a @ produzida precisa de abate com carcaça e de
uma pesagem de entrada: o peso de entrada nunca é estimado."""

from decimal import Decimal

import pytest

from apps.herd.weight_gain import desempenho_do_lote

pytestmark = pytest.mark.django_db

D = Decimal


def test_sem_pesagem_de_entrada_nao_se_estima_carcaca_de_entrada(
    criar, confirmar, dados_abate
):
    confirmar(criar(**dados_abate))

    d = desempenho_do_lote(dados_abate["lot"], rendimento_entrada=D("50"))

    assert d.arrobas_produzidas is None
    assert any("sem pesagem de entrada" in m for m in d.motivos)
