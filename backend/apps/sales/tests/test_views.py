"""F3-01/03/04 — as telas de venda: permissão, escopo, CSRF e o fluxo."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.reversible import Status
from apps.herd import services as herd
from apps.herd.models import HerdMovement
from apps.sales.models import Sale

pytestmark = pytest.mark.django_db


def _post(dados_abate, **extra):
    dados = {
        "type": "ABATE",
        "date": "2025-08-03",
        "buyer": dados_abate["buyer"].pk,
        "farm": dados_abate["farm"].pk,
        "lot": dados_abate["lot"].pk,
        "category": dados_abate["category"].pk,
        "head_count": "84",
        "total_weight_kg": "43540",
        "carcass_weight_kg": "22350.40",
        "total_value": "401502.68",
        "sale_form": "PASTO",
        "acao": "confirmar",
        **extra,
    }
    return {k: v for k, v in dados.items() if v is not None}


class TestFluxo:
    def test_lancar_e_confirmar_pela_tela(self, client, escritorio, dados_abate):
        client.force_login(escritorio)

        resposta = client.post(reverse("sales:nova"), _post(dados_abate), follow=True)

        venda = Sale.objects.get()
        assert venda.status == Status.CONFIRMADA
        assert resposta.redirect_chain[-1][0] == reverse(
            "sales:detalhe", args=[venda.pk]
        )
        texto = resposta.content.decode()
        assert (
            "Venda VD-2025/26-0001 confirmada. 84 cabeças saíram do lote LT-SFR-010"
            in texto
        )
        # O detalhe mostra os seis indicadores calculados pelo serviço.
        assert "518,3" in texto and "51,33%" in texto and "269,46" in texto

    def test_salvar_rascunho_nao_mexe_no_rebanho(
        self, client, escritorio, dados_abate, lote_gordo
    ):
        client.force_login(escritorio)
        client.post(reverse("sales:nova"), _post(dados_abate, acao="rascunho"))

        assert Sale.objects.get().status == Status.RASCUNHO
        assert herd.saldo(lot=lote_gordo)["head_count"] == 100

    def test_erro_de_saldo_e_especifico_e_a_tela_volta_preenchida(
        self, client, escritorio, dados_abate
    ):
        client.force_login(escritorio)
        resposta = client.post(
            reverse("sales:nova"), _post(dados_abate, head_count="120")
        )

        texto = resposta.content.decode()
        assert resposta.status_code == 200
        assert "Saldo insuficiente: há 100 cabeças de Machos 25 a 36 meses" in texto
        assert 'value="120"' in texto  # não perdeu o que foi digitado
        assert Sale.objects.get().status == Status.RASCUNHO

    def test_previa_vem_do_servico(self, client, escritorio):
        client.force_login(escritorio)
        resposta = client.get(
            reverse("sales:previa"),
            {
                "head_count": "84",
                "total_weight_kg": "43540",
                "carcass_weight_kg": "22350.40",
                "total_value": "401502.68",
            },
        )
        texto = resposta.content.decode()
        assert "51,33%" in texto and "R$ 269,46" in texto and "R$ 4.779,79" in texto

    def test_previa_sem_carcaca_mostra_travessao_nao_zero(self, client, escritorio):
        client.force_login(escritorio)
        texto = client.get(
            reverse("sales:previa"),
            {
                "head_count": "84",
                "total_weight_kg": "43540",
                "total_value": "401502.68",
            },
        ).content.decode()
        assert "Rendimento" in texto and "—" in texto
        assert "0,00%" not in texto and "R$ 0,00" not in texto

    def test_corrigir_pela_tela_exige_motivo(
        self, client, escritorio, dados_abate, criar, confirmar
    ):
        venda = confirmar(criar(**dados_abate))
        client.force_login(escritorio)
        url = reverse("sales:editar", args=[venda.pk])

        sem_motivo = client.post(url, _post(dados_abate, head_count="80"))
        assert "Informe o motivo da correção" in sem_motivo.content.decode()

        client.post(url, _post(dados_abate, head_count="80", edit_reason="Contagem"))
        venda.refresh_from_db()
        assert venda.head_count == 80 and venda.version == 2

    def test_excluir_mostra_impacto_e_exclui_com_motivo(
        self, client, gestor, dados_abate, criar, confirmar
    ):
        venda = confirmar(criar(**{**dados_abate, "head_count": 100}))
        client.force_login(gestor)
        url = reverse("sales:excluir", args=[venda.pk])

        tela = client.get(url).content.decode()
        assert "Isto vai desfazer" in tela and "saída de 100 cabeças" in tela
        assert "volta a ficar aberto" in tela

        client.post(url, {"motivo": "Lançada em duplicidade"})
        venda.refresh_from_db()
        assert venda.status == Status.EXCLUIDA

    def test_movimento_gerado_pela_venda_nao_se_edita_direto(
        self, client, gestor, dados_abate, criar, confirmar
    ):
        venda = confirmar(criar(**dados_abate))
        movimento = HerdMovement.objects.get(origin_sale=venda)
        client.force_login(gestor)

        resposta = client.get(reverse("herd:movimento_editar", args=[movimento.pk]))
        assert resposta.status_code == 302
        assert resposta.url == reverse("sales:detalhe", args=[venda.pk])

        resposta = client.post(
            reverse("herd:movimento_excluir", args=[movimento.pk]), {"motivo": "x"}
        )
        assert resposta.status_code == 302
        movimento.refresh_from_db()
        assert movimento.status == Status.CONFIRMADA


class TestSeguranca:
    def test_sem_login_vai_para_o_login(self, client, dados_abate, criar):
        venda = criar(**dados_abate)
        for nome, args in (
            ("sales:lista", []),
            ("sales:nova", []),
            ("sales:detalhe", [venda.pk]),
            ("sales:editar", [venda.pk]),
            ("sales:excluir", [venda.pk]),
        ):
            resposta = client.get(reverse(nome, args=args))
            assert resposta.status_code == 302
            assert resposta.url.startswith(reverse("accounts:login"))

    def test_campo_nao_lanca_venda_403(self, client, campo_baixao):
        client.force_login(campo_baixao)
        assert client.get(reverse("sales:nova")).status_code == 403
        assert client.post(reverse("sales:nova"), {}).status_code == 403

    def test_fora_do_escopo_da_fazenda_da_404_nao_403(
        self, client, dados_abate, criar, campo_baixao
    ):
        """ADR 0003: 403 confirmaria que a venda existe."""
        venda = criar(**dados_abate)  # venda de São Francisco
        client.force_login(campo_baixao)  # só tem acesso ao Baixão
        for nome in ("detalhe", "editar", "excluir", "confirmar"):
            assert (
                client.get(reverse(f"sales:{nome}", args=[venda.pk])).status_code == 404
            )
        assert (
            client.post(reverse("sales:restaurar", args=[venda.pk])).status_code == 404
        )

    def test_lista_so_mostra_vendas_do_escopo(
        self, client, dados_abate, criar, campo_baixao
    ):
        criar(**dados_abate)
        client.force_login(campo_baixao)
        resposta = client.get(reverse("sales:lista"))
        assert resposta.status_code == 200
        assert "VD-2025/26-0001" not in resposta.content.decode()

    def test_post_sem_csrf_e_recusado(self, escritorio, dados_abate):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(escritorio)
        assert (
            cliente.post(reverse("sales:nova"), _post(dados_abate)).status_code == 403
        )
        assert not Sale.objects.exists()

    def test_escritorio_nao_exclui_confirmada_pela_tela(
        self, client, escritorio, dados_abate, criar, confirmar
    ):
        venda = confirmar(criar(**dados_abate))
        client.force_login(escritorio)
        client.post(reverse("sales:excluir", args=[venda.pk]), {"motivo": "x"})
        venda.refresh_from_db()
        assert venda.status == Status.CONFIRMADA
