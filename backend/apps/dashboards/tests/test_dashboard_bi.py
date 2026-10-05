"""O dashboard analítico: recorte e comparação, contrato dos gráficos, permissão
e escopo por fazenda, e — o que mais importa — o mesmo número que o resto do
sistema mostra para o mesmo indicador (regra 6 do CLAUDE.md)."""

import datetime
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.accounts.models import Role, User, UserFarmAccess
from apps.dashboards import selectors
from apps.dashboards.bi import (
    abas,
    compras,
    custos,
    financeiro,
    insights,
    rebanho,
    specs,
    vendas,
)
from apps.dashboards.bi.escopo import Escopo
from apps.herd import services as herd
from apps.herd.models import MovementType
from apps.herd.mortality import taxa_de_mortalidade
from apps.organizations.models import Season
from apps.purchases import services as compras_servico
from apps.purchases.services import custo_da_compra
from apps.sales import carcass
from apps.sales.result import resultado_do_lote
from apps.sales.tests.conftest import vender

pytestmark = pytest.mark.django_db

D = Decimal
HOJE = datetime.date(2025, 12, 1)
RAIZ = Path(__file__).resolve().parents[3]


def escopo(user, season, **kw):
    return Escopo.criar(user, season=season, hoje=kw.pop("hoje", HOJE), **kw)


@pytest.fixture
def venda_parcial(escritorio, lote_de_compra, frigorifico, categoria_25_36):
    """60 das 100 cabeças vendidas no abate de 03/08/2025: o lote segue aberto
    (resultado parcial) e o rebanho não zera."""
    return vender(
        escritorio,
        lote_de_compra,
        frigorifico,
        categoria_25_36,
        head_count=60,
        total_weight_kg=D("28800"),
        carcass_weight_kg=D("14400"),
        total_value=D("288000"),
    )


@pytest.fixture
def safra_anterior(company):
    return Season.objects.create(
        company=company,
        name="2024/2025",
        start_date=datetime.date(2024, 7, 1),
        end_date=datetime.date(2025, 6, 30),
    )


# --------------------------------------------------------------------------
# Recorte
# --------------------------------------------------------------------------


class TestEscopo:
    def test_sem_safra_nao_ha_recorte(self, gestor):
        assert Escopo.criar(gestor, season=None) is None

    def test_o_corte_e_hoje_ou_o_fim_da_safra(self, gestor, season):
        assert escopo(gestor, season).fim == HOJE
        assert (
            escopo(gestor, season, hoje=datetime.date(2027, 1, 1)).fim
            == season.end_date
        )

    def test_safra_futura_nao_inverte_o_intervalo(self, gestor, season):
        e = escopo(gestor, season, hoje=datetime.date(2025, 1, 1))
        assert e.fim == e.inicio == season.start_date

    def test_compara_com_a_safra_anterior_no_mesmo_ponto(
        self, gestor, season, safra_anterior
    ):
        e = escopo(gestor, season, hoje=datetime.date(2025, 9, 30))  # dia 91
        assert e.anterior.season == safra_anterior
        assert e.anterior.fim == datetime.date(2024, 9, 30)  # 91 dias depois do início
        assert e.anterior.anterior is None

    def test_safra_anterior_fechada_nao_passa_do_fim_dela(
        self, gestor, season, safra_anterior
    ):
        e = escopo(gestor, season, hoje=datetime.date(2026, 6, 30))
        assert e.anterior.fim == safra_anterior.end_date

    def test_primeira_safra_nao_tem_comparacao(self, gestor, season):
        assert escopo(gestor, season).anterior is None

    def test_cache_nao_e_dividido_com_a_safra_anterior(
        self, gestor, season, safra_anterior
    ):
        e = escopo(gestor, season)
        e.memo("x", lambda: 1)
        assert e.anterior.memo("x", lambda: 2) == 2

    def test_campo_nao_ve_dinheiro(self, campo_baixao, gestor, season):
        assert escopo(campo_baixao, season).ver_dinheiro is False
        assert escopo(gestor, season).ver_dinheiro is True


