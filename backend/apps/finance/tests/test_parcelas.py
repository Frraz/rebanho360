"""Condição de pagamento parcelada: um título por parcela, valor exato, sem
duplicar e acompanhando a correção da operação (cliente, 2026-10-03)."""

import datetime
from decimal import Decimal

import pytest

from apps.commercial.models import PaymentCondition
from apps.finance.models import Component, Invoice
from apps.finance.tests.conftest import DATA_COMPRA
from apps.purchases import services as compras
from apps.sales import services as vendas

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def trinta_sessenta_noventa():
    return PaymentCondition.objects.get_or_create(
        name="Parcelado em 30, 60 e 90 dias", defaults={"days": "30,60,90"}
    )[0]


@pytest.fixture
def compra_parcelada(escritorio, dados_compra, trinta_sessenta_noventa):
    dados = {**dados_compra, "payment_condition": trinta_sessenta_noventa}
    return compras.confirmar_compra(
        compras.criar_compra(usuario=escritorio, **dados), usuario=escritorio
    )


def _animais(compra):
    return list(
        Invoice.objects.filter(
            origin_purchase=compra, component=Component.ANIMAIS, status="CONFIRMADA"
        ).order_by("due_date")
    )


class TestCompraParcelada:
    def test_gera_um_titulo_por_parcela_e_a_soma_fecha(self, compra_parcelada):
        parcelas = _animais(compra_parcelada)

        assert [p.ref for p in parcelas] == ["parcela:1", "parcela:2", "parcela:3"]
        assert [p.due_date for p in parcelas] == [
            DATA_COMPRA + datetime.timedelta(days=d) for d in (30, 60, 90)
        ]
        assert sum(p.amount for p in parcelas) == compra_parcelada.animal_value
        assert compra_parcelada.payment_days == 30  # o primeiro prazo

    def test_centavo_nao_se_perde(
        self, escritorio, dados_compra, trinta_sessenta_noventa
    ):
        dados = {
            **dados_compra,
            "animal_value": D("100.00"),
            "payment_condition": trinta_sessenta_noventa,
        }
        compra = compras.confirmar_compra(
            compras.criar_compra(usuario=escritorio, **dados), usuario=escritorio
        )
        assert sorted(p.amount for p in _animais(compra)) == [
            D("33.33"),
            D("33.33"),
            D("33.34"),
        ]

    def test_confirmar_de_novo_nao_duplica(self, compra_parcelada, escritorio):
        from apps.finance import services as fin

        fin.gerar_titulos_da_compra(compra_parcelada, usuario=escritorio)
        assert len(_animais(compra_parcelada)) == 3

    def test_trocar_para_a_vista_cancela_as_parcelas_e_gera_um_so(
        self, compra_parcelada, escritorio
    ):
        a_vista = PaymentCondition.objects.get_or_create(
            name="À vista", defaults={"days": "0"}
        )[0]
        compras.editar_compra(
            compra_parcelada,
            {"payment_condition": a_vista},
            usuario=escritorio,
            motivo="Combinado à vista",
        )
        vigentes = _animais(compra_parcelada)
        assert [p.ref for p in vigentes] == [""]
        assert vigentes[0].amount == compra_parcelada.animal_value
        assert vigentes[0].due_date == DATA_COMPRA

    def test_compra_sem_condicao_segue_com_um_titulo_so(self, compra):
        (titulo,) = _animais(compra)
        assert titulo.ref == ""
        assert titulo.due_date == DATA_COMPRA + datetime.timedelta(days=30)


class TestVendaParcelada:
    def test_recebimento_parcelado(
        self, escritorio, dados_abate, trinta_sessenta_noventa
    ):
        rascunho = vendas.criar_venda(
            usuario=escritorio,
            **{**dados_abate, "payment_condition": trinta_sessenta_noventa},
        )
        venda = vendas.confirmar_venda(rascunho, usuario=escritorio)

        parcelas = list(
            venda.invoices.filter(component=Component.VENDA).order_by("due_date")
        )
        assert len(parcelas) == 3
        assert sum(p.amount for p in parcelas) == venda.total_value
        assert all(p.direction == "RECEBER" for p in parcelas)
