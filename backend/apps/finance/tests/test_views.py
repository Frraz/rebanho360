"""As telas do financeiro: permissão, escopo (404), CSRF, dado bancário e o
fluxo programar → aprovar → baixar."""

from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import AuditEvent
from apps.core.reversible import Status
from apps.finance import services
from apps.finance.models import Invoice, Payment, PaymentStatus
from apps.finance.tests.conftest import AMANHA, HOJE, baixa, programado

pytestmark = pytest.mark.django_db

D = Decimal


class TestPermissaoEEscopo:
    def test_campo_nao_ve_o_financeiro(self, client, campo_baixao, titulo):
        client.force_login(campo_baixao)

        assert client.get(reverse("finance:contas_a_pagar")).status_code == 403
        assert (
            client.get(reverse("finance:titulo_detalhe", args=[titulo.pk])).status_code
            == 403
        )

    def test_anonimo_vai_para_o_login(self, client, titulo):
        resposta = client.get(reverse("finance:contas_a_pagar"))

        assert resposta.status_code == 302 and "/entrar/" in resposta["Location"]

    @pytest.mark.parametrize("papel", ["escritorio", "gestor", "consulta"])
    def test_papeis_que_veem_a_lista(self, client, request, papel, titulo):
        client.force_login(request.getfixturevalue(papel))

        resposta = client.get(reverse("finance:contas_a_pagar"))

        assert resposta.status_code == 200
        assert titulo.code in resposta.content.decode()

    def test_titulo_de_fazenda_fora_do_escopo_devolve_404_nao_403(
        self, client, titulo, baixao
    ):
        from apps.accounts.models import UserFarmAccess

        outro = User.objects.create_user(
            username="so_baixao", password="x", role=Role.FINANCEIRO
        )
        UserFarmAccess.objects.create(user=outro, farm=baixao, can_write=True)
        client.force_login(outro)

        assert (
            client.get(reverse("finance:titulo_detalhe", args=[titulo.pk])).status_code
            == 404
        )
        lista = client.get(reverse("finance:contas_a_pagar"))
        assert titulo.code not in lista.content.decode()
        assert (
            client.get(reverse("finance:titulo_baixar", args=[titulo.pk])).status_code
            == 404
        )

    def test_post_sem_csrf_e_recusado(self, titulo_aprovado, financeiro):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(financeiro)

        resposta = cliente.post(
            reverse("finance:titulo_baixar", args=[titulo_aprovado.pk]),
            {"date": HOJE.isoformat(), "amount": "1", "method": "PIX", "document": "X"},
        )

        assert resposta.status_code == 403
        assert Payment.objects.count() == 0

    def test_gestor_nao_ve_a_acao_de_baixa_e_a_tela_recusa(
        self, client, titulo_aprovado, gestor
    ):
        client.force_login(gestor)

        detalhe = client.get(
            reverse("finance:titulo_detalhe", args=[titulo_aprovado.pk])
        )
        assert reverse("finance:titulo_baixar", args=[titulo_aprovado.pk]) not in (
            detalhe.content.decode()
        )
        resposta = client.post(
            reverse("finance:titulo_baixar", args=[titulo_aprovado.pk]),
            {
                "date": HOJE.isoformat(),
                "amount": "100",
                "method": "PIX",
                "document": "D1",
            },
        )
        assert Payment.objects.count() == 0
        assert "permissão para dar baixa" in resposta.content.decode()


class TestDadoBancario:
    def test_escritorio_nao_ve_o_numero_da_conta(
        self, client, escritorio, titulo, conta_do_vendedor
    ):
        client.force_login(escritorio)

        html = client.get(
            reverse("finance:titulo_detalhe", args=[titulo.pk])
        ).content.decode()

        assert conta_do_vendedor.account not in html
        assert conta_do_vendedor.pix_key not in html or not conta_do_vendedor.pix_key

    def test_financeiro_ve_e_a_consulta_fica_na_auditoria(
        self, client, financeiro, titulo, conta_do_vendedor
    ):
        client.force_login(financeiro)

        html = client.get(
            reverse("finance:titulo_detalhe", args=[titulo.pk])
        ).content.decode()
        client.get(reverse("finance:titulo_detalhe", args=[titulo.pk]))

        assert conta_do_vendedor.account in html
        eventos = AuditEvent.objects.filter(
            action="VIEW", entity_type="BankAccount", actor=financeiro
        )
        assert eventos.count() == 1  # uma por pessoa, título e dia
        assert titulo.code in eventos.get().reason
        # Nenhum dado bancário vai para a auditoria, só o fato da consulta.
        assert conta_do_vendedor.account not in eventos.get().reason

    def test_select_de_contas_mostra_so_o_final_da_conta(
        self, client, financeiro, vendedor, conta_do_vendedor
    ):
        client.force_login(financeiro)

        html = client.get(
            reverse("finance:contas_do_favorecido"), {"payee": vendedor.pk}
        ).content.decode()

        assert "Banco do Brasil" in html
        assert conta_do_vendedor.account not in html  # mascarada
        assert "•" in html and "5-4" in html


