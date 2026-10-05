"""Lentidão que o usuário sente e a contagem de consultas não mostra: HTML
gigante, canvas fora do limite do navegador, consulta repetida da barra do topo
e redirecionamento da troca de safra (docs/operacao/02-desempenho.md, rodada 2)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.dashboards.bi import specs
from apps.dashboards.bi.specs import Tabela
from apps.sales.tests.conftest import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


class TestTabelaGemeaEAlturaDoGrafico:
    def _grafico(self, **kwargs):
        return specs.cartesiano(
            "g", "Gráfico", ["a", "b"], [specs.serie("s", [1, 2])], **kwargs
        )

    def test_tabela_atribuida_depois_tambem_tem_teto(self):
        """A curva de peso monta a tabela depois de criar o gráfico: sem o teto,
        eram 2.458 linhas escondidas (828 KB) numa aba de 1,1 MB."""
        g = self._grafico()
        linhas = [[str(i), "1"] for i in range(specs.LIMITE_DA_TABELA_GEMEA + 50)]

        g.com_tabela(Tabela(["Lote", "Valor"], linhas))

        assert g.tabela.limite == specs.LIMITE_DA_TABELA_GEMEA
        assert len(g.tabela.linhas_prontas) == specs.LIMITE_DA_TABELA_GEMEA
        assert g.tabela.omitidas == 50

    def test_limite_explicito_de_uma_tabela_e_respeitado(self):
        g = self._grafico()
        g.com_tabela(Tabela(["A"], [["1"], ["2"], ["3"]], limite=2))
        assert g.tabela.limite == 2

    def test_altura_nunca_passa_do_teto(self):
        """17.000 px passa do limite de canvas dos navegadores: o card saía em
        branco com 585 lotes."""
        g = self._grafico(altura=17_000)
        assert g.altura == specs.ALTURA_MAXIMA_DO_GRAFICO
        assert g.para_json()["altura"] == specs.ALTURA_MAXIMA_DO_GRAFICO

    def test_altura_pequena_nao_muda(self):
        assert self._grafico(altura=240).altura == 240


class TestTrocaDeSafraEFazenda:
    @pytest.mark.parametrize(
        "destino",
        [
            "https://outro-site.com/",
            "//outro-site.com/",
            "javascript:alert(1)",
            "\\\\outro-site.com",
        ],
    )
    def test_destino_de_outro_site_volta_para_o_inicio(
        self, client, gestor, season, destino
    ):
        client.force_login(gestor)
        for url, campo in (
            (reverse("organizations:trocar_safra"), {"season_id": season.pk}),
            (reverse("properties:trocar_fazenda"), {"farm_id": ""}),
        ):
            resposta = client.post(url, {**campo, "next": destino})
            assert resposta.status_code == 302
            assert resposta["Location"] == reverse("dashboards:inicio")

    def test_destino_da_propria_aplicacao_mantem_aba_e_filtros(
        self, client, gestor, season
    ):
        client.force_login(gestor)
        alvo = reverse("dashboards:dashboard_aba", args=["lotes"]) + "?pagina=2"

        resposta = client.post(
            reverse("organizations:trocar_safra"),
            {"season_id": season.pk, "next": alvo},
        )

        assert resposta["Location"] == alvo

    def test_barra_do_topo_aponta_para_a_pagina_atual_com_filtros(
        self, client, gestor, season
    ):
        client.force_login(gestor)
        resposta = client.get(
            reverse("dashboards:dashboard_aba", args=["lotes"]) + "?x=1"
        )
        html = resposta.content.decode()
        assert 'name="next" value="/dashboard/lotes/?x=1"' in html


class TestContextoDoTopoUmaVezPorRequisicao:
    def _consultas_a(self, capturadas, tabela):
        return [q for q in capturadas if f'FROM "{tabela}"' in q["sql"]]

    @pytest.mark.parametrize("rota", ["inicio", "dashboard"])
    def test_empresa_e_safra_sao_consultadas_uma_vez(
        self, client, gestor, season, rota
    ):
        """A barra do topo, a view e o `Escopo` pedem a mesma empresa e safra:
        eram de 3 a 6 consultas repetidas em toda tela."""
        client.force_login(gestor)
        client.get(reverse(f"dashboards:{rota}"))  # aquece sessão e tipos

        with CaptureQueriesContext(connection) as capturadas:
            assert client.get(reverse(f"dashboards:{rota}")).status_code == 200

        empresas = self._consultas_a(capturadas, "organizations_company")
        assert len(empresas) == 1, [q["sql"] for q in empresas]

    def test_fragmento_do_htmx_nao_paga_a_barra_do_topo(self, client, gestor, season):
        """Troca de aba e polling renderizam sem a barra do topo: nem a lista de
        safras nem a de fazendas é consultada para montá-la."""
        client.force_login(gestor)
        url = reverse("dashboards:dashboard_aba", args=["rebanho"])
        client.get(url, HTTP_HX_REQUEST="true")

        with CaptureQueriesContext(connection) as capturadas:
            client.get(url, HTTP_HX_REQUEST="true")

        # A lista de safras só existiria para desenhar o seletor do topo.
        assert not [
            q
            for q in self._consultas_a(capturadas, "organizations_season")
            if "ORDER BY" in q["sql"] and "LIMIT" not in q["sql"]
        ]

    def test_fora_de_requisicao_nao_guarda_nada(self, company, season):
        """Tarefa Celery e comando não têm requisição onde guardar: cada chamada
        consulta de novo, sem risco de valor velho."""
        from apps.core import context as ctx

        antes = ctx.current_company()
        company.name = "Outro nome"
        company.save()
        assert ctx.current_company().name == "Outro nome"
        assert antes is not ctx.current_company()
