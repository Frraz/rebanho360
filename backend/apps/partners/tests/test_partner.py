"""F1-03: Parceiro multi-papel, autocomplete via busca e alteração de
dado bancário auditada — ver
docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-03."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import AuditAction, AuditEvent
from apps.partners import services
from apps.partners.models import BankAccount, Partner, PartnerRole, PartnerRoleChoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def escritorio():
    return User.objects.create_user(
        username="escritorio", password="x", role=Role.ESCRITORIO
    )


@pytest.fixture
def waldemar():
    return Partner.objects.create(
        name="Waldemar Secchi", document="275.974.740-91", city="Alvorada"
    )


class TestParceiroMultiPapel:
    def test_mesmo_parceiro_exerce_dois_papeis_sem_duplicar_cadastro(
        self, waldemar, escritorio
    ):
        services.salvar_parceiro(
            waldemar,
            [PartnerRoleChoice.PRODUTOR, PartnerRoleChoice.COMPRADOR],
            usuario=escritorio,
            criando=False,
        )

        assert Partner.objects.count() == 1
        papeis = set(waldemar.roles.values_list("role", flat=True))
        assert papeis == {PartnerRoleChoice.PRODUTOR, PartnerRoleChoice.COMPRADOR}

    def test_desmarcar_papel_remove_a_linha(self, waldemar, escritorio):
        PartnerRole.objects.create(partner=waldemar, role=PartnerRoleChoice.PRODUTOR)
        PartnerRole.objects.create(partner=waldemar, role=PartnerRoleChoice.COMPRADOR)

        services.salvar_parceiro(
            waldemar, [PartnerRoleChoice.PRODUTOR], usuario=escritorio, criando=False
        )

        assert list(waldemar.roles.values_list("role", flat=True)) == [
            PartnerRoleChoice.PRODUTOR
        ]

    def test_criar_parceiro_pela_tela_com_dois_papeis(self, client, escritorio):
        client.force_login(escritorio)
        response = client.post(
            reverse("partners:novo"),
            {
                "name": "Waldemar Secchi Filho",
                "document": "812.334.120-04",
                "city": "Gurupi",
                "roles": [PartnerRoleChoice.FORNECEDOR, PartnerRoleChoice.COMPRADOR],
            },
        )
        assert response.status_code == 302
        parceiro = Partner.objects.get(name="Waldemar Secchi Filho")
        assert parceiro.roles.count() == 2


class TestBuscaDeParceiros:
    def test_busca_encontra_por_nome_documento_ou_cidade(self, waldemar):
        from apps.partners.selectors import buscar_parceiros

        assert waldemar in buscar_parceiros("secchi")
        assert waldemar in buscar_parceiros("275.974.740")
        assert waldemar in buscar_parceiros("alvorada")
        assert waldemar not in buscar_parceiros("inexistente")

    def test_busca_vazia_nao_devolve_lista_gigante(self, waldemar):
        from apps.partners.selectors import buscar_parceiros

        assert buscar_parceiros("").count() == 0

    def test_tela_de_busca_devolve_fragmento_htmx(self, client, waldemar, escritorio):
        client.force_login(escritorio)
        response = client.get(reverse("partners:buscar"), {"q": "secchi"})
        assert response.status_code == 200
        assert b"Waldemar Secchi" in response.content
        assert b"<html" not in response.content  # fragmento, não página inteira


class TestContaBancaria:
    def test_criar_primeira_conta_nao_exige_motivo(self, client, waldemar, escritorio):
        client.force_login(escritorio)
        response = client.post(
            reverse("partners:conta_nova", args=[waldemar.pk]),
            {
                "bank_code": "001",
                "bank_name": "Banco do Brasil",
                "branch": "1234-5",
                "account": "98765-4",
                "account_type": "CORRENTE",
                "is_default": "on",
            },
        )
        assert response.status_code == 302
        assert BankAccount.objects.filter(partner=waldemar).exists()
        assert AuditEvent.objects.filter(
            entity_type="BankAccount", action=AuditAction.CREATE
        ).exists()

    def test_editar_conta_sem_motivo_e_recusado(self, client, waldemar, escritorio):
        conta = BankAccount.objects.create(
            partner=waldemar, bank_name="Banco do Brasil", account="1"
        )
        client.force_login(escritorio)
        response = client.post(
            reverse("partners:conta_editar", args=[conta.pk]),
            {
                "bank_code": "001",
                "bank_name": "Banco do Brasil",
                "branch": "1234-5",
                "account": "99999-9",
                "account_type": "CORRENTE",
            },
        )
        assert response.status_code == 200  # re-renderiza o form com erro
        conta.refresh_from_db()
        assert conta.account == "1"  # não alterou

    def test_editar_conta_com_motivo_gera_auditoria_de_alta_severidade(
        self, client, waldemar, escritorio
    ):
        conta = BankAccount.objects.create(
            partner=waldemar, bank_name="Banco do Brasil", account="1"
        )
        client.force_login(escritorio)
        response = client.post(
            reverse("partners:conta_editar", args=[conta.pk]),
            {
                "bank_code": "001",
                "bank_name": "Banco do Brasil",
                "branch": "1234-5",
                "account": "99999-9",
                "account_type": "CORRENTE",
                "reason": "Conta encerrada, cliente informou a nova",
            },
        )
        assert response.status_code == 302
        conta.refresh_from_db()
        assert conta.account == "99999-9"

        evento = AuditEvent.objects.get(
            entity_type="BankAccount",
            entity_id=str(conta.pk),
            action=AuditAction.UPDATE,
        )
        assert evento.reason == "Conta encerrada, cliente informou a nova"
        assert "account" in evento.changed_fields

    def test_marcar_conta_como_padrao_desmarca_as_outras(self, waldemar, escritorio):
        conta1 = BankAccount.objects.create(
            partner=waldemar, bank_name="A", account="1", is_default=True
        )
        conta2 = BankAccount.objects.create(
            partner=waldemar, bank_name="B", account="2"
        )

        services.salvar_conta_bancaria(
            conta2, usuario=escritorio, criando=False, motivo="corrigir conta padrão"
        )
        conta2.is_default = True
        services.salvar_conta_bancaria(
            conta2, usuario=escritorio, criando=False, motivo="tornar padrão"
        )

        conta1.refresh_from_db()
        assert conta1.is_default is False