# --------------------------------------------------------------------------
# Contrato dos gráficos
# --------------------------------------------------------------------------


class TestEspecificacoes:
    def test_variacao_percentual(self):
        d = specs.variacao(D("110"), D("100"))
        assert (d.texto, d.sentido, d.avaliacao) == ("+10,0%", "alta", "bom")
        assert (
            specs.variacao(D("110"), D("100"), bom_quando="baixa").avaliacao == "ruim"
        )
        assert specs.variacao(D("90"), D("100"), bom_quando=None).avaliacao == "neutro"
        assert specs.variacao(D("100"), D("100")).sentido == "estavel"

    def test_sem_base_nao_ha_variacao_nem_infinito(self):
        assert specs.variacao(D("5"), D("0")) is None
        assert specs.variacao(None, D("5")) is None
        assert specs.variacao(D("5"), None) is None

    def test_variacao_em_pontos_percentuais(self):
        assert specs.variacao_pp(D("2.5"), D("2.0")).texto == "+0,5 p.p."
        assert (
            specs.variacao_pp(D("1.0"), D("2.0"), bom_quando="baixa").avaliacao == "bom"
        )

    def test_o_delta_sempre_tem_texto_para_leitor_de_tela(self):
        assert "subiu +10,0%" in specs.variacao(D("110"), D("100")).leitura

    def test_unica_fronteira_decimal_para_float_arredonda_para_cima(self):
        assert specs.num(D("0.00005")) == 0.0001  # ROUND_HALF_UP, não o par do float
        assert specs.num(D("2.675")) == 2.675
        assert specs.num(None) is None

    def test_formatacao_brasileira_e_travessao(self):
        assert specs.formatar(None) == "—"
        assert specs.formatar(D("1234.5"), "brl") == "R$ 1.234,50"
        assert (
            specs.formatar(2.675, "num2") == "2,68"
        )  # float já arredondado não reabre a cauda binária
        assert specs.brl_curto(D("1250000")) == "R$ 1,25 mi"
        assert specs.brl_curto(D("-583700")) == "−R$ 583,7 mil"
        assert specs.brl_curto(None) == "—"

    def test_sparkline_precisa_de_dois_pontos(self):
        assert specs.sparkline([D("1")]) is None
        assert specs.sparkline([D("1"), None]) is None
        assert specs.sparkline([None, None]) is None

    def test_sparkline_de_serie_constante_nao_divide_por_zero(self):
        s = specs.sparkline([D("5"), D("5"), D("5")])
        assert s is not None and "," in s.pontos
        assert (
            "," not in s.ultimo_x
        )  # ponto decimal, não vírgula: vai para atributo SVG

    def test_grade_nunca_deixa_buraco(self):
        def g(*larguras):
            return [
                specs.Grafico(str(i), "t", "cartesiano", {}, largura=larg)
                for i, larg in enumerate(larguras)
            ]

        um = g("terco")
        specs.reorganizar(um)
        assert um[0].largura == "cheia"
        dois = g("terco", "terco")
        specs.reorganizar(dois)
        assert [x.largura for x in dois] == ["metade", "metade"]
        tres = g("quarto", "quarto", "quarto")
        specs.reorganizar(tres)
        assert [x.largura for x in tres] == ["terco"] * 3
        cheia = g("dois-tercos", "terco", "terco")
        specs.reorganizar(cheia)
        assert [x.largura for x in cheia] == ["dois-tercos", "terco", "cheia"]

    def test_ranking_soma_o_resto_do_que_se_soma(self):
        g = specs.ranking(
            "r",
            "t",
            [("a", D("5")), ("b", D("3")), ("c", D("1")), ("d", D("1"))],
            formato="brl",
            limite=2,
        )
        assert g.opcoes["x"] == ["a", "b", "Outros (2)"]
        assert g.opcoes["series"][0]["dados"][-1] == 2.0

    def test_ranking_de_taxa_trunca_em_vez_de_somar(self):
        g = specs.ranking(
            "r",
            "t",
            [("a", D("0.9")), ("b", D("0.5")), ("c", D("0.2"))],
            formato="kgdia",
            limite=2,
            mostrar_participacao=False,
        )
        assert g.opcoes["x"] == ["a", "b"]
        assert "Mostra os 2 primeiros" in g.nota

    def test_grafico_de_um_elemento_so_explica_em_vez_de_desenhar(self):
        mapa = specs.calor(
            "c", "t", ["Machos"], ["Baixão"], {(0, 0): D("32")}, formato="cb"
        )
        assert (
            mapa.vazio
            and "Só há um item" in mapa.mensagem_vazia
            and "32 cb" in mapa.mensagem_vazia
        )
        arvore = specs.treemap(
            "a",
            "t",
            [
                {
                    "nome": "Baixão",
                    "valor": D("32"),
                    "filhos": [{"nome": "Machos", "valor": D("32")}],
                }
            ],
            formato="cb",
        )
        assert arvore.vazio and "Baixão › Machos" in arvore.mensagem_vazia
        rosca = specs.rosca(
            "r", "t", [("Abate", D("10"), None), ("Venda", D("0"), None)], formato="brl"
        )
        assert rosca.vazio and "100%" in rosca.mensagem_vazia
        ranking = specs.ranking("k", "t", [("COPERFRIGU", D("10"))], formato="brl")
        assert ranking.vazio and "COPERFRIGU" in ranking.mensagem_vazia
        # Com dois ou mais, desenha.
        assert not specs.calor(
            "c", "t", ["a", "b"], ["x"], {(0, 0): D("1"), (1, 0): D("2")}
        ).vazio
        assert not specs.ranking(
            "k", "t", [("a", D("1")), ("b", D("2"))], formato="brl"
        ).vazio

    def test_grafico_sem_ponto_vira_vazio_e_sai_do_json(self):
        vazio = specs.cartesiano("v", "t", ["jan"], [specs.serie("s", [D("0")])])
        cheio = specs.cartesiano("c", "t", ["jan"], [specs.serie("s", [D("3")])])
        painel = specs.Painel(secoes=[specs.Secao("x", [vazio, cheio])])
        assert vazio.vazio and not cheio.vazio
        assert list(painel.json_dos_graficos()) == ["c"]

    def test_tabela_resolve_barra_marca_e_link(self):
        t = specs.Tabela(
            ["Lote", "GMD"],
            [["LT-1", "0,5"], ["LT-2", "—"]],
            numericas=[1],
            links=["/a/", "/b/"],
            codigo=0,
        )
        t.barra(1, [D("0.5"), None])
        t.marcas[(0, 1)] = ("atencao", "abaixo da média")
        a, b = t.linhas_prontas
        assert a.url == "/a/" and a.celulas[0].codigo and a.celulas[1].barra == 100.0
        assert a.celulas[1].estado_texto == "abaixo da média"  # cor nunca sozinha
        assert b.celulas[1].barra is None

    def test_toda_tabela_gemea_tem_as_mesmas_linhas_do_grafico(self):
        g = specs.cartesiano(
            "v", "t", ["jan", "fev"], [specs.serie("s", [D("1"), None])], formato="num0"
        )
        assert g.tabela.linhas == [["jan", "1"], ["fev", "—"]]


