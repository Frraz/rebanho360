from decimal import Decimal

from apps.core.irr import anualizar, taxa_interna_de_retorno

D = Decimal


def test_tir_conhecida():
    # investe 100, recebe 110 no período seguinte: 10%
    assert round(taxa_interna_de_retorno([D("-100"), D("110")]), 4) == D("0.1000")


def test_tir_de_varios_periodos():
    # −1000, +500, +500, +500 → ≈ 23,38% por período
    r = taxa_interna_de_retorno([D("-1000"), D("500"), D("500"), D("500")])
    assert round(r, 4) == D("0.2338")


def test_prejuizo_da_tir_negativa():
    assert taxa_interna_de_retorno([D("-100"), D("90")]) < 0


def test_sem_troca_de_sinal_nao_ha_tir():
    assert taxa_interna_de_retorno([D("-100"), D("-50")]) is None
    assert taxa_interna_de_retorno([D("10"), D("20")]) is None
    assert taxa_interna_de_retorno([]) is None


def test_anualiza_a_taxa_mensal_composta():
    assert round(anualizar(D("0.01")), 6) == D("0.126825")
    assert anualizar(None) is None
