"""Condições de pagamento: cadastro do usuário (cliente, 2026-10-03)."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.commercial.models import PaymentCondition, parse_prazos
from apps.commercial.payment import aplicar_condicao
from apps.core.exceptions import BusinessError

pytestmark = pytest.mark.django_db


class TestPrazos:
    @pytest.mark.parametrize(
        "texto,esperado",
        [("0", [0]), ("30", [30]), ("30,60,90", [30, 60, 90]), (" 7 , 14 ", [7, 14])],
    )
    def test_le_prazos(self, texto, esperado):
        assert parse_prazos(texto) == esperado

    @pytest.mark.parametrize("texto", ["", "abc", "30,x", "60,30", "30,30", "-5"])
    def test_recusa_prazo_invalido(self, texto):
        with pytest.raises(ValueError):
            parse_prazos(texto)

    def test_resumo_diz_o_que_a_condicao_faz(self):
        assert PaymentCondition(name="a", days="0").resumo == "à vista"
        assert PaymentCondition(name="b", days="15").resumo == "15 dias"
        assert PaymentCondition(name="c", days="30,60").parcelado
        assert "2 parcelas" in PaymentCondition(name="c", days="30,60").resumo


class TestSemente:
    def test_vem_com_os_exemplos_do_cliente(self):
        nomes = set(PaymentCondition.objects.values_list("name", flat=True))
        assert {"À vista", "4 dias", "7 dias", "15 dias", "30 dias"} <= nomes


class TestAplicar:
    def test_copia_o_primeiro_prazo_para_payment_days(self):
        condicao = PaymentCondition.objects.create(name="30/60", days="30,60")
        dados = aplicar_condicao({"payment_condition": condicao, "payment_days": 5})
        assert dados["payment_days"] == 30

    def test_sem_condicao_deixa_o_prazo_digitado(self):
        assert aplicar_condicao({"payment_days": 12}) == {"payment_days": 12}

    def test_condicao_inativa_e_recusada_a_menos_que_ja_fosse_a_da_operacao(self):
        condicao = PaymentCondition.objects.create(
            name="Velha", days="9", is_active=False
        )
        with pytest.raises(BusinessError, match="inativa"):
            aplicar_condicao({"payment_condition": condicao})
        assert (
            aplicar_condicao({"payment_condition": condicao}, atual=condicao)[
                "payment_days"
            ]
            == 9
        )


class TestTelas:
    @pytest.fixture
    def usuario(self):
        return User.objects.create_user(
            username="esc", password="x", role=Role.ESCRITORIO
        )

    def test_lista_abre_para_quem_esta_logado(self, client, usuario):
        client.force_login(usuario)
        resposta = client.get(reverse("commercial:condicao_lista"))
        assert resposta.status_code == 200
        assert "À vista" in resposta.content.decode()

    def test_usuario_cria_condicao_nova_e_ela_fica_auditada(self, client, usuario):
        from apps.audit.models import AuditAction, AuditEvent

        client.force_login(usuario)
        resposta = client.post(
            reverse("commercial:condicao_nova"),
            {
                "name": "Entrada + 45",
                "days": "0, 45",
                "display_order": 9,
                "is_active": "on",
            },
        )
        assert resposta.status_code == 302
        condicao = PaymentCondition.objects.get(name="Entrada + 45")
        assert condicao.days == "0,45" and condicao.parcelado
        assert AuditEvent.objects.filter(
            action=AuditAction.CREATE, entity_id=str(condicao.pk)
        ).exists()

    def test_prazo_invalido_volta_com_erro(self, client, usuario):
        client.force_login(usuario)
        resposta = client.post(
            reverse("commercial:condicao_nova"),
            {"name": "Torta", "days": "90,30", "display_order": 1},
        )
        assert resposta.status_code == 200
        assert "ordem crescente" in resposta.content.decode()
        assert not PaymentCondition.objects.filter(name="Torta").exists()

    def test_campo_nao_cadastra(self, client):
        campo = User.objects.create_user(username="c", password="x", role=Role.CAMPO)
        client.force_login(campo)
        assert client.get(reverse("commercial:condicao_nova")).status_code == 403