# --------------------------------------------------------------------------
# Telas e permissão
# --------------------------------------------------------------------------

SLUGS = [a.slug for a in abas.ABAS]


class TestTelas:
    def test_exige_login(self, client):
        r = client.get(reverse("dashboards:dashboard"))
        assert r.status_code == 302 and "/contas/entrar/" in r["Location"]

    @pytest.mark.parametrize("slug", SLUGS)
    def test_toda_aba_abre_para_o_gestor(
        self, client, gestor, season, venda_parcial, slug
    ):
        client.force_login(gestor)
        r = client.get(reverse("dashboards:dashboard_aba", args=[slug]))
        assert r.status_code == 200
        assert f'id="dash-aba-{slug}"' in r.content.decode()

    def test_raiz_e_a_visao_geral(self, client, gestor, season):
        client.force_login(gestor)
        assert (
            'id="dash-aba-visao-geral"'
            in client.get(reverse("dashboards:dashboard")).content.decode()
        )

    def test_aba_inexistente_e_404(self, client, gestor, season):
        client.force_login(gestor)
        assert client.get("/dashboard/nao-existe/").status_code == 404

    def test_htmx_recebe_so_o_fragmento(self, client, gestor, season, venda_parcial):
        client.force_login(gestor)
        r = client.get(
            reverse("dashboards:dashboard_aba", args=["compras"]),
            HTTP_HX_REQUEST="true",
        )
        html = r.content.decode()
        assert "<html" not in html and 'class="dash-tabs"' in html
        assert "HX-Request" in r["Vary"]

    def test_pagina_inteira_sem_htmx_tem_o_resto_do_site(self, client, gestor, season):
        client.force_login(gestor)
        html = client.get(reverse("dashboards:dashboard")).content.decode()
        assert "<html" in html and "vendor/echarts-" in html and "dashboard.js" in html

    def test_campo_nao_entra_em_aba_com_dinheiro(self, client, campo_baixao, season):
        client.force_login(campo_baixao)
        for slug in ("compras", "vendas", "custos", "financeiro", "ciclo"):
            assert (
                client.get(reverse("dashboards:dashboard_aba", args=[slug])).status_code
                == 403
            )
        for slug in ("visao-geral", "rebanho", "mortes", "lotes"):
            assert (
                client.get(reverse("dashboards:dashboard_aba", args=[slug])).status_code
                == 200
            )

    def test_campo_nao_ve_dinheiro_nem_na_visao_geral(
        self,
        client,
        campo_baixao,
        escritorio,
        baixao,
        season,
        categoria_25_36,
        vendedor,
    ):
        compra = compras_servico.criar_compra(
            usuario=escritorio,
            date=datetime.date(2025, 7, 10),
            destination_farm=baixao,
            category=categoria_25_36,
            seller=vendedor,
            head_count=20,
            animal_value=D("50000"),
        )
        compras_servico.confirmar_compra(compra, usuario=escritorio)
        client.force_login(campo_baixao)
        html = client.get(reverse("dashboards:dashboard")).content.decode()
        assert "Rebanho atual" in html
        for proibido in (
            "Investimento em compras",
            "Receita de vendas",
            "Custos da safra",
            "A pagar em aberto",
        ):
            assert proibido not in html
        assert [a.slug for a in abas.abas_visiveis(campo_baixao)] == [
            "visao-geral",
            "rebanho",
            "mortes",
            "lotes",
        ]

    def test_financeiro_so_para_quem_ve_titulos(self, client, season):
        consulta = User.objects.create_user(
            username="c", password="x", role=Role.CONSULTA
        )
        client.force_login(consulta)
        assert (
            client.get(
                reverse("dashboards:dashboard_aba", args=["financeiro"])
            ).status_code
            == 200
        )
        campo = User.objects.create_user(username="c2", password="x", role=Role.CAMPO)
        client.force_login(campo)
        assert (
            client.get(
                reverse("dashboards:dashboard_aba", args=["financeiro"])
            ).status_code
            == 403
        )

    def test_sem_safra_explica_o_que_fazer(self, client, gestor, season):
        Season.objects.all().delete()
        client.force_login(gestor)
        r = client.get(reverse("dashboards:dashboard"))
        assert r.status_code == 200 and "Escolha uma safra" in r.content.decode()

    def test_o_menu_traz_o_dashboard_logo_abaixo_do_inicio(
        self, client, gestor, season
    ):
        client.force_login(gestor)
        html = client.get(reverse("dashboards:inicio")).content.decode()
        assert 'href="/dashboard/"' in html
        assert html.index(">Início<") < html.index(">Dashboard<")

    def test_o_item_do_menu_acende_nas_abas(self, client, gestor, season):
        client.force_login(gestor)
        html = client.get(
            reverse("dashboards:dashboard_aba", args=["rebanho"])
        ).content.decode()
        assert re.search(
            r'href="/dashboard/"\s+class="nav-item"\s+aria-current="page"', html
        )

    def test_o_json_dos_graficos_chega_ao_html_e_cada_grafico_tem_seu_alvo(
        self, client, gestor, season, venda_parcial
    ):
        client.force_login(gestor)
        html = client.get(
            reverse("dashboards:dashboard_aba", args=["compras"])
        ).content.decode()
        dados = json.loads(
            re.search(
                r'<script id="dash-dados" type="application/json">(.*?)</script>',
                html,
                re.S,
            ).group(1)
        )
        assert dados
        for chart_id in dados:
            assert f'data-chart="{chart_id}"' in html

    def test_todo_tipo_de_grafico_tem_desenhista_no_javascript(
        self, gestor, season, venda_parcial
    ):
        js = (RAIZ / "static/js/dashboard.js").read_text(encoding="utf-8")
        desenhistas = set(
            re.search(r"const BUILDERS = \{([^}]*)\}", js)
            .group(1)
            .replace(" ", "")
            .split(",")
        )
        e = escopo(gestor, season)
        tipos = {g.tipo for a in abas.ABAS for g in a.montar(e).finalizar().graficos()}
        assert tipos <= desenhistas

    def test_template_nao_calcula(self):
        for arquivo in (RAIZ / "templates/dashboards").glob("*.html"):
            texto = arquivo.read_text(encoding="utf-8")
            assert not re.search(
                r"widthratio|\|add:|\|multiply|\|divisibleby", texto
            ), arquivo.name

    def test_cada_aba_tem_ids_de_grafico_unicos(self, gestor, season, venda_parcial):
        e = escopo(gestor, season)
        for a in abas.ABAS:
            ids = [g.id for g in a.montar(e).graficos()]
            assert len(ids) == len(set(ids)), a.slug


