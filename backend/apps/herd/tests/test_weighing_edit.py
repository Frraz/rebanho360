"""Pesagem se corrige, se exclui e se restaura — como qualquer lançamento
confirmado (regra 5 do CLAUDE.md). Antes, a lista levava ao lote e não havia como
mudar a data de uma pesagem lançada no dia errado."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.audit.models import AuditAction, AuditEvent
from apps.core.reversible import Status
from apps.herd import services
from apps.herd.models import Weighing, WeighingReason

pytestmark = pytest.mark.django_db

DATA = datetime.date(2025, 9, 18)


@pytest.fixture
def pesagem(baixao, lote_baixao, gestor):
    return services.registrar_pesagem(
        date=DATA,
        farm=baixao,
        lot=lote_baixao,
        reason=WeighingReason.CONFERENCIA,
        head_count=100,
        total_weight_kg=Decimal("20000"),
        usuario=gestor,
    )


def _dados(**extra):
    base = {
        "date": "2025-09-20",
        "reason": WeighingReason.CONFERENCIA,
        "head_count": "100",
        "total_weight_kg": "21000",
        "edit_reason": "Data lançada errada",
    }
    base.update(extra)
    return base


def test_a_lista_leva_a_pesagem_e_nao_ao_lote(client, gestor, pesagem):
    client.force_login(gestor)
    html = client.get(reverse("herd:pesagem_lista")).content.decode()
    assert reverse("herd:pesagem_detalhe", args=[pesagem.pk]) in html
    assert (
        reverse("livestock:lote_detalhe", args=[pesagem.lot_id])
        not in html.split('id="conteudo"')[1]
    )


def test_corrigir_a_data_faz_o_gmd_aparecer(client, gestor, baixao, lote_baixao):
    """O caso do cliente: duas pesagens no mesmo dia dão GMD "—"; corrigir uma
    para outro dia faz o GMD existir."""
    for peso in ("20000", "21000"):
        services.registrar_pesagem(
            date=DATA,
            farm=baixao,
            lot=lote_baixao,
            reason=WeighingReason.CONFERENCIA,
            head_count=100,
            total_weight_kg=Decimal(peso),
            usuario=gestor,
        )
    assert services.calcular_gmd(lote_baixao) is None

    depois = Weighing.objects.filter(total_weight_kg=Decimal("21000")).get()
    client.force_login(gestor)
    resposta = client.post(
        reverse("herd:pesagem_editar", args=[depois.pk]),
        _dados(date="2025-09-28", head_count="100", total_weight_kg="21000"),
    )

    assert resposta.status_code == 302
    depois.refresh_from_db()
    assert depois.date == datetime.date(2025, 9, 28)
    assert depois.version == 2
    # (210 − 200) kg ÷ 10 dias
    assert services.calcular_gmd(lote_baixao) == Decimal("1")
    evento = AuditEvent.objects.filter(action=AuditAction.UPDATE).latest("id")
    assert evento.reason == "Data lançada errada"


def test_corrigir_sem_motivo_e_recusado(client, gestor, pesagem):
    client.force_login(gestor)
    resposta = client.post(
        reverse("herd:pesagem_editar", args=[pesagem.pk]), _dados(edit_reason="")
    )
    assert resposta.status_code == 200
    pesagem.refresh_from_db()
    assert pesagem.version == 1


def test_corrigir_para_data_futura_e_recusado(client, gestor, pesagem):
    futuro = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    client.force_login(gestor)
    resposta = client.post(
        reverse("herd:pesagem_editar", args=[pesagem.pk]), _dados(date=futuro)
    )
    assert resposta.status_code == 200
    assert "data futura" in resposta.content.decode()
    pesagem.refresh_from_db()
    assert pesagem.date == DATA


def test_campo_nao_corrige_pesagem(client, campo_baixao, pesagem):
    client.force_login(campo_baixao)
    resposta = client.post(reverse("herd:pesagem_editar", args=[pesagem.pk]), _dados())
    assert resposta.status_code == 302
    pesagem.refresh_from_db()
    assert pesagem.version == 1


def test_pesagem_de_fazenda_fora_do_escopo_da_404(
    client, campo_baixao, sao_francisco, lote_sao_francisco, gestor
):
    fora = services.registrar_pesagem(
        date=DATA,
        farm=sao_francisco,
        lot=lote_sao_francisco,
        reason=WeighingReason.CONFERENCIA,
        head_count=10,
        total_weight_kg=Decimal("4000"),
        usuario=gestor,
    )
    client.force_login(campo_baixao)
    for nome in ("pesagem_detalhe", "pesagem_editar"):
        assert client.get(reverse(f"herd:{nome}", args=[fora.pk])).status_code == 404
    assert (
        client.post(reverse("herd:pesagem_excluir", args=[fora.pk])).status_code == 404
    )


def test_excluir_exige_motivo_e_tira_a_pesagem_do_gmd(
    client, gestor, baixao, lote_baixao, pesagem
):
    segunda = services.registrar_pesagem(
        date=datetime.date(2025, 9, 28),
        farm=baixao,
        lot=lote_baixao,
        reason=WeighingReason.CONFERENCIA,
        head_count=100,
        total_weight_kg=Decimal("21000"),
        usuario=gestor,
    )
    assert services.calcular_gmd(lote_baixao) is not None
    client.force_login(gestor)

    client.post(reverse("herd:pesagem_excluir", args=[segunda.pk]), {"motivo": ""})
    segunda.refresh_from_db()
    assert segunda.status == Status.CONFIRMADA

    client.post(
        reverse("herd:pesagem_excluir", args=[segunda.pk]), {"motivo": "Peso errado"}
    )
    segunda.refresh_from_db()
    assert segunda.status == Status.EXCLUIDA
    assert Weighing.objects.filter(pk=segunda.pk).exists()  # exclusão é lógica
    assert services.calcular_gmd(lote_baixao) is None

    client.post(reverse("herd:pesagem_restaurar", args=[segunda.pk]))
    segunda.refresh_from_db()
    assert segunda.status == Status.CONFIRMADA
    assert services.calcular_gmd(lote_baixao) is not None
