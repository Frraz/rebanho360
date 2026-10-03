"""F5-04 — escolher e calcular a comissão (CommissionService, pendência #4)."""

import datetime
from decimal import Decimal

import pytest

from apps.commercial.commission import calcular_comissao, escolher_regra
from apps.commercial.models import CommissionRule

pytestmark = pytest.mark.django_db
D = Decimal
DATA = datetime.date(2025, 9, 18)


def regra(**kw):
    dados = dict(
        type="PERCENTUAL",
        base="BRUTO",
        value=D("1"),
        valid_from=datetime.date(2025, 1, 1),
    )
    return CommissionRule.objects.create(**(dados | kw))


# --- cálculo ---------------------------------------------------------------


def test_percentual_sobre_o_bruto():
    valor = calcular_comissao(
        tipo="PERCENTUAL",
        base="BRUTO",
        valor=D("1.5"),
        valor_bruto=D("100000"),
        deducoes=D("7000"),
        cabecas=50,
    )
    assert valor == D("1500.00")


def test_percentual_sobre_o_liquido_desconta_frete_e_tributos():
    valor = calcular_comissao(
        tipo="PERCENTUAL",
        base="LIQUIDO",
        valor=D("1.5"),
        valor_bruto=D("100000"),
        deducoes=D("10000"),
        cabecas=50,
    )
    assert valor == D("1350.00")


def test_bruto_e_liquido_dao_valores_diferentes_com_a_mesma_regra():
    """É a pendência #4 em um teste: a base muda o dinheiro."""
    comum = dict(
        tipo="PERCENTUAL",
        valor=D("2"),
        valor_bruto=D("200000"),
        deducoes=D("20000"),
        cabecas=100,
    )
    assert calcular_comissao(base="BRUTO", **comum) == D("4000.00")
    assert calcular_comissao(base="LIQUIDO", **comum) == D("3600.00")


def test_liquido_nunca_fica_negativo():
    valor = calcular_comissao(
        tipo="PERCENTUAL",
        base="LIQUIDO",
        valor=D("1"),
        valor_bruto=D("1000"),
        deducoes=D("5000"),
        cabecas=1,
    )
    assert valor == D("0.00")


def test_por_cabeca():
    valor = calcular_comissao(
        tipo="POR_CABECA",
        base="BRUTO",
        valor=D("12.50"),
        valor_bruto=None,
        deducoes=None,
        cabecas=126,
    )
    assert valor == D("1575.00")


def test_sem_cabecas_a_comissao_por_cabeca_e_none_nao_zero():
    assert (
        calcular_comissao(
            tipo="POR_CABECA",
            base="BRUTO",
            valor=D("12.50"),
            valor_bruto=None,
            deducoes=None,
            cabecas=0,
        )
        is None
    )


def test_sem_valor_bruto_o_percentual_e_none():
    assert (
        calcular_comissao(
            tipo="PERCENTUAL",
            base="BRUTO",
            valor=D("1"),
            valor_bruto=None,
            deducoes=None,
            cabecas=10,
        )
        is None
    )


def test_arredonda_meio_centavo_para_cima_so_no_fim():
    """0,005 → 0,01 (ROUND_HALF_UP, ADR 0005): 0,5% de R$ 1,00."""
    valor = calcular_comissao(
        tipo="PERCENTUAL",
        base="BRUTO",
        valor=D("0.5"),
        valor_bruto=D("1.00"),
        deducoes=None,
        cabecas=1,
    )
    assert valor == D("0.01")


# --- escolha da regra -------------------------------------------------------


def test_sem_regra_devolve_none(comissionado, categoria_desmamados):
    assert (
        escolher_regra(
            comissionado=comissionado, categoria=categoria_desmamados, data=DATA
        )
        is None
    )


def test_a_regra_do_comissionado_vence_a_geral(comissionado, categoria_desmamados):
    regra(value=D("1"))
    propria = regra(value=D("2"), commissioned=comissionado)
    escolhida = escolher_regra(
        comissionado=comissionado, categoria=categoria_desmamados, data=DATA
    )
    assert escolhida == propria


def test_comissionado_pesa_mais_que_categoria(comissionado, categoria_desmamados):
    regra(value=D("3"), category=categoria_desmamados)
    do_comissionado = regra(value=D("2"), commissioned=comissionado)
    escolhida = escolher_regra(
        comissionado=comissionado, categoria=categoria_desmamados, data=DATA
    )
    assert escolhida == do_comissionado


def test_regra_de_outro_comissionado_nao_vale(comissionado, outro_comissionado):
    regra(commissioned=outro_comissionado)
    assert escolher_regra(comissionado=comissionado, categoria=None, data=DATA) is None


def test_vigencia_so_vale_dentro_do_periodo(comissionado):
    regra(valid_from=datetime.date(2025, 1, 1), valid_to=datetime.date(2025, 6, 30))
    assert escolher_regra(comissionado=comissionado, categoria=None, data=DATA) is None
    assert (
        escolher_regra(
            comissionado=comissionado,
            categoria=None,
            data=datetime.date(2025, 3, 1),
        )
        is not None
    )


def test_entre_regras_iguais_vence_a_vigencia_mais_recente(comissionado):
    regra(value=D("1"), valid_from=datetime.date(2025, 1, 1))
    nova = regra(value=D("1.5"), valid_from=datetime.date(2025, 8, 1))
    assert escolher_regra(comissionado=comissionado, categoria=None, data=DATA) == nova


def test_regra_inativa_nunca_e_escolhida(comissionado):
    regra(is_active=False)
    assert escolher_regra(comissionado=comissionado, categoria=None, data=DATA) is None


def test_sem_comissionado_na_operacao_so_vale_regra_geral(comissionado):
    regra(commissioned=comissionado)
    geral = regra(value=D("0.5"))
    assert escolher_regra(comissionado=None, categoria=None, data=DATA) == geral