# --------------------------------------------------------------------------
# O mesmo número em todo lugar (regra 6)
# --------------------------------------------------------------------------


class TestMesmoNumero:
    def test_rebanho_e_o_do_painel_inicial(self, gestor, season, venda_parcial):
        e = escopo(gestor, season)
        assert (
            rebanho.total_de_cabecas(e)
            == selectors.cartao_do_rebanho(gestor, hoje=HOJE).cabecas
            == 40
        )

    def test_investimento_e_o_custo_de_aquisicao_da_compra(
        self, gestor, season, lote_de_compra
    ):
        e = escopo(gestor, season)
        compra = lote_de_compra.origin_purchase
        assert (
            compras.agregado_da_safra(e).custo
            == custo_da_compra(compra).custo_aquisicao
            == D("255000")
        )
        assert (
            compras.agregado_da_safra(e).custo_por_cabeca
            == custo_da_compra(compra).custo_por_cabeca
        )

    def test_custos_sao_os_do_cartao_da_safra(self, gestor, season, lote_de_compra):
        e = escopo(gestor, season)
        cartao = selectors.cartao_da_safra(gestor, season=season, cabecas_atuais=100)
        assert (
            custos.total(e) == cartao.custos == D("15000")
        )  # fora o frete que a compra gerou

    def test_cabecas_vendidas_e_a_soma_das_vendas(self, gestor, season, venda_parcial):
        e = escopo(gestor, season)
        kpi = {k.rotulo: k for k in vendas.kpis(e)}["Cabeças vendidas"]
        assert kpi.valor == "60" and "1 venda(s)" in kpi.nota
        # a mesma conta do gráfico de cabeças por mês e do subtexto da receita
        receita = {k.rotulo: k for k in vendas.kpis(e)}["Receita de vendas"]
        assert "60 cabeças" in receita.nota

    def test_a_visao_geral_segue_mostrando_receita_e_resultado(
        self, gestor, season, lote_de_compra, venda_parcial
    ):
        from apps.dashboards.bi import visao_geral

        rotulos = [k.rotulo for k in visao_geral.kpis(escopo(gestor, season))]
        assert "Receita de vendas" in rotulos
        assert "Resultado dos lotes vendidos" in rotulos

    def test_despesas_do_financeiro_sao_os_custos_da_safra(
        self, gestor, season, lote_de_compra
    ):
        """Soma por centro e soma por mês fecham com o total da aba Custos e com
        o cartão da safra (regra 6: um número só)."""
        e = escopo(gestor, season)
        por_centro = financeiro.grafico_despesas_por_centro(e)
        por_mes = financeiro.grafico_despesas_por_mes(e)
        total = custos.total(e)
        assert total == D("15000")
        assert sum(v for _, v, _ in custos.por_centro(e)) == total
        assert sum(custos.totais_por_mes(e)) == total
        assert (
            por_centro.id == "fin-despesas-centro" and por_mes.id == "fin-despesas-mes"
        )
        # um único centro não é ranking: o gráfico diz isso em vez de desenhar 1 barra
        assert por_centro.vazio and "FUNCIONARIO" in por_centro.aviso_vazio
        assert not por_mes.vazio
        assert "fora a compra de animais" in por_centro.nota

    def test_a_aba_financeiro_mostra_as_despesas_mesmo_sem_titulos(
        self, gestor, season, lote_de_compra
    ):
        painel = financeiro.montar(escopo(gestor, season)).finalizar()
        ids = {g.id for g in painel.graficos()}
        assert {"fin-despesas-centro", "fin-despesas-mes"} <= ids

    def test_valor_por_arroba_e_o_da_venda(self, gestor, season, venda_parcial):
        e = escopo(gestor, season)
        esperado = carcass.indicadores_da_venda(venda_parcial).valor_por_arroba
        assert (
            vendas.agregado(vendas.abates(e)).indicadores.valor_por_arroba == esperado
        )

    def test_resultado_da_safra_e_o_resultado_do_lote(
        self, gestor, season, lote_de_compra, venda_parcial
    ):
        e = escopo(gestor, season)
        do_lote = resultado_do_lote(lote_de_compra)
        r = vendas.resultado_da_safra(e)
        assert r.resultado == do_lote.resultado
        assert r.receita == do_lote.receita and r.lotes_com_resultado == 1
        assert r.margem_por_arroba == do_lote.margem_por_arroba

    def test_cascata_fecha_receita_menos_custos_igual_resultado(
        self, gestor, season, lote_de_compra, venda_parcial
    ):
        r = vendas.resultado_da_safra(escopo(gestor, season))
        assert r.receita - r.custo == r.resultado

    def test_custo_por_arroba_da_visao_geral_e_o_do_cartao(
        self, gestor, season, lote_de_compra, venda_parcial
    ):
        from apps.dashboards.bi import visao_geral

        e = escopo(gestor, season)
        cartao = selectors.cartao_da_safra(gestor, season=season, cabecas_atuais=40)
        assert visao_geral.kpi_custo_por_arroba(e).valor == specs.formatar(
            cartao.custo_por_arroba, "brl"
        )

    def test_mortalidade_e_a_do_servico(
        self, gestor, escritorio, season, lote_gordo, sao_francisco, categoria_25_36
    ):
        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 7, 25),
            quantity=3,
            usuario=escritorio,
            origin_farm=sao_francisco,
            origin_lot=lote_gordo,
            origin_category=categoria_25_36,
            reason="Picada de cobra",
        )
        e = escopo(gestor, season, hoje=datetime.date(2025, 7, 31))
        taxa = taxa_de_mortalidade(farm=sao_francisco, start=e.inicio, end=e.fim)
        assert rebanho.mortalidade(e).por_fazenda[sao_francisco].taxa == taxa.taxa
        assert (
            rebanho.mortalidade(e).taxa == taxa.taxa
        )  # uma fazenda só: a ponderação não muda nada

    def test_custo_por_cabeca_dia_usa_o_calculo_do_rateio(
        self, gestor, season, lote_de_compra
    ):
        e = escopo(gestor, season)
        from apps.costs.allocation import cabecas_dia_por_lote

        esperado = sum(
            cabecas_dia_por_lote(
                farm=lote_de_compra.farm, start=e.inicio, end=e.fim
            ).values(),
            D("0"),
        )
        assert sum(custos.cabecas_dia_por_mes(e), D("0")) == esperado
        assert custos.custo_por_cabeca_dia(e) == custos.total(e) / esperado


