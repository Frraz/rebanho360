"""O rendimento oficial é o que o frigorífico informa (cliente, 2026-10-03);
o calculado (carcaça ÷ peso vivo) continua disponível para conferência."""

from decimal import Decimal

import pytest

from apps.sales import carcass, services
from apps.sales.tests.conftest import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db
D = Decimal


def test_sem_rendimento_informado_vale_o_calculado(escritorio, dados_abate):
    venda = services.criar_venda(usuario=escritorio, **dados_abate)
    ind = carcass.indicadores_da_venda(venda)
    assert round(ind.rendimento, 2) == D("51.33")
    assert ind.rendimento_origem == "calculado"


def test_o_informado_prevalece_e_o_calculado_fica_para_conferir(
    escritorio, dados_abate
):
    venda = services.criar_venda(
        usuario=escritorio, **{**dados_abate, "reported_yield_percent": D("52.10")}
    )
    ind = carcass.indicadores_da_venda(venda)
    assert ind.rendimento == D("52.10")
    assert ind.rendimento_origem == "informado"
    assert round(ind.rendimento_calculado, 2) == D("51.33")


def test_a_soma_rendimento_da_planilha_nao_vira_indicador(escritorio, dados_abate):
    """Pendência #7(b): o significado de "SOMA RENDIMENTO" não foi definido;
    não há campo nem cálculo para ele."""
    campos = {
        f.name
        for f in type(
            services.criar_venda(usuario=escritorio, **dados_abate)
        )._meta.fields
    }
    assert not any("soma_rend" in c or "sum_yield" in c for c in campos)


def test_agregado_pondera_o_rendimento_efetivo_pelo_peso_vivo(
    escritorio, dados_abate, lote_gordo
):
    a = services.criar_venda(
        usuario=escritorio, **{**dados_abate, "reported_yield_percent": D("50")}
    )
    agregado = carcass.agregar([a])
    assert agregado.indicadores.rendimento == D("50")


def test_condicao_de_recebimento_na_venda(escritorio, dados_abate):
    from apps.commercial.models import PaymentCondition

    condicao = PaymentCondition.objects.get_or_create(
        name="15 dias", defaults={"days": "15"}
    )[0]
    venda = services.criar_venda(
        usuario=escritorio, **{**dados_abate, "payment_condition": condicao}
    )
    assert venda.payment_condition == condicao and venda.payment_days == 15
