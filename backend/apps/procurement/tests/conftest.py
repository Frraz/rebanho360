import datetime
from decimal import Decimal

import pytest

from apps.commercial.models import CarcassClass, CommissionRule, TaxType
from apps.commercial.tests.conftest import *  # noqa: F401,F403
from apps.livestock.models import AnimalCategory, Sex
from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
from apps.procurement import closing, commitments, grading, receivings, trips

D = Decimal
DATA_COMPROMISSO = datetime.date(2025, 9, 1)
DATA_RETIRADA = datetime.date(2025, 9, 3)
DATA_RECEBIMENTO = datetime.date(2025, 9, 4)
DATA_ACERTO = datetime.date(2025, 9, 20)


def _parceiro(nome, papel):
    parceiro = Partner.objects.create(name=nome)
    PartnerRole.objects.create(partner=parceiro, role=papel)
    return parceiro


@pytest.fixture
def produtor():
    return _parceiro("Waldemar Secchi", PartnerRoleChoice.PRODUTOR)


@pytest.fixture
def frigorifico():
    return _parceiro("COPERFRIGU", PartnerRoleChoice.FRIGORIFICO)


@pytest.fixture
def transportador():
    return _parceiro("Transportes Tocantins", PartnerRoleChoice.TRANSPORTADOR)


@pytest.fixture
def outro_transportador():
    return _parceiro("Frota Araguaia", PartnerRoleChoice.TRANSPORTADOR)


@pytest.fixture
def categoria_vaca():
    return AnimalCategory.objects.create(
        name="Fêmeas + 36 meses", sex=Sex.FEMEA, age_order=5, display_order=11
    )


@pytest.fixture
def classe(db):
    return CarcassClass.objects.get(code="MEDIANA")


@pytest.fixture
def classe_escassa(db):
    return CarcassClass.objects.get(code="ESCASSA")


def dados_item(categoria, **extra):
    """Item por @ de carcaça, com as cinco faixas do contrato do legado."""
    return {
        "category": categoria,
        "head_count": 10,
        "avg_weight_kg": D("480"),
        "price_basis": "ARROBA",
        "price_band_1": D("216.00"),
        "price_band_2": D("237.60"),
        "price_band_3": D("248.40"),
        "price_band_4": D("270.00"),
        "price_band_5": D("270.00"),
        "expected_arrobas": D("17.00"),
        "expected_band": 4,
    } | extra


@pytest.fixture
def dados_compromisso(produtor, sao_francisco, comissionado, categoria_desmamados):
    return {
        "date": DATA_COMPROMISSO,
        "seller": produtor,
        "destination_farm": sao_francisco,
        "commissioned": comissionado,
        "payment_days": 30,
        "pickup_date": DATA_RETIRADA,
        "slaughter_date": datetime.date(2025, 9, 10),
        "trucks": 1,
        "distance_km": 100,
        "itens": [dados_item(categoria_desmamados)],
    }


@pytest.fixture
def criar_compromisso(escritorio, dados_compromisso):
    def _criar(**sobrescrever):
        dados = dados_compromisso | sobrescrever
        itens = dados.pop("itens")
        return commitments.criar_compromisso(usuario=escritorio, itens=itens, **dados)

    return _criar


@pytest.fixture
def rascunho(criar_compromisso):
    return criar_compromisso()


@pytest.fixture
def compromisso(rascunho, escritorio, gestor):
    """Aprovado, sem regra de comissão cadastrada."""
    return commitments.aprovar_compromisso(rascunho, usuario=gestor)


@pytest.fixture
def item(compromisso):
    return compromisso.items.get(number=1)


@pytest.fixture
def viagem(escritorio, compromisso, item, transportador):
    return trips.criar_viagem(
        usuario=escritorio,
        compromisso=compromisso,
        pickup_date=DATA_RETIRADA,
        carrier=transportador,
        freight_criterion="POR_CABECA",
        freight_rate=D("50"),
        cargas=[
            {
                "item": item,
                "planned_qty": 10,
                "shipped_qty": 10,
                "origin_weight_kg": D("5000"),
            }
        ],
    )


@pytest.fixture
def recebimento(escritorio, viagem):
    carga = viagem.loads.get()
    return receivings.criar_recebimento(
        usuario=escritorio,
        viagem=viagem,
        date=DATA_RECEBIMENTO,
        linhas=[
            {
                "load": carga,
                "received_qty": 10,
                "received_weight_kg": D("4900"),
            }
        ],
    )


@pytest.fixture
def romaneio(escritorio, item, classe, recebimento):
    """10 cabeças, 2.400 kg de carcaça na Faixa 4 (R$ 270,00/@): 160 @ →
    R$ 43.200,00."""
    return grading.registrar_romaneio(
        item,
        [
            {
                "carcass_class": classe,
                "band": 4,
                "head_count": 10,
                "carcass_weight_kg": D("2400"),
            }
        ],
        usuario=escritorio,
    )