# --------------------------------------------------------------------------
# Escopo por fazenda (regra 4)
# --------------------------------------------------------------------------


class TestEscopoPorFazenda:
    @pytest.fixture
    def duas_compras(
        self, escritorio, baixao, sao_francisco, categoria_25_36, vendedor
    ):
        def comprar(fazenda, cabecas):
            c = compras_servico.criar_compra(
                usuario=escritorio,
                date=datetime.date(2025, 7, 10),
                destination_farm=fazenda,
                category=categoria_25_36,
                seller=vendedor,
                head_count=cabecas,
                animal_value=D("1000") * cabecas,
            )
            return compras_servico.confirmar_compra(c, usuario=escritorio)

        return comprar(sao_francisco, 100), comprar(baixao, 30)

    @pytest.fixture
    def so_baixao(self, baixao):
        user = User.objects.create_user(
            username="so-baixao", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=user, farm=baixao, can_write=True)
        return user

    def test_quem_so_tem_uma_fazenda_so_ve_ela(
        self, so_baixao, baixao, season, duas_compras
    ):
        e = escopo(so_baixao, season)
        assert compras.agregado_da_safra(e).cabecas == 30
        assert list(rebanho.saldo_por_fazenda(e)) == [baixao.pk]
        assert e.fazendas() == [baixao]
        assert all(c.destination_farm == baixao for c in compras.lista_de_compras(e))

    def test_gestor_ve_as_duas_e_o_filtro_de_fazenda_recorta(
        self, gestor, sao_francisco, season, duas_compras
    ):
        assert compras.agregado_da_safra(escopo(gestor, season)).cabecas == 130
        assert (
            compras.agregado_da_safra(
                escopo(gestor, season, farm=sao_francisco)
            ).cabecas
            == 100
        )

    def test_a_tela_nao_vaza_a_outra_fazenda(
        self, client, so_baixao, season, duas_compras
    ):
        client.force_login(so_baixao)
        for slug in ("visao-geral", "rebanho", "compras", "lotes"):
            html = client.get(
                reverse("dashboards:dashboard_aba", args=[slug])
            ).content.decode()
            assert "São Francisco" not in html.split('<div id="dash"')[1], slug
            assert "LT-SFR" not in html, slug


