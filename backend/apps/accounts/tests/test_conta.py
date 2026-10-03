"""Página Conta: o usuário edita o próprio perfil, a senha e vê o segundo fator."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import AuditAction, AuditEvent

CPF = "52998224725"
CPF_FORMATADO = "529.982.247-25"
SENHA = "senha-antiga-9182"


@pytest.fixture
def gestor(db):
    return User.objects.create_user(
        username="gestor1",
        password=SENHA,
        role=Role.GESTOR,
        email="gestor1@fazenda.com.br",
        first_name="Gil",
    )


@pytest.fixture
def cliente(client, gestor):
    client.force_login(gestor)
    return client


def _dados(**extra):
    base = {
        "first_name": "Gilberto",
        "last_name": "Souza",
        "phone": "(63) 99999-0000",
        "birth_date": "1985-03-20",
        "cpf": CPF_FORMATADO,
    }
    base.update(extra)
    return base


class TestAcesso:
    def test_exige_login(self, client):
        resposta = client.get(reverse("accounts:conta"))
        assert resposta.status_code == 302
        assert reverse("accounts:login") in resposta["Location"]

    def test_qualquer_papel_abre_a_propria_conta(self, client, db):
        consulta = User.objects.create_user(
            username="leitor", password=SENHA, role=Role.CONSULTA
        )
        client.force_login(consulta)
        assert client.get(reverse("accounts:conta")).status_code == 200

    def test_mostra_e_nao_deixa_editar_email_e_papel(self, cliente):
        html = cliente.get(reverse("accounts:conta")).content.decode()
        assert "gestor1@fazenda.com.br" in html
        assert 'name="email"' not in html
        assert 'name="role"' not in html


class TestPerfil:
    def test_salva_e_audita_com_cpf_mascarado(self, cliente, gestor):
        resposta = cliente.post(reverse("accounts:conta"), _dados())
        assert resposta.status_code == 302
        gestor.refresh_from_db()
        assert gestor.first_name == "Gilberto"
        assert gestor.cpf == CPF
        assert str(gestor.birth_date) == "1985-03-20"

        evento = AuditEvent.objects.filter(
            entity_type="User", entity_id=str(gestor.pk), action=AuditAction.UPDATE
        ).latest("timestamp")
        assert evento.actor_id == gestor.pk
        assert "cpf" in evento.changed_fields
        assert evento.after["cpf"] == "***.***.***-25"
        assert CPF not in str(evento.before) + str(evento.after)

    def test_nada_mudou_nao_gera_auditoria(self, cliente, gestor):
        cliente.post(reverse("accounts:conta"), _dados())
        antes = AuditEvent.objects.count()
        cliente.post(reverse("accounts:conta"), _dados())
        assert AuditEvent.objects.count() == antes

    def test_cpf_e_opcional(self, cliente, gestor):
        resposta = cliente.post(
            reverse("accounts:conta"), _dados(cpf="", birth_date="")
        )
        assert resposta.status_code == 302
        gestor.refresh_from_db()
        assert gestor.cpf == "" and gestor.birth_date is None

    def test_cpf_invalido_e_recusado(self, cliente, gestor):
        resposta = cliente.post(reverse("accounts:conta"), _dados(cpf="123.456.789-00"))
        assert resposta.status_code == 200
        assert "CPF inválido" in resposta.content.decode()
        gestor.refresh_from_db()
        assert gestor.cpf == ""

    def test_cpf_de_outra_conta_e_recusado_com_mensagem_especifica(
        self, cliente, gestor
    ):
        User.objects.create_user(
            username="outro", password=SENHA, role=Role.CAMPO, cpf=CPF
        )
        resposta = cliente.post(reverse("accounts:conta"), _dados())
        assert "já está cadastrado em outra conta" in resposta.content.decode()
        gestor.refresh_from_db()
        assert gestor.cpf == ""

    def test_data_de_nascimento_implausivel_e_recusada(self, cliente):
        futuro = cliente.post(
            reverse("accounts:conta"), _dados(birth_date="2999-01-01")
        )
        assert "no futuro" in futuro.content.decode()
        crianca = cliente.post(
            reverse("accounts:conta"), _dados(birth_date="2024-01-01")
        )
        assert "não é plausível" in crianca.content.decode()

    def test_post_adulterado_nao_muda_papel_email_nem_usuario(self, cliente, gestor):
        cliente.post(
            reverse("accounts:conta"),
            _dados(
                role=Role.ADMIN, email="invasor@x.com", username="root", is_active=""
            ),
        )
        gestor.refresh_from_db()
        assert gestor.role == Role.GESTOR
        assert gestor.email == "gestor1@fazenda.com.br"
        assert gestor.username == "gestor1"
        assert gestor.is_active is True

    def test_nome_em_branco_e_recusado(self, cliente):
        resposta = cliente.post(reverse("accounts:conta"), _dados(first_name="   "))
        assert resposta.status_code == 200
        assert "obrigatório" in resposta.content.decode()

    def test_telefone_invalido_e_recusado(self, cliente):
        resposta = cliente.post(reverse("accounts:conta"), _dados(phone="abc"))
        assert "Informe só números" in resposta.content.decode()

    def test_cpf_aparece_formatado_so_para_o_dono(self, cliente, gestor):
        gestor.cpf = CPF
        gestor.save(update_fields=["cpf"])
        assert CPF_FORMATADO in cliente.get(reverse("accounts:conta")).content.decode()


class TestSenha:
    def _trocar(self, cliente, nova="outra-senha-forte-5531", antiga=SENHA):
        return cliente.post(
            reverse("accounts:password_change"),
            {"old_password": antiga, "new_password1": nova, "new_password2": nova},
        )

    def test_troca_audita_sem_a_senha(self, cliente, gestor):
        resposta = self._trocar(cliente)
        assert resposta.status_code == 302
        assert resposta["Location"].endswith(reverse("accounts:conta") + "#senha")
        gestor.refresh_from_db()
        assert gestor.check_password("outra-senha-forte-5531")

        evento = AuditEvent.objects.filter(
            entity_type="User", entity_id=str(gestor.pk), changed_fields=["password"]
        ).get()
        assert evento.actor_id == gestor.pk
        assert "outra-senha" not in str(evento.__dict__)

    def test_senha_atual_errada_reabre_a_conta_com_o_erro(self, cliente, gestor):
        resposta = self._trocar(cliente, antiga="errada-1234567")
        assert resposta.status_code == 200
        assert "accounts/conta.html" in [t.name for t in resposta.templates]
        assert "A senha não foi trocada" in resposta.content.decode()
        gestor.refresh_from_db()
        assert gestor.check_password(SENHA)

    def test_sessao_continua_valida_depois_da_troca(self, cliente):
        self._trocar(cliente)
        assert cliente.get(reverse("accounts:conta")).status_code == 200

    def test_get_fora_da_troca_obrigatoria_vai_para_a_conta(self, cliente):
        resposta = cliente.get(reverse("accounts:password_change"))
        assert resposta.status_code == 302
        assert resposta["Location"] == reverse("accounts:conta") + "#senha"

    def test_troca_obrigatoria_continua_com_tela_propria(self, client, db):
        usuario = User.objects.create_user(
            username="novo", password=SENHA, role=Role.CAMPO, must_change_password=True
        )
        client.force_login(usuario)
        assert client.get(reverse("accounts:password_change")).status_code == 200
        assert client.get(reverse("accounts:conta")).status_code == 302
        resposta = self._trocar(client)
        assert resposta.status_code == 302 and resposta["Location"] == "/"
        usuario.refresh_from_db()
        assert usuario.must_change_password is False


class TestSegundoFator:
    def test_status_antigo_redireciona_para_a_conta(self, cliente):
        resposta = cliente.get(reverse("accounts:2fa_status"))
        assert resposta.status_code == 302
        assert resposta["Location"] == reverse("accounts:conta") + "#seguranca"

    def test_conta_mostra_que_esta_desativado_e_oferece_ativar(self, cliente):
        html = cliente.get(reverse("accounts:conta")).content.decode()
        assert "Desativado" in html
        assert reverse("accounts:2fa_configurar") in html