@pytest.fixture
def acerto(escritorio, compromisso, romaneio):
    return closing.criar_acerto(
        usuario=escritorio, compromisso=compromisso, date=DATA_ACERTO
    )


@pytest.fixture
def aprovar(gestor):
    def _aprovar(acerto):
        return closing.aprovar_acerto(acerto, usuario=gestor)

    return _aprovar


@pytest.fixture
def acerto_aprovado(acerto, aprovar):
    return aprovar(acerto)


def tipo(nome):
    return TaxType.objects.get(name=nome)


@pytest.fixture
def regra_de_comissao(db):
    return CommissionRule.objects.create(
        type="PERCENTUAL",
        base="BRUTO",
        value=D("1"),
        valid_from=datetime.date(2025, 1, 1),
    )


# --- apoio aos testes de aprovação e reabertura -------------------------


@pytest.fixture
def financeiro(sao_francisco, baixao):
    from apps.accounts.models import Role, User, UserFarmAccess

    user = User.objects.create_user(
        username="financeiro", password="x", role=Role.FINANCEIRO
    )
    for farm in (sao_francisco, baixao):
        UserFarmAccess.objects.create(user=user, farm=farm, can_write=True)
    return user


@pytest.fixture
def saldo_do_lote():
    """Cabeças do lote até uma data — o saldo é derivado do razão."""
    from django.db.models import Sum

    from apps.herd.models import HerdLedgerEntry

    def _saldo(lote, ate=None):
        entradas = HerdLedgerEntry.objects.filter(lot=lote)
        if ate is not None:
            entradas = entradas.filter(date__lte=ate)
        return entradas.aggregate(total=Sum("quantity"))["total"] or 0

    return _saldo


@pytest.fixture
def compromisso_duplo(
    gestor,
    escritorio,
    criar_compromisso,
    categoria_desmamados,
    categoria_vaca,
    transportador,
    classe,
):
    """Dois itens, duas categorias: o que `Purchase` sozinha não comportaria.

    Item 1 — 10 desmamados por @ (romaneio: 2.400 kg a R$ 270 → R$ 43.200).
    Item 2 — 20 vacas por cabeça a R$ 3.000; chegam 19 (R$ 57.000).
    Uma viagem, frete fechado de R$ 1.000,00.
    """
    c = commitments.aprovar_compromisso(
        criar_compromisso(
            itens=[
                dados_item(categoria_desmamados),
                dados_item(
                    categoria_vaca,
                    head_count=20,
                    price_basis="CABECA",
                    unit_price=D("3000"),
                    expected_band=None,
                    expected_arrobas=None,
                ),
            ]
        ),
        usuario=gestor,
    )
    primeiro, segundo = c.items.order_by("number")
    viagem = trips.criar_viagem(
        usuario=escritorio,
        compromisso=c,
        pickup_date=DATA_RETIRADA,
        carrier=transportador,
        freight_criterion="POR_VIAGEM",
        freight_rate=D("1000"),
        cargas=[
            {
                "item": primeiro,
                "planned_qty": 10,
                "shipped_qty": 10,
                "origin_weight_kg": D("5000"),
            },
            {
                "item": segundo,
                "planned_qty": 20,
                "shipped_qty": 20,
                "origin_weight_kg": D("11000"),
            },
        ],
    )
    cargas = {carga.item_id: carga for carga in viagem.loads.all()}
    receivings.criar_recebimento(
        usuario=escritorio,
        viagem=viagem,
        date=DATA_RECEBIMENTO,
        linhas=[
            {
                "load": cargas[primeiro.pk],
                "received_qty": 10,
                "received_weight_kg": D("4900"),
            },
            {
                "load": cargas[segundo.pk],
                "received_qty": 19,
                "received_weight_kg": D("10400"),
            },
        ],
    )
    grading.registrar_romaneio(
        primeiro,
        [
            {
                "carcass_class": classe,
                "band": 4,
                "head_count": 10,
                "carcass_weight_kg": D("2400"),
            }
        ],
        usuario=escritorio,
    )
    return c


@pytest.fixture
def acerto_duplo(escritorio, compromisso_duplo):
    """Dois itens: o frete (R$ 1.000,00) é **distribuído pelo usuário** — aqui,
    por cabeça recebida (344,83 / 655,17), como a tela sugeriria."""
    acerto = closing.criar_acerto(
        usuario=escritorio, compromisso=compromisso_duplo, date=DATA_ACERTO
    )
    primeiro, segundo = compromisso_duplo.items.order_by("number")
    closing.registrar_distribuicao(
        acerto,
        [
            {"item": primeiro.pk, "freight_value": D("344.83")},
            {"item": segundo.pk, "freight_value": D("655.17")},
        ],
        usuario=escritorio,
    )
    return acerto