# --------------------------------------------------------------------------
# Falta de dado é estado normal
# --------------------------------------------------------------------------


class TestSemDados:
    @pytest.mark.parametrize("slug", SLUGS)
    def test_aba_vazia_nao_quebra_e_diz_que_esta_vazia(self, gestor, season, slug):
        painel = abas.aba_por_slug(slug).montar(escopo(gestor, season)).finalizar()
        assert painel.kpis
        if slug not in ("lotes",):
            assert painel.vazio, slug
        assert painel.json_dos_graficos() == {} or slug in (
            "custos",
            "financeiro",
            "rebanho",
            "visao-geral",
        )

    def test_kpi_sem_dado_e_travessao_nunca_zero_reais(self, gestor, season):
        e = escopo(gestor, season)
        kpi = {k.rotulo: k for k in compras.kpis(e)}
        assert kpi["Investimento em compras"].valor == "—"
        assert kpi["Custo por cabeça"].valor == "—"
        assert kpi["Custo por @ (peso vivo)"].valor == "—"
        vendas_kpi = {k.rotulo: k for k in vendas.kpis(e)}
        assert vendas_kpi["Receita de vendas"].valor == "—"
        assert vendas_kpi["Cabeças vendidas"].valor == "—"  # sem venda: falta, não 0
        assert vendas_kpi["Valor por @ (abates)"].valor == "—"

    def test_primeira_safra_nao_inventa_variacao(self, gestor, season, venda_parcial):
        e = escopo(gestor, season)
        assert all(k.delta is None for k in compras.kpis(e))


