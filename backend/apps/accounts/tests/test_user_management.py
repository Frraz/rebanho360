"""Gerenciamento de usuários pelo administrador."""

import re

import pytest
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.accounts import user_management as gestao
from apps.accounts.models import Role, User, UserFarmAccess
from apps.audit.models import AuditAction, AuditEvent
from apps.core.exceptions import BusinessError

pytestmark = pytest.mark.django_db

DADOS = {
    "first_name": "Maria",
    "last_name": "Souza",
    "email": "maria@exemplo.com",
    "phone": "",
    "role": Role.CAMPO,
}


def _criar(admin, fazenda, *, username="maria", **extra):
    return gestao.criar_usuario(
        ator=admin,
        dados={"username": username, **{**DADOS, **extra}},
        acessos={fazenda: True},
        base_url="http://testserver/",
    )


class TestPermissao:
    def test_anonimo_vai_para_o_login(self, client):
        resposta = client.get(reverse("accounts:usuarios"))
        assert resposta.status_code == 302
        assert reverse("accounts:login") in resposta["Location"]

    @pytest.mark.parametrize(
        "papel",
        [Role.GESTOR, Role.ESCRITORIO, Role.CAMPO, Role.FINANCEIRO, Role.CONSULTA],
    )
    def test_so_o_admin_gerencia(self, client, papel):
        usuario = User.objects.create_user(username="x", password="s", role=papel)
        client.force_login(usuario)
        for nome in ("accounts:usuarios", "accounts:usuario_novo"):
            assert client.get(reverse(nome)).status_code == 403
        # Decidir pedidos de acesso é de ADMIN e GESTOR (cliente, 2026-10-03).
        status = 200 if papel == Role.GESTOR else 403
        assert client.get(reverse("accounts:solicitacoes")).status_code == status

    def test_is_staff_sozinho_nao_basta(self, client):
        staff = User.objects.create_user(
            username="s", password="s", role=Role.CONSULTA, is_staff=True
        )
        client.force_login(staff)
        assert client.get(reverse("accounts:usuarios")).status_code == 403

    def test_superusuario_criado_pelo_createsuperuser_entra(self, client):
        # `createsuperuser` deixa o papel padrão (consulta): ele não pode ficar de fora.
        root = User.objects.create_superuser(username="root", password="s")
        client.force_login(root)
        assert client.get(reverse("accounts:usuarios")).status_code == 200

    def test_servico_tambem_confere_a_permissao(self, fazenda_a):
        gestor = User.objects.create_user(username="g", password="s", role=Role.GESTOR)
        with pytest.raises(PermissionDenied):
            _criar(gestor, fazenda_a)

    def test_menu_aparece_para_admin_e_gestor_e_nao_para_os_demais(
        self, cliente_admin, client, admin
    ):
        assert (
            "Usuários e acessos"
            in cliente_admin.get(reverse("dashboards:inicio")).content.decode()
        )
        gestor = User.objects.create_user(username="g", password="s", role=Role.GESTOR)
        client.force_login(gestor)
        html = client.get(reverse("dashboards:inicio")).content.decode()
        assert "Usuários e acessos" in html
        # o gestor cai direto nas solicitações: a lista de usuários não é dele
        assert f'href="{reverse("accounts:solicitacoes")}"' in html
        escritorio = User.objects.create_user(
            username="e", password="s", role=Role.ESCRITORIO
        )
        client.force_login(escritorio)
        assert (
            "Usuários e acessos"
            not in client.get(reverse("dashboards:inicio")).content.decode()
        )


