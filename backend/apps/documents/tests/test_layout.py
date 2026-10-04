"""PDF de relatório largo: a última coluna tem de caber na página (o de Vendas e
abates, com 14 colunas, saía cortado na margem direita)."""

import datetime
from decimal import Decimal

import pytest

from apps.documents import layout, services
from apps.reports.services import Coluna, Relatorio

pytestmark = pytest.mark.django_db


def _relatorio(colunas: int) -> Relatorio:
    cols = [
        Coluna(f"c{i}", f"Coluna {i} (rótulo longo)", "dinheiro" if i % 2 else "texto")
        for i in range(colunas)
    ]
    linha = {
        c.chave: (
            Decimal("638474.26")
            if c.tipo == "dinheiro"
            else "Coperfrigu Cooperativa de Carnes"
        )
        for c in cols
    }
    return Relatorio(
        "Largo", "d", cols, [linha, linha], totais=None, filtros=["Safra X"]
    )


def _caixas(caixa):
    yield caixa
    for filho in getattr(caixa, "children", []) or []:
        yield from _caixas(filho)


@pytest.mark.parametrize("colunas", [5, 10, 14, 16])
def test_a_tabela_cabe_na_pagina(colunas):
    import weasyprint

    html = services.renderizar_html(
        _relatorio(colunas),
        emitido_por="Teste",
        emitido_em=datetime.datetime(2026, 10, 4, 12, 0),
        versao=services.TEMPLATE_VERSION,
    )
    pagina = weasyprint.HTML(string=html).render().pages[0]._page_box
    limite = pagina.margin_width() - pagina.margin_right
    tabelas = [c for c in _caixas(pagina) if getattr(c, "element_tag", "") == "table"]
    assert tabelas
    for tabela in tabelas:
        assert tabela.position_x + tabela.margin_width() <= limite + 0.5


def test_larguras_somam_cem_e_dao_mais_espaco_ao_texto_longo():
    tabela = {
        "cabecalho": ["Comprador", "Data", "Cabeças"],
        "celulas": [
            [("Coperfrigu Cooperativa", False), ("01/10/2026", False), ("94", True)]
        ],
    }
    larguras = layout.larguras_percentuais(tabela)
    assert round(sum(larguras)) == 100
    assert larguras[0] > larguras[2]


def test_densidade_pelo_numero_de_colunas():
    assert layout.densidade(7) == ""
    assert layout.densidade(10) == "densa"
    assert layout.densidade(14) == "muito-densa"