class TestFluxoPelaTela:
    def test_programar_aprovar_e_baixar_pelas_telas(
        self, client, escritorio, gestor, financeiro, titulo
    ):
        # 1. escritório programa
        client.force_login(escritorio)
        resposta = client.post(
            reverse("finance:titulo_programar", args=[titulo.pk]),
            {"scheduled_date": AMANHA.isoformat()},
            follow=True,
        )
        assert "programado para" in resposta.content.decode()
        # 2. gestor aprova
        client.force_login(gestor)
        resposta = client.post(
            reverse("finance:titulo_aprovar", args=[titulo.pk]), follow=True
        )
        assert "aprovado" in resposta.content.decode()
        # 3. financeiro paga
        client.force_login(financeiro)
        resposta = client.post(
            reverse("finance:titulo_baixar", args=[titulo.pk]),
            {
                "date": HOJE.isoformat(),
                "amount": "388080.00",
                "method": "PIX",
                "document": "E2E-9",
            },
            follow=True,
        )

        titulo.refresh_from_db()
        assert titulo.payment_status == PaymentStatus.PAGO
        assert "PG-2025/26-0001 registrado" in resposta.content.decode()
        assert "quitado" in resposta.content.decode()

    def test_clique_duplo_na_tela_nao_paga_duas_vezes(
        self, client, titulo_aprovado, financeiro
    ):
        client.force_login(financeiro)
        dados = {
            "date": HOJE.isoformat(),
            "amount": "1000.00",
            "method": "PIX",
            "document": "CLIQUE-DUPLO",
        }
        url = reverse("finance:titulo_baixar", args=[titulo_aprovado.pk])

        client.post(url, dados)
        segunda = client.post(url, dados)

        assert Payment.objects.count() == 1
        assert "Já existe uma baixa" in segunda.content.decode()

    def test_pagar_sem_aprovacao_pela_tela_e_recusado(self, client, titulo, financeiro):
        client.force_login(financeiro)

        resposta = client.post(
            reverse("finance:titulo_baixar", args=[titulo.pk]),
            {"date": HOJE.isoformat(), "amount": "1", "method": "PIX", "document": "X"},
        )

        assert Payment.objects.count() == 0
        assert "depois da aprovação" in resposta.content.decode()

    def test_quem_aprova_nao_paga_na_tela(
        self, client, titulo, escritorio, admin_fin, financeiro
    ):
        programado(titulo, escritorio)
        services.aprovar_titulo(titulo, usuario=admin_fin)
        client.force_login(admin_fin)

        resposta = client.post(
            reverse("finance:titulo_baixar", args=[titulo.pk]),
            {"date": HOJE.isoformat(), "amount": "1", "method": "PIX", "document": "X"},
        )

        assert "Quem aprova não é quem paga" in resposta.content.decode()
        assert Payment.objects.count() == 0


class TestBloqueioComLink:
    """F4-05: a mensagem diz o caminho, e o link leva direto ao pagamento."""

    def test_excluir_compra_paga_mostra_o_bloqueio_com_link_para_o_pagamento(
        self, client, compra, titulo_aprovado, financeiro, gestor
    ):
        pagamento = baixa(titulo_aprovado, financeiro)
        client.force_login(gestor)

        html = client.get(
            reverse("purchases:excluir", args=[compra.pk])
        ).content.decode()

        assert "Não é possível excluir agora" in html
        assert "desfaça antes a baixa do pagamento" in html
        assert reverse("finance:pagamento_detalhe", args=[pagamento.pk]) in html
        assert "Ir para o pagamento" in html
        # Sem botão de excluir enquanto bloqueado.
        assert 'name="motivo"' not in html

    def test_desfazer_baixa_pela_tela_com_impacto_e_motivo(
        self, client, titulo_aprovado, financeiro
    ):
        pagamento = baixa(titulo_aprovado, financeiro)
        client.force_login(financeiro)
        url = reverse("finance:pagamento_desfazer", args=[pagamento.pk])

        html = client.get(url).content.decode()
        assert "Isto vai desfazer" in html
        assert "não desfaz a transferência no banco" in html

        sem_motivo = client.post(url, {"motivo": ""})
        assert "Motivo é obrigatório" in sem_motivo.content.decode()
        pagamento.refresh_from_db()
        assert pagamento.status == Status.CONFIRMADA

        client.post(url, {"motivo": "TED devolvida pelo banco"})
        pagamento.refresh_from_db()
        titulo_aprovado.refresh_from_db()
        assert pagamento.status == Status.EXCLUIDA
        assert titulo_aprovado.payment_status == PaymentStatus.APROVADO

    def test_gestor_nao_desfaz_baixa_nem_pela_tela(
        self, client, titulo_aprovado, financeiro, gestor
    ):
        pagamento = baixa(titulo_aprovado, financeiro)
        client.force_login(gestor)

        client.post(
            reverse("finance:pagamento_desfazer", args=[pagamento.pk]),
            {"motivo": "tentando"},
        )

        pagamento.refresh_from_db()
        assert pagamento.status == Status.CONFIRMADA