# --------------------------------------------------------------------------
# Leituras automáticas
# --------------------------------------------------------------------------


class TestInsights:
    def test_sem_nada_a_dizer_devolve_lista_vazia(self, gestor, season):
        assert insights.gerar(escopo(gestor, season)) == []

    def test_mortalidade_alta_nao_vira_leitura_automatica(
        self, gestor, escritorio, season, lote_gordo, sao_francisco, categoria_25_36
    ):
        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 7, 25),
            quantity=3,
            usuario=escritorio,
            origin_farm=sao_francisco,
            origin_lot=lote_gordo,
            origin_category=categoria_25_36,
            reason="Picada de cobra",
        )
        achados = insights.gerar(
            escopo(gestor, season, hoje=datetime.date(2025, 7, 31))
        )
        assert not any("ortalidade" in a.titulo for a in achados)

    def test_lote_no_prejuizo_e_alerta_e_vem_antes_do_positivo(
        self, gestor, escritorio, season, lote_de_compra, frigorifico, categoria_25_36
    ):
        vender(
            escritorio,
            lote_de_compra,
            frigorifico,
            categoria_25_36,
            head_count=100,
            total_weight_kg=D("48000"),
            carcass_weight_kg=D("24000"),
            total_value=D("100000"),
        )
        achados = insights.gerar(escopo(gestor, season))
        assert achados[0].titulo == "1 lote(s) no prejuízo"
        assert "LT-" in achados[0].texto and achados[0].url.endswith(
            f"/{lote_de_compra.pk}/"
        )

    def test_lucro_aparece_como_positivo(self, gestor, season, venda_parcial):
        achados = insights.gerar(escopo(gestor, season))
        assert "positivo" in [i.nivel for i in achados]
        assert not [i for i in achados if "prejuízo" in i.titulo]

    def test_quem_nao_ve_dinheiro_nao_recebe_leitura_de_dinheiro(
        self, campo_baixao, season, venda_parcial
    ):
        textos = " ".join(
            i.titulo for i in insights.gerar(escopo(campo_baixao, season))
        )
        assert (
            "prejuízo" not in textos
            and "lucro" not in textos
            and "Contas" not in textos
        )

    def test_concentracao_de_vendedor(
        self, gestor, escritorio, season, baixao, categoria_25_36, vendedor
    ):
        from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice

        outro = Partner.objects.create(name="Outro Vendedor")
        PartnerRole.objects.create(partner=outro, role=PartnerRoleChoice.FORNECEDOR)
        for seller, valor in ((vendedor, D("90000")), (outro, D("10000"))):
            c = compras_servico.criar_compra(
                usuario=escritorio,
                date=datetime.date(2025, 7, 10),
                destination_farm=baixao,
                category=categoria_25_36,
                seller=seller,
                head_count=10,
                animal_value=valor,
            )
            compras_servico.confirmar_compra(c, usuario=escritorio)
        titulos = [i.titulo for i in insights.gerar(escopo(gestor, season))]
        assert "Compras concentradas em um vendedor" in titulos


# --------------------------------------------------------------------------
# Carga de demonstração
# --------------------------------------------------------------------------


def test_carga_demo_recusa_producao():
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("seed_demo_bi")
