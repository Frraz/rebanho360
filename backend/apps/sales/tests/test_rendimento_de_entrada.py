"""Rendimento estimado de entrada: editável, informado na compra e usado pela @
produzida do lote (cliente, 2026-10-03). Nenhum valor é imposto pelo sistema."""

from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.herd.weight_gain import rendimento_de_entrada_do_lote
from apps.purchases import services as compras
from apps.sales.tests.conftest import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db
D = Decimal


def test_sem_nenhuma_compra_informar_o_sistema_nao_escolhe(lote_de_compra):
    assert rendimento_de_entrada_do_lote(lote_de_compra) is None


def test_usa_o_que_o_usuario_informou_na_compra(
    lote_de_compra, escritorio, sao_francisco, categoria_25_36, vendedor
):
    compra = lote_de_compra.purchases.get()
    compras.editar_compra(
        compra,
        {"entry_yield_percent": D("48.5")},
        usuario=escritorio,
        motivo="Rendimento estimado de entrada",
    )
    assert rendimento_de_entrada_do_lote(lote_de_compra) == D("48.5")


def test_rendimento_fora_de_1_a_100_e_recusado(lote_de_compra, escritorio):
    compra = lote_de_compra.purchases.get()
    with pytest.raises(BusinessError, match="entre 1% e 100%"):
        compras.editar_compra(
            compra,
            {"entry_yield_percent": D("150")},
            usuario=escritorio,
            motivo="x",
        )