class TestTelasRenderizam:
    def test_todas_as_telas_do_fluxo(
        self, client, financeiro, titulo_aprovado, titulo_a_receber
    ):
        pagamento = baixa(titulo_aprovado, financeiro, valor=D("100"))
        client.force_login(financeiro)

        urls = [
            reverse("finance:contas_a_pagar"),
            reverse("finance:contas_a_pagar") + "?situacao=todos",
            reverse("finance:contas_a_pagar") + "?situacao=vencidos",
            reverse("finance:contas_a_receber"),
            reverse("finance:pagamento_lista"),
            reverse("finance:pagamento_lista") + "?desfeitos=1&direcao=PAGAR",
            reverse("finance:pagamento_detalhe", args=[pagamento.pk]),
            reverse("finance:titulo_detalhe", args=[titulo_aprovado.pk]),
            reverse("finance:titulo_detalhe", args=[titulo_a_receber.pk]),
            reverse("finance:titulo_baixar", args=[titulo_aprovado.pk]),
            reverse("finance:titulo_baixar", args=[titulo_a_receber.pk]),
            reverse("finance:titulo_editar", args=[titulo_aprovado.pk]),
            reverse("finance:titulo_novo"),
            reverse("finance:sem_titulo"),
            reverse("finance:pagamento_desfazer", args=[pagamento.pk]),
        ]
        for url in urls:
            resposta = client.get(url)
            assert resposta.status_code == 200, url

    def test_telas_de_programar_aprovar_e_devolver(
        self, client, financeiro, gestor, titulo, escritorio
    ):
        client.force_login(escritorio)
        assert (
            client.get(
                reverse("finance:titulo_programar", args=[titulo.pk])
            ).status_code
            == 200
        )
        programado(titulo, escritorio)
        client.force_login(gestor)
        html = client.get(
            reverse("finance:titulo_aprovar", args=[titulo.pk])
        ).content.decode()
        assert "Aprovar pagamento" in html
        client.force_login(escritorio)
        assert (
            client.get(reverse("finance:titulo_devolver", args=[titulo.pk])).status_code
            == 200
        )

    def test_novo_titulo_a_partir_da_compra_vem_preenchido(
        self, client, financeiro, compra
    ):
        client.force_login(financeiro)

        html = client.get(
            reverse("finance:titulo_novo") + f"?compra={compra.pk}"
        ).content.decode()

        assert f'value="{compra.pk}"' in html  # origem oculta
        assert "Fazenda Boa Vista" in html  # favorecido pré-selecionado

    def test_lancar_titulo_avulso_pela_tela(
        self, client, financeiro, sao_francisco, vendedor
    ):
        client.force_login(financeiro)

        resposta = client.post(
            reverse("finance:titulo_novo"),
            {
                "direction": "PAGAR",
                "component": "OUTRO",
                "farm": sao_francisco.pk,
                "payee": vendedor.pk,
                "issue_date": "2025-09-01",
                "due_date": "2025-09-30",
                "amount": "750.00",
            },
            follow=True,
        )

        assert Invoice.objects.get().amount == D("750.00")
        assert "lançado" in resposta.content.decode()

    def test_detalhe_da_compra_mostra_o_bloco_financeiro(
        self, client, financeiro, compra, titulo
    ):
        client.force_login(financeiro)

        html = client.get(
            reverse("purchases:detalhe", args=[compra.pk])
        ).content.decode()

        assert 'id="titulo-financeiro"' in html
        assert titulo.code in html

    def test_campo_nao_ve_o_bloco_financeiro_da_compra(
        self, client, campo_baixao, compra
    ):
        # CAMPO não vê compra (escopo), mas o bloco nunca vaza para quem não vê o financeiro.
        from apps.purchases.views import _contexto_financeiro

        assert _contexto_financeiro(compra, campo_baixao) == {"ver_financeiro": False}

    def test_cancelar_titulo_pela_tela_com_impacto(self, client, gestor, titulo):
        client.force_login(gestor)
        url = reverse("finance:titulo_excluir", args=[titulo.pk])

        html = client.get(url).content.decode()
        assert "Cancelar título" in html and "Isto vai desfazer" in html

        client.post(url, {"motivo": "Pago em dinheiro, fora do sistema"})
        titulo.refresh_from_db()
        assert titulo.status == Status.EXCLUIDA

    def test_operacoes_sem_titulo_e_gerar_pela_tela(
        self, client, financeiro, escritorio, dados_compra
    ):
        from apps.purchases import services as compras

        compra = compras.criar_compra(usuario=escritorio, **dados_compra)
        compras.confirmar_compra(compra, usuario=escritorio, gerar_titulos=False)
        client.force_login(financeiro)

        html = client.get(reverse("finance:sem_titulo")).content.decode()
        assert compra.code in html
        client.post(reverse("finance:sem_titulo"), {"operacao": f"compra:{compra.pk}"})

        assert compra.invoices.count() == 1