class TestCriar:
    def test_convite_cria_conta_sem_senha_e_envia_o_link(
        self, admin, fazenda_a, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            usuario = _criar(admin, fazenda_a)

        assert not usuario.has_usable_password()
        assert usuario.must_change_password is False
        assert UserFarmAccess.objects.get(user=usuario).farm == fazenda_a
        (mensagem,) = mailoutbox
        assert mensagem.to == ["maria@exemplo.com"]
        assert "maria" in mensagem.body  # o usuário para entrar
        assert "senha-" not in mensagem.body

    def test_link_do_convite_define_a_senha_e_permite_entrar(
        self, client, admin, fazenda_a, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _criar(admin, fazenda_a)
        caminho = re.search(
            r"http://testserver(/contas/senha/redefinir/\S+)", mailoutbox[0].body
        ).group(1)

        resposta = client.get(
            caminho, follow=True
        )  # o Django troca o token pela sessão
        destino = resposta.redirect_chain[-1][0]
        resposta = client.post(
            destino,
            {
                "new_password1": "uma-senha-boa-987",
                "new_password2": "uma-senha-boa-987",
            },
        )
        assert resposta.status_code == 302
        assert client.login(username="maria", password="uma-senha-boa-987")

    def test_senha_temporaria_obriga_a_trocar_no_primeiro_acesso(
        self, client, admin, fazenda_a
    ):
        usuario = gestao.criar_usuario(
            ator=admin,
            dados={"username": "joao", **DADOS},
            acessos={fazenda_a: True},
            senha_temporaria="temporaria-4321",
        )
        assert usuario.must_change_password is True

        client.post(
            reverse("accounts:login"),
            {"username": "joao", "password": "temporaria-4321"},
        )
        resposta = client.get(reverse("dashboards:inicio"))
        assert resposta.status_code == 302
        assert resposta["Location"] == reverse("accounts:password_change")

        resposta = client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "temporaria-4321",
                "new_password1": "minha-senha-nova-77",
                "new_password2": "minha-senha-nova-77",
            },
        )
        assert resposta.status_code == 302
        usuario.refresh_from_db()
        assert usuario.must_change_password is False
        assert client.get(reverse("dashboards:inicio")).status_code == 200

    @pytest.mark.parametrize("senha_temporaria", [None, "temporaria-4321"])
    def test_todo_usuario_precisa_de_email(self, admin, fazenda_a, senha_temporaria):
        """Cliente, 2026-10-03 (#31): e-mail obrigatório, com ou sem convite."""
        with pytest.raises(BusinessError, match="precisa de e-mail"):
            gestao.criar_usuario(
                ator=admin,
                dados={"username": "joao", **DADOS, "email": ""},
                acessos={fazenda_a: True},
                senha_temporaria=senha_temporaria,
            )

    def test_editar_nao_deixa_tirar_o_email(self, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        with pytest.raises(BusinessError, match="precisa de e-mail"):
            gestao.editar_usuario(
                usuario,
                ator=admin,
                dados={**DADOS, "email": ""},
                acessos={fazenda_a: True},
                motivo="teste",
            )

    def test_senha_curta_demais_e_recusada(self, admin, fazenda_a):
        """Política liberal (2026-10-03): o único requisito é ter 4 caracteres."""
        with pytest.raises(BusinessError, match="4 caracteres"):
            gestao.criar_usuario(
                ator=admin,
                dados={"username": "joao", **DADOS},
                acessos={fazenda_a: True},
                senha_temporaria="123",
            )

    @pytest.mark.parametrize(
        "senha", ["0000", "1111", "abcde", "senha", "ABCD", "a1b2"]
    )
    def test_senha_simples_e_aceita(self, admin, fazenda_a, senha):
        usuario = gestao.criar_usuario(
            ator=admin,
            dados={"username": "joao", **DADOS},
            acessos={fazenda_a: True},
            senha_temporaria=senha,
        )
        assert usuario.check_password(senha)

    def test_email_repetido_ignora_maiusculas(self, admin, fazenda_a):
        _criar(admin, fazenda_a)
        with pytest.raises(BusinessError, match="e-mail"):
            _criar(admin, fazenda_a, username="outra", email="MARIA@exemplo.com")

    def test_auditoria_nao_guarda_senha(self, admin, fazenda_a):
        usuario = gestao.criar_usuario(
            ator=admin,
            dados={"username": "joao", **DADOS},
            acessos={fazenda_a: True},
            senha_temporaria="temporaria-4321",
        )
        evento = AuditEvent.objects.get(entity_type="User", entity_id=str(usuario.pk))
        assert evento.action == AuditAction.CREATE
        assert evento.actor == admin
        texto = str(evento.after)
        assert "temporaria-4321" not in texto and "argon2" not in texto
        assert evento.after["acessos"] == {"SRT": True}

    def test_formulario_exige_fazenda_para_papel_sem_acesso_amplo(
        self, cliente_admin, fazenda_a
    ):
        corpo = {
            "username": "paulo",
            "first_name": "Paulo",
            "email": "paulo@x.com",
            "role": Role.CAMPO,
            "senha_modo": "convite",
        }
        resposta = cliente_admin.post(reverse("accounts:usuario_novo"), corpo)
        assert resposta.status_code == 200
        assert "Marque ao menos uma fazenda" in resposta.content.decode()
        assert not User.objects.filter(username="paulo").exists()

        resposta = cliente_admin.post(
            reverse("accounts:usuario_novo"),
            {**corpo, f"farm_{fazenda_a.pk}": "leitura"},
        )
        assert resposta.status_code == 302
        acesso = UserFarmAccess.objects.get(user__username="paulo")
        assert acesso.can_write is False

    def test_admin_nao_guarda_linha_de_fazenda(self, admin, fazenda_a):
        novo = gestao.criar_usuario(
            ator=admin,
            dados={"username": "chefe", **DADOS, "role": Role.ADMIN},
            acessos={fazenda_a: True},
            base_url="http://testserver/",
        )
        assert not novo.farm_access.exists()


class TestEditar:
    def test_exige_motivo(self, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        with pytest.raises(BusinessError, match="motivo"):
            gestao.editar_usuario(
                usuario,
                ator=admin,
                dados={**DADOS, "first_name": "Mari"},
                acessos={fazenda_a: True},
                motivo="  ",
            )

    def test_grava_antes_e_depois_com_o_motivo(self, admin, fazenda_a, fazenda_b):
        usuario = _criar(admin, fazenda_a)
        mudou = gestao.editar_usuario(
            usuario,
            ator=admin,
            dados={**DADOS, "role": Role.ESCRITORIO},
            acessos={fazenda_a: True, fazenda_b: False},
            motivo="Passou para o escritório",
        )
        assert mudou
        evento = AuditEvent.objects.filter(
            entity_id=str(usuario.pk), action=AuditAction.UPDATE
        ).get()
        assert evento.reason == "Passou para o escritório"
        assert (
            evento.before["role"] == Role.CAMPO
            and evento.after["role"] == Role.ESCRITORIO
        )
        assert "role" in evento.changed_fields and "acessos" in evento.changed_fields
        assert usuario.farm_access.count() == 2

    def test_sem_mudanca_nao_grava_auditoria(self, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        antes = AuditEvent.objects.count()
        assert (
            gestao.editar_usuario(
                usuario,
                ator=admin,
                dados=DADOS,
                acessos={fazenda_a: True},
                motivo="nada",
            )
            is False
        )
        assert AuditEvent.objects.count() == antes

    def test_nao_muda_o_proprio_papel(self, admin, outro_admin):
        with pytest.raises(BusinessError, match="próprio papel"):
            gestao.editar_usuario(
                admin,
                ator=admin,
                dados={
                    "first_name": "Ana",
                    "last_name": "",
                    "email": admin.email,
                    "phone": "",
                    "role": Role.GESTOR,
                },
                acessos={},
                motivo="teste",
            )

    def test_guarda_do_ultimo_administrador(self, admin, outro_admin):
        # Com dois administradores, qualquer um pode sair; com um só, não.
        gestao._garantir_outro_administrador(admin)
        gestao.desativar_usuario(outro_admin, ator=admin, motivo="saiu")
        with pytest.raises(BusinessError, match="único administrador"):
            gestao._garantir_outro_administrador(admin)

    def test_tela_explica_que_o_ultimo_admin_nao_sai(self, admin):
        gestor = User.objects.create_user(username="g", password="s", role=Role.GESTOR)
        (aviso,) = gestao.bloqueios_para_remover(admin, gestor, "desativar")
        assert "único administrador" in aviso and "Editar → Papel" in aviso

    def test_trocar_email_para_um_em_uso_e_recusado(self, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        with pytest.raises(BusinessError, match="e-mail"):
            gestao.editar_usuario(
                usuario,
                ator=admin,
                dados={**DADOS, "email": admin.email},
                acessos={fazenda_a: True},
                motivo="teste",
            )


class TestDesativarEExcluir:
    def test_desativar_derruba_a_sessao_e_barra_o_login(self, client, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        usuario.set_password("senha-da-maria-1")
        usuario.save()
        assert client.login(username="maria", password="senha-da-maria-1")
        assert Session.objects.count() == 1

        encerradas = gestao.desativar_usuario(
            usuario, ator=admin, motivo="Saiu da fazenda"
        )

        assert encerradas == 1 and Session.objects.count() == 0
        assert not client.login(username="maria", password="senha-da-maria-1")
        evento = AuditEvent.objects.filter(
            entity_id=str(usuario.pk), action=AuditAction.UPDATE
        ).latest("id")
        assert "Saiu da fazenda" in evento.reason
        assert evento.before["is_active"] is True and evento.after["is_active"] is False

    def test_reativar(self, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        gestao.desativar_usuario(usuario, ator=admin, motivo="férias")
        gestao.reativar_usuario(usuario, ator=admin, motivo="voltou")
        usuario.refresh_from_db()
        assert usuario.is_active

    def test_nao_desativa_nem_exclui_a_si_mesmo(self, admin, outro_admin):
        with pytest.raises(BusinessError, match="própria conta"):
            gestao.desativar_usuario(admin, ator=admin, motivo="x")
        with pytest.raises(BusinessError, match="própria conta"):
            gestao.excluir_usuario(admin, ator=admin, motivo="x")

    def test_superusuario_conta_como_administrador(self, admin):
        root = User.objects.create_superuser(username="root", password="s")
        gestao.desativar_usuario(
            admin, ator=root, motivo="teste"
        )  # root ainda administra
        with pytest.raises(BusinessError, match="própria"):
            gestao.desativar_usuario(root, ator=root, motivo="x")

    def test_excluir_e_logico_libera_o_email_e_pode_voltar(self, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        gestao.excluir_usuario(usuario, ator=admin, motivo="Cadastro duplicado")

        usuario.refresh_from_db()
        assert User.objects.filter(pk=usuario.pk).exists()  # nunca sai do banco
        assert usuario.deleted_at and not usuario.is_active
        assert AuditEvent.objects.filter(
            entity_id=str(usuario.pk), action=AuditAction.DELETE
        ).exists()
        # O e-mail volta a ficar livre.
        _criar(admin, fazenda_a, username="maria2")

        # Restaurar: o e-mail já é de outra conta, então a volta é recusada com o caminho.
        with pytest.raises(BusinessError, match="já pertence"):
            gestao.restaurar_usuario(usuario, ator=admin, motivo="engano")

    def test_restaurar_volta_desativado(self, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        gestao.excluir_usuario(usuario, ator=admin, motivo="engano")
        gestao.restaurar_usuario(usuario, ator=admin, motivo="era o certo")
        usuario.refresh_from_db()
        assert usuario.deleted_at is None and usuario.is_active is False
        assert AuditEvent.objects.filter(
            entity_id=str(usuario.pk), action=AuditAction.RESTORE
        ).exists()

    def test_lista_esconde_excluidos_e_a_aba_mostra(
        self, cliente_admin, admin, fazenda_a
    ):
        usuario = _criar(admin, fazenda_a)
        gestao.excluir_usuario(usuario, ator=admin, motivo="x")
        url = reverse("accounts:usuarios")
        assert "maria@exemplo.com" not in cliente_admin.get(url).content.decode()
        assert (
            "maria@exemplo.com"
            in cliente_admin.get(url, {"estado": "excluidos"}).content.decode()
        )

    def test_tela_explica_o_bloqueio_em_vez_de_so_recusar(self, cliente_admin, admin):
        resposta = cliente_admin.get(
            reverse("accounts:usuario_desativar", args=[admin.pk])
        )
        html = resposta.content.decode()
        assert "Não dá para fazer isto agora" in html
        assert "Peça a outro administrador" in html

    def test_post_sem_motivo_nao_executa(self, cliente_admin, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        resposta = cliente_admin.post(
            reverse("accounts:usuario_desativar", args=[usuario.pk]), {"motivo": ""}
        )
        assert resposta.status_code == 200
        usuario.refresh_from_db()
        assert usuario.is_active


class TestSenhaESessoes:
    def test_senha_temporaria_derruba_sessoes_e_exige_troca(
        self, client, admin, fazenda_a
    ):
        usuario = _criar(admin, fazenda_a)
        usuario.set_password("senha-antiga-1234")
        usuario.save()
        client.login(username="maria", password="senha-antiga-1234")

        gestao.definir_senha_temporaria(
            usuario, ator=admin, senha="outra-temporaria-55", motivo="Esqueceu"
        )

        usuario.refresh_from_db()
        assert usuario.must_change_password and usuario.check_password(
            "outra-temporaria-55"
        )
        assert Session.objects.count() == 0
        evento = AuditEvent.objects.filter(entity_id=str(usuario.pk)).latest("id")
        assert "outra-temporaria-55" not in str(evento.after) + evento.reason

    def test_nao_define_senha_temporaria_para_si(self, admin):
        with pytest.raises(BusinessError, match="Alterar senha"):
            gestao.definir_senha_temporaria(
                admin, ator=admin, senha="outra-temporaria-55", motivo="x"
            )

    def test_link_de_senha_por_email(
        self, admin, fazenda_a, mailoutbox, django_capture_on_commit_callbacks
    ):
        usuario = _criar(admin, fazenda_a)
        with django_capture_on_commit_callbacks(execute=True):
            gestao.enviar_link_de_senha(
                usuario,
                ator=admin,
                motivo="Perdeu a senha",
                base_url="http://testserver/",
            )
        assert mailoutbox[-1].to == ["maria@exemplo.com"]
        assert "/contas/senha/redefinir/" in mailoutbox[-1].body

    def test_link_de_senha_sem_email_explica_o_caminho(self, admin, fazenda_a):
        # conta antiga, de antes da regra de e-mail obrigatório
        usuario = User.objects.create_user(
            username="sem", password="temporaria-4321", role=Role.CAMPO, email=""
        )
        with pytest.raises(BusinessError, match="senha temporária"):
            gestao.enviar_link_de_senha(
                usuario, ator=admin, motivo="x", base_url="http://t/"
            )

    def test_encerrar_sessoes(self, client, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        usuario.set_password("senha-da-maria-1")
        usuario.save()
        client.login(username="maria", password="senha-da-maria-1")
        assert (
            gestao.encerrar_sessoes_do_usuario(
                usuario, ator=admin, motivo="aparelho alheio"
            )
            == 1
        )
        usuario.refresh_from_db()
        assert usuario.is_active  # a conta segue ativa

    def test_nao_redefine_o_proprio_segundo_fator(self, admin, outro_admin):
        with pytest.raises(BusinessError, match="segundo fator"):
            gestao.redefinir_segundo_fator(admin, ator=admin, motivo="x")

    def test_redefine_segundo_fator_de_outro_com_rastro(self, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        gestao.redefinir_segundo_fator(usuario, ator=admin, motivo="Perdeu o celular")
        assert AuditEvent.objects.filter(entity_type="TOTPDevice", actor=admin).exists()


class TestTelas:
    def test_editar_pela_tela_grava_e_volta_ao_detalhe(
        self, cliente_admin, admin, fazenda_a, fazenda_b
    ):
        usuario = _criar(admin, fazenda_a)
        resposta = cliente_admin.post(
            reverse("accounts:usuario_editar", args=[usuario.pk]),
            {
                "first_name": "Maria",
                "last_name": "Souza",
                "email": "maria@exemplo.com",
                "phone": "(63) 99999-0000",
                "role": Role.ESCRITORIO,
                f"farm_{fazenda_a.pk}": "lancar",
                f"farm_{fazenda_b.pk}": "leitura",
                "motivo": "Mudou de função",
            },
        )
        assert resposta.status_code == 302
        usuario.refresh_from_db()
        assert usuario.role == Role.ESCRITORIO and usuario.phone == "(63) 99999-0000"
        assert dict(usuario.farm_access.values_list("farm__code", "can_write")) == {
            "SRT": True,
            "BXO": False,
        }

    def test_editar_sem_motivo_nao_grava(self, cliente_admin, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        resposta = cliente_admin.post(
            reverse("accounts:usuario_editar", args=[usuario.pk]),
            {
                "first_name": "Outro",
                "email": "maria@exemplo.com",
                "role": Role.CAMPO,
                f"farm_{fazenda_a.pk}": "lancar",
                "motivo": "",
            },
        )
        assert resposta.status_code == 200
        usuario.refresh_from_db()
        assert usuario.first_name == "Maria"

    def test_superusuario_edita_o_proprio_cadastro_sem_marcar_fazenda(
        self, client, fazenda_a
    ):
        root = User.objects.create_superuser(
            username="root", password="s", first_name="Root"
        )
        client.force_login(root)
        resposta = client.post(
            reverse("accounts:usuario_editar", args=[root.pk]),
            {
                "first_name": "Chefe",
                "email": "root@x.com",
                "role": Role.CONSULTA,
                "motivo": "Corrigir o nome",
            },
        )
        assert resposta.status_code == 302
        root.refresh_from_db()
        assert root.first_name == "Chefe"

    def test_pagina_de_usuario_inexistente_e_404(self, cliente_admin):
        assert (
            cliente_admin.get(
                reverse("accounts:usuario_detalhe", args=[999999])
            ).status_code
            == 404
        )

    def test_detalhe_mostra_o_historico_da_conta(self, cliente_admin, admin, fazenda_a):
        usuario = _criar(admin, fazenda_a)
        gestao.desativar_usuario(usuario, ator=admin, motivo="Saiu da fazenda")
        html = cliente_admin.get(
            reverse("accounts:usuario_detalhe", args=[usuario.pk])
        ).content.decode()
        assert "Saiu da fazenda" in html and "Desativado" in html

    def test_post_sem_csrf_nas_acoes_e_recusado(self, admin, fazenda_a):
        from django.test import Client

        usuario = _criar(admin, fazenda_a)
        c = Client(enforce_csrf_checks=True)
        c.force_login(admin)
        resposta = c.post(
            reverse("accounts:usuario_excluir", args=[usuario.pk]), {"motivo": "x"}
        )
        assert resposta.status_code == 403
        usuario.refresh_from_db()
        assert usuario.deleted_at is None

    def test_quem_tem_de_trocar_a_senha_ainda_consegue_sair(
        self, client, admin, fazenda_a
    ):
        usuario = gestao.criar_usuario(
            ator=admin,
            dados={"username": "joao", **DADOS},
            acessos={fazenda_a: True},
            senha_temporaria="temporaria-4321",
        )
        client.force_login(usuario)
        assert client.get(reverse("accounts:password_change")).status_code == 200
        assert client.post(reverse("accounts:logout")).status_code == 302
        assert "_auth_user_id" not in client.session
