"""O dashboard e o Início usam o cache de resultados sem nunca servir número
velho nem número de outra pessoa (apps/core/result_cache.py)."""

from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core import result_cache
from apps.dashboards import views
from apps.dashboards.bi.escopo import Escopo
from apps.dashboards.tests.test_desempenho import mais_lotes
from apps.sales.tests.conftest import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def cache_ligado(settings):
    settings.CACHE_DE_RESULTADOS = True
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "r360-dashboard-cache-tests",
        }
    }
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def montagens(monkeypatch):
    """Quantas vezes o dashboard realmente calculou uma aba."""
    contagem = {"n": 0}
    original = views.DashboardView._montar_a_aba

    def contar(self, *args, **kwargs):
        contagem["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(views.DashboardView, "_montar_a_aba", contar)
    return contagem


def abrir(client, aba="rebanho", fragmento=True, **extra):
    cabecalhos = {"HTTP_HX_REQUEST": "true"} if fragmento else {}
    resposta = client.get(
        reverse("dashboards:dashboard_aba", args=[aba]), extra or None, **cabecalhos
    )
    assert resposta.status_code == 200
    return resposta.content.decode()


class TestCacheDaAba:
    def test_segunda_abertura_nao_recalcula_e_traz_o_mesmo_conteudo(
        self, client, gestor, season, montagens
    ):
        client.force_login(gestor)
        primeira = abrir(client)
        segunda = abrir(client)
        assert montagens["n"] == 1
        assert primeira == segunda

    def test_pagina_inteira_aproveita_o_fragmento_guardado(
        self, client, gestor, season, montagens
    ):
        """Troca de aba (fragmento) e carga direta (página) compartilham o cálculo;
        a casca da página continua sendo montada para quem pede."""
        client.force_login(gestor)
        fragmento = abrir(client)
        pagina = abrir(client, fragmento=False)
        assert montagens["n"] == 1
        assert fragmento in pagina
        assert "<html" in pagina and "<html" not in fragmento

    def test_aberta_a_quente_faz_muito_menos_consultas(
        self, client, gestor, season, cenario, lote_de_compra
    ):
        mais_lotes(5, **cenario)
        client.force_login(gestor)
        abrir(client, "lotes")  # a frio
        with CaptureQueriesContext(connection) as quente:
            abrir(client, "lotes")
        result_cache.avancar()
        with CaptureQueriesContext(connection) as frio:
            abrir(client, "lotes")
        assert len(quente) < len(frio) / 3

    def test_escrita_de_negocio_recalcula(
        self,
        client,
        gestor,
        season,
        montagens,
        sao_francisco,
        django_capture_on_commit_callbacks,
    ):
        client.force_login(gestor)
        abrir(client)
        transaction.get_connection().run_on_commit.clear()
        with django_capture_on_commit_callbacks(execute=True):
            sao_francisco.name = "Renomeada"
            sao_francisco.save()
        abrir(client)
        assert montagens["n"] == 2

    def test_cada_usuario_tem_o_seu(
        self, client, gestor, escritorio, season, montagens
    ):
        """A chave inclui quem pede: o que um papel vê (dinheiro, abas) nunca é
        servido a outro."""
        client.force_login(gestor)
        abrir(client)
        client.force_login(escritorio)
        abrir(client)
        assert montagens["n"] == 2

    def test_safra_e_fazenda_diferentes_nao_se_misturam(
        self, client, gestor, season, sao_francisco, montagens
    ):
        client.force_login(gestor)
        abrir(client)
        client.post(
            reverse("properties:trocar_fazenda"),
            {"farm_id": sao_francisco.pk, "next": "/"},
        )
        abrir(client)
        assert montagens["n"] == 2

    def test_outro_dia_recalcula(self, client, gestor, season, montagens, monkeypatch):
        import datetime

        client.force_login(gestor)
        abrir(client)
        amanha = datetime.date.today() + datetime.timedelta(days=1)

        class Amanha(datetime.date):
            @classmethod
            def today(cls):
                return amanha

        monkeypatch.setattr(views, "datetime", SimpleNamespace(date=Amanha))
        abrir(client)
        assert montagens["n"] == 2

    def test_recalcular_agora_refaz_mesmo_sem_mudanca(
        self, client, gestor, season, montagens
    ):
        client.force_login(gestor)
        abrir(client)
        abrir(client, recalcular="1")
        assert montagens["n"] == 2
        abrir(client)  # e o recalculado fica guardado
        assert montagens["n"] == 2

    def test_sem_permissao_continua_403_depois_de_outro_ler(
        self, client, gestor, campo_baixao, season
    ):
        """A checagem de permissão vem antes do cache: ninguém lê o que não pode
        só porque outro leu."""
        client.force_login(gestor)
        assert abrir(client, "vendas")
        client.force_login(campo_baixao)
        resposta = client.get(
            reverse("dashboards:dashboard_aba", args=["vendas"]), HTTP_HX_REQUEST="true"
        )
        assert resposta.status_code == 403

    def test_redis_fora_do_ar_a_aba_abre_normalmente(
        self, client, gestor, season, monkeypatch
    ):
        client.force_login(gestor)
        esperado = abrir(client)

        def quebra(*a, **k):
            raise ConnectionError("Redis fora do ar")

        for metodo in ("get", "set", "add", "incr"):
            monkeypatch.setattr(cache, metodo, quebra)
        assert abrir(client) == esperado


class TestCacheDoInicio:
    def test_cartao_da_safra_guardado_ate_mudar_algo(
        self,
        client,
        gestor,
        season,
        monkeypatch,
        sao_francisco,
        django_capture_on_commit_callbacks,
    ):
        from apps.dashboards import selectors

        chamadas = {"n": 0}
        original = selectors.cartao_da_safra

        def contar(*a, **k):
            chamadas["n"] += 1
            return original(*a, **k)

        monkeypatch.setattr(selectors, "cartao_da_safra", contar)
        client.force_login(gestor)
        url = reverse("dashboards:inicio")
        client.get(url)
        client.get(url)
        assert chamadas["n"] == 1
        transaction.get_connection().run_on_commit.clear()
        with django_capture_on_commit_callbacks(execute=True):
            sao_francisco.name = "Renomeada"
            sao_francisco.save()
        client.get(url)
        assert chamadas["n"] == 2


def test_fim_do_recorte_e_o_mesmo_do_escopo(season, gestor):
    import datetime

    hoje = datetime.date(2025, 9, 1)
    escopo = Escopo.criar(gestor, season=season, hoje=hoje)
    assert escopo.fim == Escopo.fim_do_recorte(season, hoje)
