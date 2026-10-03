"""Solicitação de acesso: tela pública, aviso aos administradores, aprovação."""

import re

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse

from apps.accounts import access_requests as pedidos
from apps.accounts.models import AccessRequest, AccessRequestStatus, Role, User
from apps.audit.models import AuditAction, AuditEvent
from apps.core.exceptions import BusinessError

pytestmark = pytest.mark.django_db

PEDIDO = {
    "full_name": "Carlos Pereira",
    "email": "carlos@exemplo.com",
    "phone": "(63) 99999-0000",
    "message": "Sou encarregado da Fazenda Santa Rita e vou lançar as pesagens.",
    "website": "",
}


def _enviar(client, **extra):
    return client.post(reverse("accounts:solicitar_acesso"), {**PEDIDO, **extra})


@pytest.fixture
def pedido(db):
    return AccessRequest.objects.create(
        full_name="Carlos Pereira",
        email="carlos@exemplo.com",
        message="Preciso de acesso.",
    )


class TestTelaPublica:
    def test_aparece_no_login_e_abre_sem_estar_logado(self, client):
        assert (
            reverse("accounts:solicitar_acesso")
            in client.get(reverse("accounts:login")).content.decode()
        )
        resposta = client.get(reverse("accounts:solicitar_acesso"))
        assert resposta.status_code == 200
        assert "Solicitar acesso" in resposta.content.decode()

    def test_logado_vai_para_o_inicio(self, cliente_admin):
        assert (
            cliente_admin.get(reverse("accounts:solicitar_acesso")).status_code == 302
        )

    def test_pedido_vira_registro_pendente_com_auditoria(self, client):
        resposta = _enviar(client)
        assert resposta.status_code == 302
        assert resposta["Location"] == reverse("accounts:solicitar_acesso_enviado")
        pedido = AccessRequest.objects.get()
        assert pedido.status == AccessRequestStatus.PENDENTE
        assert pedido.email == "carlos@exemplo.com"
        assert AuditEvent.objects.filter(
            entity_type="AccessRequest",
            entity_id=str(pedido.pk),
            action=AuditAction.CREATE,
            actor=None,
        ).exists()

    def test_admins_recebem_o_aviso_com_o_link_da_tela(
        self, client, admin, outro_admin, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _enviar(client)
        (mensagem,) = mailoutbox
        assert sorted(mensagem.to) == ["admin1@fazenda.com.br", "admin2@fazenda.com.br"]
        assert "Carlos Pereira" in mensagem.subject
        assert "carlos@exemplo.com" in mensagem.body
        assert "/contas/solicitacoes/" in mensagem.body
        assert "não foi confirmado" in mensagem.body

    def test_avisa_administradores_e_gestores_mas_nao_inativo_nem_outros_papeis(
        self, client, admin, mailoutbox, django_capture_on_commit_callbacks
    ):
        User.objects.create_user(
            username="g", password="s", role=Role.GESTOR, email="g@x.com"
        )
        User.objects.create_user(
            username="esc", password="s", role=Role.ESCRITORIO, email="esc@x.com"
        )
        User.objects.create_user(
            username="velho",
            password="s",
            role=Role.ADMIN,
            email="velho@x.com",
            is_active=False,
        )
        with django_capture_on_commit_callbacks(execute=True):
            _enviar(client)
        assert sorted(mailoutbox[0].to) == ["admin1@fazenda.com.br", "g@x.com"]

    def test_emails_extras_das_settings_tambem_recebem(
        self, client, settings, mailoutbox, django_capture_on_commit_callbacks
    ):
        settings.ACCESS_REQUEST_NOTIFY_EMAILS = ["dono@fazenda.com.br"]
        with django_capture_on_commit_callbacks(execute=True):
            _enviar(client)
        assert mailoutbox[0].to == ["dono@fazenda.com.br"]

    def test_sem_destinatario_o_pedido_fica_na_tela_mesmo_assim(
        self, client, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _enviar(client)
        assert AccessRequest.objects.count() == 1 and mailoutbox == []

    def test_resposta_e_igual_para_quem_ja_tem_conta(self, client, admin):
        User.objects.create_user(
            username="carlos", password="s", email="CARLOS@exemplo.com"
        )
        resposta = _enviar(client)
        assert resposta.status_code == 302
        assert resposta["Location"] == reverse("accounts:solicitar_acesso_enviado")
        assert not AccessRequest.objects.exists()

    def test_pedido_repetido_nao_entra_na_fila_duas_vezes(self, client, admin):
        _enviar(client)
        resposta = _enviar(client, email="CARLOS@exemplo.com")
        assert resposta["Location"] == reverse("accounts:solicitar_acesso_enviado")
        assert AccessRequest.objects.count() == 1

    def test_quem_foi_recusado_pode_pedir_de_novo(self, client, admin, pedido):
        pedidos.recusar_solicitacao(
            pedido, ator=admin, motivo="Não conheço", avisar=False
        )
        _enviar(client)
        assert AccessRequest.objects.count() == 2

    def test_isca_de_robo_responde_sucesso_e_nao_grava(self, client):
        resposta = _enviar(client, website="http://spam.example")
        assert resposta.status_code == 302
        assert not AccessRequest.objects.exists()

    def test_limite_por_ip(self, client):
        for n in range(pedidos.LIMITE_POR_IP):
            assert _enviar(client, email=f"p{n}@exemplo.com").status_code == 302
        resposta = _enviar(client, email="outro@exemplo.com")
        assert resposta.status_code == 429
        assert "Muitas solicitações" in resposta.content.decode()
        assert AccessRequest.objects.count() == pedidos.LIMITE_POR_IP

    def test_teto_de_avisos_protege_a_caixa_dos_admins(
        self, client, admin, mailoutbox, django_capture_on_commit_callbacks, monkeypatch
    ):
        monkeypatch.setattr(pedidos, "TETO_DE_AVISOS_POR_HORA", 2)
        monkeypatch.setattr(pedidos, "LIMITE_POR_IP", 99)
        with django_capture_on_commit_callbacks(execute=True):
            for n in range(4):
                _enviar(client, email=f"p{n}@exemplo.com")
        assert AccessRequest.objects.count() == 4  # todos na tela
        assert len(mailoutbox) == 2  # só dois e-mails

    @pytest.mark.parametrize(
        "campo,valor",
        [
            ("full_name", "Carlos"),
            ("email", "isso-nao-e-email"),
            ("message", "oi"),
            ("phone", "abc<script>"),
        ],
    )
    def test_dados_invalidos_nao_gravam(self, client, campo, valor):
        resposta = _enviar(client, **{campo: valor})
        assert resposta.status_code == 200
        assert not AccessRequest.objects.exists()

    def test_nome_com_quebra_de_linha_nao_injeta_cabecalho(
        self, client, admin, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _enviar(client, full_name="Carlos\r\nBcc: alguem@mal.com Pereira")
        assert "\n" not in mailoutbox[0].subject and "\r" not in mailoutbox[0].subject
        assert mailoutbox[0].bcc == []

    def test_post_sem_csrf_e_recusado(self, admin):
        from django.test import Client

        resposta = Client(enforce_csrf_checks=True).post(
            reverse("accounts:solicitar_acesso"), PEDIDO
        )
        assert resposta.status_code == 403


class TestListaEDecisao:
    def test_pendencia_aparece_na_aba_e_no_menu(self, cliente_admin, pedido):
        html = cliente_admin.get(reverse("accounts:usuarios")).content.decode()
        assert "1 pendente" in html
        assert (
            "Carlos Pereira"
            in cliente_admin.get(reverse("accounts:solicitacoes")).content.decode()
        )

    def test_so_admin_e_gestor_decidem(self, client, pedido):
        """Cliente, 2026-10-03 (#41): aprovam novos acessos ADMIN e GESTOR."""
        for papel in (Role.ESCRITORIO, Role.CAMPO, Role.FINANCEIRO, Role.CONSULTA):
            usuario = User.objects.create_user(
                username=f"u-{papel}", password="s", role=papel
            )
            client.force_login(usuario)
            assert (
                client.get(
                    reverse("accounts:solicitacao_aprovar", args=[pedido.pk])
                ).status_code
                == 403
            )
            assert (
                client.post(
                    reverse("accounts:solicitacao_recusar", args=[pedido.pk]),
                    {"motivo": "x"},
                ).status_code
                == 403
            )
        pedido.refresh_from_db()
        assert pedido.status == AccessRequestStatus.PENDENTE

    def test_gestor_aprova_o_pedido_e_fica_registrado(self, client, fazenda_a, pedido):
        gestor = User.objects.create_user(
            username="g", password="s", role=Role.GESTOR, email="g@x.com"
        )
        client.force_login(gestor)
        resposta = client.post(
            reverse("accounts:solicitacao_aprovar", args=[pedido.pk]),
            {
                "username": "carlos",
                "first_name": "Carlos",
                "role": Role.CAMPO,
                f"farm_{fazenda_a.pk}": "lancar",
            },
        )
        assert resposta.status_code == 302
        pedido.refresh_from_db()
        assert pedido.status == AccessRequestStatus.APROVADA
        assert pedido.decided_by == gestor
        assert User.objects.get(username="carlos").role == Role.CAMPO

    def test_gestor_nao_concede_o_papel_de_administrador(self, client, pedido):
        gestor = User.objects.create_user(
            username="g", password="s", role=Role.GESTOR, email="g@x.com"
        )
        client.force_login(gestor)
        resposta = client.post(
            reverse("accounts:solicitacao_aprovar", args=[pedido.pk]),
            {"username": "carlos", "first_name": "Carlos", "role": Role.ADMIN},
        )
        assert resposta.status_code in (200, 403)
        assert not User.objects.filter(username="carlos").exists()
        pedido.refresh_from_db()
        assert pedido.status == AccessRequestStatus.PENDENTE

    def test_gestor_nao_ve_a_lista_de_usuarios(self, client):
        gestor = User.objects.create_user(
            username="g", password="s", role=Role.GESTOR, email="g@x.com"
        )
        client.force_login(gestor)
        assert client.get(reverse("accounts:usuarios")).status_code == 403
        assert client.get(reverse("accounts:solicitacoes")).status_code == 200

    def test_aprovar_cria_a_conta_e_envia_a_confirmacao(
        self,
        cliente_admin,
        admin,
        fazenda_a,
        pedido,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            resposta = cliente_admin.post(
                reverse("accounts:solicitacao_aprovar", args=[pedido.pk]),
                {
                    "username": "carlos",
                    "first_name": "Carlos",
                    "last_name": "Pereira",
                    "phone": "",
                    "role": Role.CAMPO,
                    f"farm_{fazenda_a.pk}": "lancar",
                },
            )
        usuario = User.objects.get(username="carlos")
        assert resposta.status_code == 302
        assert usuario.email == "carlos@exemplo.com" and usuario.role == Role.CAMPO
        assert not usuario.has_usable_password()
        assert usuario.farm_access.get().can_write is True

        pedido.refresh_from_db()
        assert pedido.status == AccessRequestStatus.APROVADA
        assert (
            pedido.decided_by == admin and pedido.user == usuario and pedido.decided_at
        )

        (mensagem,) = mailoutbox
        assert mensagem.to == ["carlos@exemplo.com"]
        assert "aprovada" in mensagem.body and "carlos" in mensagem.body
        token = re.search(r"/senha/redefinir/[^/]+/([^/\s]+)/", mensagem.body).group(1)
        assert default_token_generator.check_token(usuario, token)
        assert AuditEvent.objects.filter(
            action=AuditAction.APPROVE, entity_id=str(pedido.pk)
        ).exists()
        assert AuditEvent.objects.filter(
            action=AuditAction.CREATE, entity_id=str(usuario.pk)
        ).exists()

    def test_e_mail_do_pedido_nao_e_editavel_pela_aprovacao(
        self, cliente_admin, fazenda_a, pedido
    ):
        cliente_admin.post(
            reverse("accounts:solicitacao_aprovar", args=[pedido.pk]),
            {
                "username": "carlos",
                "first_name": "Carlos",
                "email": "outro@x.com",
                "role": Role.CAMPO,
                f"farm_{fazenda_a.pk}": "leitura",
            },
        )
        assert User.objects.get(username="carlos").email == "carlos@exemplo.com"

    def test_aprovar_exige_papel_e_fazenda(self, cliente_admin, fazenda_a, pedido):
        resposta = cliente_admin.post(
            reverse("accounts:solicitacao_aprovar", args=[pedido.pk]),
            {"username": "carlos", "first_name": "Carlos", "role": Role.CAMPO},
        )
        assert resposta.status_code == 200
        assert "Marque ao menos uma fazenda" in resposta.content.decode()
        pedido.refresh_from_db()
        assert pedido.status == AccessRequestStatus.PENDENTE

    def test_aprovar_com_usuario_ja_usado_nao_perde_o_pedido(
        self, cliente_admin, admin, fazenda_a, pedido
    ):
        resposta = cliente_admin.post(
            reverse("accounts:solicitacao_aprovar", args=[pedido.pk]),
            {
                "username": "admin1",
                "first_name": "Carlos",
                "role": Role.CAMPO,
                f"farm_{fazenda_a.pk}": "leitura",
            },
        )
        assert resposta.status_code == 200 and "já existe" in resposta.content.decode()
        pedido.refresh_from_db()
        assert pedido.status == AccessRequestStatus.PENDENTE

    def test_segunda_decisao_recebe_o_que_a_primeira_fez(
        self, admin, outro_admin, fazenda_a, pedido
    ):
        pedidos.aprovar_solicitacao(
            pedido,
            ator=admin,
            dados={
                "username": "carlos",
                "first_name": "Carlos",
                "last_name": "",
                "phone": "",
                "role": Role.CAMPO,
            },
            acessos={fazenda_a: True},
            base_url="http://testserver/",
        )
        antigo = AccessRequest.objects.get(pk=pedido.pk)
        antigo.status = (
            AccessRequestStatus.PENDENTE
        )  # a tela do segundo admin ainda mostrava pendente
        with pytest.raises(BusinessError, match="já foi aprovada"):
            pedidos.recusar_solicitacao(
                antigo, ator=outro_admin, motivo="x", avisar=False
            )
        assert User.objects.filter(email="carlos@exemplo.com").count() == 1

    def test_aprovacao_aberta_de_pedido_decidido_avisa_e_volta_para_a_lista(
        self, cliente_admin, admin, pedido
    ):
        pedidos.recusar_solicitacao(pedido, ator=admin, motivo="x", avisar=False)
        resposta = cliente_admin.get(
            reverse("accounts:solicitacao_aprovar", args=[pedido.pk])
        )
        assert resposta.status_code == 302

    def test_recusar_exige_motivo_e_nao_manda_o_motivo_no_email(
        self,
        cliente_admin,
        admin,
        pedido,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        url = reverse("accounts:solicitacao_recusar", args=[pedido.pk])
        assert (
            cliente_admin.post(url, {"motivo": " ", "avisar": "on"}).status_code == 200
        )
        pedido.refresh_from_db()
        assert pedido.status == AccessRequestStatus.PENDENTE

        with django_capture_on_commit_callbacks(execute=True):
            cliente_admin.post(
                url, {"motivo": "Não conheço esta pessoa", "avisar": "on"}
            )
        pedido.refresh_from_db()
        assert pedido.status == AccessRequestStatus.RECUSADA
        assert pedido.decision_reason == "Não conheço esta pessoa"
        (mensagem,) = mailoutbox
        assert mensagem.to == ["carlos@exemplo.com"]
        assert (
            "não foi aprovada" in mensagem.body and "Não conheço" not in mensagem.body
        )
        assert AuditEvent.objects.filter(
            action=AuditAction.CANCEL, entity_id=str(pedido.pk)
        ).exists()

    def test_recusar_sem_avisar_nao_envia_email(
        self, admin, pedido, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            pedidos.recusar_solicitacao(pedido, ator=admin, motivo="x", avisar=False)
        assert mailoutbox == []

    def test_pedido_nunca_e_apagado(self, admin, pedido):
        pedidos.recusar_solicitacao(pedido, ator=admin, motivo="x", avisar=False)
        assert AccessRequest.objects.filter(pk=pedido.pk).exists()


class TestIntegridade:
    def test_banco_recusa_dois_pendentes_com_o_mesmo_email(self, pedido):
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            AccessRequest.objects.create(
                full_name="X", email="CARLOS@exemplo.com", message="y"
            )

    def test_banco_recusa_decisao_sem_data(self, pedido):
        from django.db import IntegrityError, transaction

        pedido.status = AccessRequestStatus.APROVADA
        with pytest.raises(IntegrityError), transaction.atomic():
            pedido.save()

    def test_banco_recusa_dois_usuarios_com_o_mesmo_email(self, db):
        from django.db import IntegrityError, transaction

        User.objects.create_user(username="a", password="s", email="x@x.com")
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="b", password="s", email="X@x.com")

    def test_usuarios_sem_email_nao_conflitam(self, db):
        User.objects.create_user(username="a", password="s")
        User.objects.create_user(username="b", password="s")
