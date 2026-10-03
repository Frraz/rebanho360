import datetime
from decimal import Decimal

import pytest

from apps.accounts.models import Role, User, UserFarmAccess
from apps.finance import services as fin
from apps.partners.models import BankAccount, Partner, PartnerRole, PartnerRoleChoice
from apps.purchases import services as compras
from apps.sales.tests.conftest import *  # noqa: F401,F403

D = Decimal
DATA_COMPRA = datetime.date(2025, 9, 18)
HOJE = datetime.date.today()
AMANHA = HOJE + datetime.timedelta(days=1)


def _usuario(username, role, *fazendas):
    user = User.objects.create_user(username=username, password="x", role=role)
    for farm in fazendas:
        UserFarmAccess.objects.create(user=user, farm=farm, can_write=True)
    return user


@pytest.fixture
def financeiro(sao_francisco, baixao):
    return _usuario("financeiro", Role.FINANCEIRO, sao_francisco, baixao)


@pytest.fixture
def admin_fin():
    """Administrador: aprova pagamento e, como perfil superior, também pode
    executá-lo — mas não o que ele mesmo aprovou, havendo outro executor."""
    return _usuario("admin_fin", Role.ADMIN)


@pytest.fixture
def financeiro2(sao_francisco, baixao):
    return _usuario("financeiro2", Role.FINANCEIRO, sao_francisco, baixao)


@pytest.fixture
def consulta(sao_francisco):
    return _usuario("consulta", Role.CONSULTA, sao_francisco)


@pytest.fixture
def conta_do_vendedor(vendedor):
    return BankAccount.objects.create(
        partner=vendedor,
        bank_code="001",
        bank_name="Banco do Brasil",
        branch="1234",
        account="98765-4",
        is_default=True,
    )


@pytest.fixture
def cliente_frigorifico(frigorifico):
    return frigorifico


@pytest.fixture
def dados_compra(sao_francisco, categoria_desmamados, vendedor, conta_do_vendedor):
    """126 bezerros, como na compra de abril da planilha (R$ 388.080,00)."""
    return {
        "date": DATA_COMPRA,
        "seller": vendedor,
        "destination_farm": sao_francisco,
        "category": categoria_desmamados,
        "head_count": 126,
        "animal_value": D("388080.00"),
        "payment_days": 30,
    }


@pytest.fixture
def compra(escritorio, dados_compra):
    """Compra confirmada — e, junto, o título dos animais."""
    rascunho = compras.criar_compra(usuario=escritorio, **dados_compra)
    return compras.confirmar_compra(rascunho, usuario=escritorio)


@pytest.fixture
def titulo(compra):
    return compra.invoices.get(component="ANIMAIS")


def programado(titulo, usuario, data=AMANHA):
    return fin.programar_titulo(titulo, usuario=usuario, data=data)


def aprovado(titulo, programador, aprovador):
    fin.programar_titulo(titulo, usuario=programador, data=AMANHA)
    return fin.aprovar_titulo(titulo, usuario=aprovador)


@pytest.fixture
def titulo_aprovado(titulo, escritorio, gestor):
    return aprovado(titulo, escritorio, gestor)


def baixa(titulo, usuario, *, valor=None, documento="TED-1", data=None):
    return fin.baixar_titulo(
        titulo,
        usuario=usuario,
        date=data or HOJE,
        amount=valor if valor is not None else titulo.amount,
        method="TED",
        document=documento,
    )


@pytest.fixture
def venda(escritorio, dados_abate):
    from apps.sales import services as vendas

    dados = {**dados_abate, "payment_days": 15}
    rascunho = vendas.criar_venda(usuario=escritorio, **dados)
    return vendas.confirmar_venda(rascunho, usuario=escritorio)


@pytest.fixture
def titulo_a_receber(venda):
    return venda.invoices.get(component="VENDA")


@pytest.fixture
def outro_parceiro():
    parceiro = Partner.objects.create(name="Transportes Rápido")
    PartnerRole.objects.create(partner=parceiro, role=PartnerRoleChoice.TRANSPORTADOR)
    return parceiro
