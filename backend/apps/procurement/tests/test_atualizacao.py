"""Aceite dos materiais atualizacao/1–9 e decisões confirmadas na implementação."""

import datetime
from decimal import Decimal

import pytest
from django.db.models import Sum
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.core.exceptions import BusinessError
from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.finance.models import Component, Invoice
from apps.herd.models import HerdLedgerEntry
from apps.livestock.selectors import financeiro_dos_lotes
from apps.procurement import closing, commitments, freight
from apps.procurement.models import Commitment, FreightSupplement, ReceivingLine
from apps.procurement.tests.conftest import DATA_ACERTO
from apps.procurement.tests.test_reabertura import pagar
from apps.purchases.models import Purchase
from apps.purchases.services import custo_da_compra
from apps.reports import services as reports

pytestmark = pytest.mark.django_db
D = Decimal


def novo_frete(compromisso, usuario, transportador, **extra):
    return freight.criar(
        compromisso=compromisso,
        usuario=usuario,
        carrier=transportador,
        date=DATA_ACERTO,
        due_date=DATA_ACERTO + datetime.timedelta(days=10),
        amount=D("100.01"),
        trucks=1,
        truck="ABC1D23",
        **extra,
    )


def test_frete_posterior_preserva_animais_pagos_e_operacao_encerrada(
    acerto_aprovado, compromisso, gestor, financeiro, transportador
):
    compra = Purchase.objects.get(commitment_item__commitment=compromisso)
    animal = compra.invoices.get(component=Component.ANIMAIS)
    pagamento = pagar(
        animal, programador=gestor, aprovador=gestor, financeiro=financeiro
    )
    commitments.encerrar_operacao(compromisso, usuario=gestor)
    original = list(HerdLedgerEntry.objects.values_list("id", "quantity"))
    custo_inicial = custo_da_compra(compra).custo_aquisicao
    custos_iniciais = compra.cost_entries.filter(status=Status.CONFIRMADA).aggregate(
        t=Sum("amount")
    )["t"]
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    compra = Purchase.objects.get(pk=compra.pk)
    assert custo_da_compra(compra).custo_aquisicao == custo_inicial + D("100.01")
    assert financeiro_dos_lotes([compra.lot])[compra.lot_id][
        "aquisicao"
    ] == custo_inicial + D("100.01")
    assert compra.cost_entries.filter(status=Status.CONFIRMADA).aggregate(
        t=Sum("amount")
    )["t"] == custos_iniciais + D("100.01")
    assert list(HerdLedgerEntry.objects.values_list("id", "quantity")) == original
    animal.refresh_from_db()
    assert animal.paid_total == pagamento.amount
    assert f.invoice.amount == D("100.01") and f.invoice.payee_id == transportador.pk
    assert f.cost_entries.get().cost_center.name == "FRETE DE COMPRA"
    assert Commitment.objects.get(pk=compromisso.pk).encerrada
    with pytest.raises(BusinessError, match="já foi confirmado"):
        freight.confirmar(f, usuario=gestor)
    assert (
        Invoice.objects.filter(
            origin_settlement=acerto_aprovado, ref=f"complemento:{f.pk}"
        ).count()
        == 1
    )


def test_correcao_e_exclusao_do_complemento_nao_refazem_compra(
    acerto_aprovado, compromisso, gestor, transportador
):
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    ledger = HerdLedgerEntry.objects.count()
    f = freight.editar(
        f, {"amount": D("120.02")}, usuario=gestor, motivo="Nota corrigida"
    )
    assert f.cost_entries.filter(status=Status.CONFIRMADA).get().amount == D("120.02")
    assert f.invoice.amount == D("120.02")
    freight.excluir(f, usuario=gestor, motivo="Frete cancelado")
    assert not f.cost_entries.filter(status=Status.CONFIRMADA).exists()
    f.invoice.refresh_from_db()
    assert f.invoice.status == Status.EXCLUIDA
    assert (
        Purchase.objects.get(commitment_item__commitment=compromisso).status
        == Status.CONFIRMADA
    )
    assert HerdLedgerEntry.objects.count() == ledger
    assert AuditEvent.objects.filter(
        entity_type="FreightSupplement", entity_id=str(f.pk), reason="Nota corrigida"
    ).exists()


def test_baixa_do_frete_bloqueia_correcao_e_exclusao(
    acerto_aprovado, compromisso, gestor, financeiro, transportador
):
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    pagar(f.invoice, programador=gestor, aprovador=gestor, financeiro=financeiro)
    for acao in (
        lambda: freight.editar(
            f, {"amount": D("99")}, usuario=gestor, motivo="Corrigir"
        ),
        lambda: freight.excluir(f, usuario=gestor, motivo="Cancelar"),
    ):
        with pytest.raises(BusinessError, match="baixado"):
            acao()
    assert f.cost_entries.filter(status=Status.CONFIRMADA).get().amount == D("100.01")


def test_rateio_explicito_soma_centavos_e_recusa_compra_estranha(
    acerto_duplo, compromisso_duplo, gestor, transportador
):
    closing.aprovar_acerto(acerto_duplo, usuario=gestor)
    compras = list(
        Purchase.objects.filter(commitment_item__commitment=compromisso_duplo).order_by(
            "pk"
        )
    )
    with pytest.raises(BusinessError, match="Distribua"):
        novo_frete(compromisso_duplo, gestor, transportador)
    with pytest.raises(BusinessError, match="soma"):
        novo_frete(
            compromisso_duplo,
            gestor,
            transportador,
            distribuicao={compras[0].pk: D("30"), compras[1].pk: D("70")},
        )
    with pytest.raises(BusinessError, match="somente"):
        novo_frete(
            compromisso_duplo, gestor, transportador, distribuicao={999999: D("100.01")}
        )
    f = freight.confirmar(
        novo_frete(
            compromisso_duplo,
            gestor,
            transportador,
            distribuicao={compras[0].pk: D("30.01"), compras[1].pk: D("70")},
        ),
        usuario=gestor,
    )
    assert f.cost_entries.filter(status=Status.CONFIRMADA).aggregate(t=Sum("amount"))[
        "t"
    ] == D("100.01")
    assert f.invoice.amount == D("100.01")


def test_falha_na_geracao_de_custo_reverte_titulo(
    acerto_aprovado, compromisso, gestor, transportador, monkeypatch
):
    f = novo_frete(compromisso, gestor, transportador)

    def falhar(**kwargs):
        raise BusinessError("Falha de teste")

    monkeypatch.setattr(freight, "registrar_custo", falhar)
    with pytest.raises(BusinessError, match="Falha de teste"):
        freight.confirmar(f, usuario=gestor)
    assert not Invoice.objects.filter(ref=f"complemento:{f.pk}").exists()
    f.refresh_from_db()
    assert f.status == Status.RASCUNHO and f.invoice_id is None


def test_encerramento_exige_peso_e_conferencia_com_acerto_aprovado(
    acerto_aprovado, compromisso, gestor
):
    ReceivingLine.objects.filter(receiving__trip__commitment=compromisso).update(
        received_weight_kg=None
    )
    with pytest.raises(BusinessError, match="pesos"):
        commitments.encerrar_operacao(compromisso, usuario=gestor)
    compromisso.refresh_from_db()
    assert not compromisso.encerrada


def test_reabertura_nao_apaga_complemento_existente(
    acerto_aprovado, compromisso, gestor, transportador
):
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    with pytest.raises(BusinessError, match="complementos"):
        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Revisar")
    assert FreightSupplement.objects.get(pk=f.pk).status == Status.CONFIRMADA


def test_previsao_nao_gera_titulo_e_exporta_mesmos_valores(compromisso, gestor, season):
    antes = Invoice.objects.count()
    r = reports.montar_relatorio(gestor, "compromissos", season=season, farm=None)
    assert len(r.linhas) == 1
    assert r.linhas[0]["valor"] == D("45900")
    assert Invoice.objects.count() == antes
    assert compromisso.code in reports.csv_do_relatorio(r)
    assert reports.xlsx_do_relatorio(r).startswith(b"PK")


def test_filtros_compras_mantem_mes_totais_e_colunas(
    acerto_aprovado, compromisso, gestor, season, comissionado
):
    r = reports.montar_relatorio(
        gestor,
        "compras-do-periodo",
        season=season,
        farm=None,
        extras={
            "comprador": comissionado,
            "produtor": compromisso.seller,
            "operacao": compromisso,
        },
    )
    assert len(r.linhas) == 1
    assert r.linhas[0]["produtor"] == compromisso.seller.name
    assert comissionado.name in r.linhas[0]["comprador"]
    assert r.totais["cabecas"] == sum(linha["cabecas"] for linha in r.secoes[0].linhas)
    r = reports.montar_relatorio(
        gestor,
        "compras-do-periodo",
        season=season,
        farm=None,
        extras={"start": datetime.date(2025, 10, 1)},
    )
    assert r.linhas == [] and r.secoes[0].linhas == []


def test_frete_telas_permissoes_escopo_e_csrf(
    acerto_aprovado, compromisso, gestor, campo_baixao, transportador, client
):
    f = novo_frete(compromisso, gestor, transportador)
    client.force_login(gestor)
    for name, args in [
        ("frete_novo", [compromisso.pk]),
        ("frete_detalhe", [f.pk]),
        ("frete_editar", [compromisso.pk, f.pk]),
        ("frete_excluir", [f.pk]),
    ]:
        assert client.get(reverse("procurement:" + name, args=args)).status_code == 200
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(gestor)
    assert (
        csrf.post(reverse("procurement:frete_confirmar", args=[f.pk])).status_code
        == 403
    )
    client.force_login(campo_baixao)
    assert (
        client.get(reverse("procurement:frete_novo", args=[compromisso.pk])).status_code
        == 403
    )


def test_mapa_consolidado_compartilha_saldo_transferencias_e_acesso(
    acerto_aprovado,
    compromisso,
    gestor,
    campo_baixao,
    season,
    sao_francisco,
    baixao,
    lote_baixao,
    categoria_desmamados,
):
    from dataclasses import replace

    from apps.dashboards.bi import rebanho
    from apps.dashboards.bi.escopo import Escopo
    from apps.herd import services as herd
    from apps.herd.consolidation import consolidar
    from apps.herd.models import MovementType
    from apps.organizations.models import BusinessUnit

    u1 = BusinessUnit.objects.create(
        company=season.company, name="Unidade 520", code="520"
    )
    u2 = BusinessUnit.objects.create(
        company=season.company, name="Unidade 530", code="530"
    )
    sao_francisco.business_unit = u1
    sao_francisco.save()
    baixao.business_unit = u2
    baixao.save()
    compra = Purchase.objects.get(commitment_item__commitment=compromisso)
    herd.registrar_movimento(
        type=MovementType.TRANSFERENCIA,
        date=DATA_ACERTO,
        quantity=4,
        usuario=gestor,
        origin_farm=sao_francisco,
        origin_lot=compra.lot,
        origin_category=categoria_desmamados,
        destination_farm=baixao,
        destination_lot=lote_baixao,
        destination_category=categoria_desmamados,
    )
    geral = consolidar(gestor, company=season.company, ate=DATA_ACERTO)
    restrito = consolidar(campo_baixao, company=season.company, ate=DATA_ACERTO)
    assert geral["total"] == 10 and restrito["total"] == 4
    assert (
        consolidar(gestor, company=season.company, ate=DATA_ACERTO, unidade=u1)["total"]
        == 6
    )
    assert (
        consolidar(gestor, company=season.company, ate=DATA_ACERTO, unidade=u2)["total"]
        == 4
    )
    r = reports.montar_relatorio(
        gestor, "rebanho-consolidado", season=season, farm=None
    )
    assert r.totais["cabecas"] == geral["total"]
    assert sum(linha["cabecas"] for linha in r.secoes[0].linhas) == geral["total"]
    e = replace(Escopo.criar(gestor, season=season, hoje=DATA_ACERTO), unidade=u1)
    assert rebanho.montar(e).kpis[0].valor == "6"


def test_filtros_web_exportacao_e_pdf_revalidam_ids(
    acerto_aprovado, compromisso, gestor, season, client
):
    from django.http import Http404

    from apps.documents.services import (
        _extras_a_partir_dos_parametros,
        _parametros_para_gravar,
    )
    from apps.organizations.models import BusinessUnit
    from apps.reports.parametros import parametros_do_relatorio

    u = BusinessUnit.objects.create(
        company=season.company, code="520", name="Unidade 520"
    )
    farm = compromisso.destination_farm
    farm.business_unit = u
    farm.save()
    origem = {
        "unidade": str(u.pk),
        "produtor": str(compromisso.seller_id),
        "operacao": str(compromisso.pk),
        "tipo_operacao": "SEM_TIPO",
    }
    extras = parametros_do_relatorio(gestor, "compras-do-periodo", origem)
    serializado = _parametros_para_gravar(extras, season=season, farm=None)
    restaurado = _extras_a_partir_dos_parametros(serializado, gestor)
    assert restaurado["unidade"] == u and restaurado["operacao"] == compromisso
    for formato in ("", "csv", "xlsx"):
        client.force_login(gestor)
        url = reverse("reports:relatorio", args=["compras-do-periodo"])
        response = client.get(url, {**origem, "formato": formato})
        assert response.status_code == 200
    with pytest.raises(Http404):
        parametros_do_relatorio(gestor, "compras-do-periodo", {"fazenda": "999999"})
    assert (
        client.get(reverse("procurement:compromisso_lista"), origem).status_code == 200
    )
    assert (
        client.get(
            reverse("dashboards:dashboard_aba", args=["rebanho"]),
            {"unidade": str(u.pk)},
        ).status_code
        == 200
    )


def test_classificacao_obrigatoria_na_interface_e_preserva_historico(gestor):
    from apps.costs.forms import CostEntryForm
    from apps.procurement.forms import CommitmentForm
    from apps.purchases.forms import PurchaseForm

    for Form in (PurchaseForm, CommitmentForm, CostEntryForm):
        novo = Form({}, user=gestor, initial={"date": DATA_ACERTO})
        assert not novo.is_valid() and "operation_type" in novo.errors
        antigo = Form({}, user=gestor, initial={"operation_type": ""})
        antigo.is_valid()
        assert "operation_type" not in antigo.errors


def test_filtro_centro_detalhado_traz_apenas_frete(
    acerto_aprovado, compromisso, gestor, transportador, season
):
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    centro = f.cost_entries.get().cost_center
    r = reports.montar_relatorio(
        gestor,
        "custos-por-fazenda-detalhado",
        season=season,
        farm=None,
        extras={"centro_custo": centro},
    )
    assert r.totais["valor"] == sum(linha["valor"] for linha in r.linhas)
    assert all(linha["centro"] == "FRETE DE COMPRA" for linha in r.linhas)
    assert any(linha["referencia"] == str(f) for linha in r.linhas)
    assert {"unidade", "tipo_operacao", "compra", "referencia"} <= {
        c.chave for c in r.colunas
    }


@pytest.mark.django_db(transaction=True)
def test_confirmacao_concorrente_gera_um_titulo_e_um_custo(
    acerto_aprovado, compromisso, gestor, transportador
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    from apps.accounts.models import User

    f = novo_frete(compromisso, gestor, transportador)
    barreira = Barrier(2)

    def confirmar():
        close_old_connections()
        try:
            user = User.objects.get(pk=gestor.pk)
            registro = FreightSupplement.objects.get(pk=f.pk)
            barreira.wait(timeout=10)
            freight.confirmar(registro, usuario=user)
            return "confirmado"
        except BusinessError:
            return "recusado"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(lambda _: confirmar(), range(2)))
    assert sorted(resultados) == ["confirmado", "recusado"]
    assert Invoice.objects.filter(ref=f"complemento:{f.pk}").count() == 1
    assert (
        CostEntry.objects.filter(source_freight=f, status=Status.CONFIRMADA).count()
        == 1
    )


def test_classificacao_do_compromisso_chega_a_compra_e_custos(
    acerto, compromisso, gestor
):
    compromisso.operation_type = "BOI_BRASIL"
    compromisso.origin_property = "Fazenda de origem"
    compromisso.save()
    closing.aprovar_acerto(acerto, usuario=gestor)
    compra = Purchase.objects.get(commitment_item__commitment=compromisso)
    assert compra.operation_type == "BOI_BRASIL"
    assert compra.origin_property == "Fazenda de origem"
    assert set(compra.cost_entries.values_list("operation_type", flat=True)) == {
        "BOI_BRASIL"
    }


def test_relatorio_de_fretes_inclui_complemento_uma_vez(
    acerto_aprovado, compromisso, gestor, transportador, season
):
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    r = reports.montar_relatorio(
        gestor,
        "fretes-e-quebra",
        season=season,
        farm=None,
        extras={"operacao": compromisso},
    )
    extras = [linha for linha in r.linhas if linha["viagem"] == str(f)]
    assert len(extras) == 1 and extras[0]["realizado"] == D("100.01")
    assert r.totais["cabecas"] == 10


def test_mapa_cache_preserva_recorte_e_link_de_exportacao(
    acerto_aprovado, compromisso, gestor, season, baixao, client, settings
):
    from django.core.cache import cache
    from django.test import override_settings

    from apps.organizations.models import BusinessUnit

    u1 = BusinessUnit.objects.create(
        company=season.company, code="520", name="Unidade 520"
    )
    u2 = BusinessUnit.objects.create(
        company=season.company, code="530", name="Unidade 530"
    )
    baixao.business_unit = u2
    baixao.save()
    farm = compromisso.destination_farm
    farm.business_unit = u1
    farm.save()
    client.force_login(gestor)
    with override_settings(
        CACHE_DE_RESULTADOS=True,
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
        },
    ):
        cache.clear()
        url = reverse("dashboards:dashboard_aba", args=["rebanho"])
        primeira = client.get(
            url, {"unidade": u1.pk}, HTTP_HX_REQUEST="true"
        ).content.decode()
        segunda = client.get(
            url, {"unidade": u2.pk}, HTTP_HX_REQUEST="true"
        ).content.decode()
        repetida = client.get(
            url, {"unidade": u1.pk}, HTTP_HX_REQUEST="true"
        ).content.decode()
        assert '<p class="kpi-value">10<small>cabeças</small></p>' in primeira
        assert '<p class="kpi-value">0<small>cabeças</small></p>' in segunda
        assert primeira == repetida
        assert f"/relatorios/rebanho-consolidado/?unidade={u1.pk}" in primeira


def test_complemento_fora_da_fazenda_do_usuario_e_invisivel(
    acerto_aprovado, compromisso, gestor, transportador, baixao, client
):
    from apps.accounts.models import Role, User, UserFarmAccess

    f = novo_frete(compromisso, gestor, transportador)
    consulta = User.objects.create_user(
        username="consulta-frete", role=Role.CONSULTA, password="teste"
    )
    UserFarmAccess.objects.create(user=consulta, farm=baixao)
    client.force_login(consulta)
    assert (
        client.get(reverse("procurement:frete_detalhe", args=[f.pk])).status_code == 404
    )


def test_frete_posterior_pode_atravessar_a_virada_de_safra(
    acerto_aprovado, compromisso, gestor, transportador, season
):
    from apps.organizations.models import Season

    seguinte = Season.objects.create(
        company=season.company,
        name="2026/2027",
        start_date=datetime.date(2026, 7, 1),
        end_date=datetime.date(2027, 6, 30),
    )
    frete = freight.criar(
        compromisso=compromisso,
        usuario=gestor,
        carrier=transportador,
        date=datetime.date(2026, 7, 2),
        due_date=datetime.date(2026, 7, 5),
        amount=D("100"),
        trucks=1,
    )
    frete = freight.confirmar(frete, usuario=gestor)
    assert frete.invoice.season_id == seguinte.pk
    assert frete.cost_entries.get().season_id == seguinte.pk
    assert (
        Purchase.objects.get(commitment_item__commitment=compromisso).season_id
        == season.pk
    )


def test_titulo_do_frete_nao_pode_divergir_do_complemento(
    acerto_aprovado, compromisso, gestor, transportador, outro_transportador
):
    from apps.finance import services as financeiro

    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    for mudanca in (
        {"payee": outro_transportador},
        {"due_date": DATA_ACERTO + datetime.timedelta(days=40)},
    ):
        with pytest.raises(BusinessError, match="complemento de frete"):
            financeiro.editar_titulo(f.invoice, mudanca, usuario=gestor, motivo="Teste")
    with pytest.raises(BusinessError, match="complemento de frete"):
        financeiro.excluir_titulo(f.invoice, usuario=gestor, motivo="Teste")
    f.invoice.refresh_from_db()
    assert f.invoice.payee_id == f.carrier_id
    assert f.invoice.status == Status.CONFIRMADA
    assert f.invoice.due_date == f.due_date
    assert f.cost_entries.filter(status=Status.CONFIRMADA).get().amount == f.amount


def test_financeiro_nao_restaura_divida_de_complemento_excluido(
    acerto_aprovado, compromisso, gestor, transportador
):
    from apps.finance import services as financeiro

    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    freight.excluir(f, usuario=gestor, motivo="Cancelar")
    with pytest.raises(BusinessError, match="complemento de frete"):
        financeiro.restaurar_titulo(f.invoice, usuario=gestor)
    f.invoice.refresh_from_db()
    assert f.invoice.status == Status.EXCLUIDA
    assert not f.cost_entries.filter(status=Status.CONFIRMADA).exists()


def test_restaurar_frete_reaplica_uma_vez_custo_e_mesmo_titulo(
    acerto_aprovado, compromisso, gestor, transportador
):
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    compra = Purchase.objects.get(commitment_item__commitment=compromisso)
    custo = custo_da_compra(compra).custo_aquisicao
    razao = list(HerdLedgerEntry.objects.values_list("pk", "quantity"))
    titulo_id = f.invoice_id
    freight.excluir(f, usuario=gestor, motivo="Excluído por engano")
    f = freight.restaurar(f, usuario=gestor)
    assert f.status == Status.CONFIRMADA and f.invoice_id == titulo_id
    assert f.invoice.status == Status.CONFIRMADA
    assert f.cost_entries.filter(status=Status.CONFIRMADA).get().amount == f.amount
    assert custo_da_compra(Purchase.objects.get(pk=compra.pk)).custo_aquisicao == custo
    assert list(HerdLedgerEntry.objects.values_list("pk", "quantity")) == razao
    with pytest.raises(BusinessError, match="excluído"):
        freight.restaurar(f, usuario=gestor)
    assert f.cost_entries.filter(status=Status.CONFIRMADA).count() == 1


def test_restaurar_rascunho_de_frete_nao_gera_divida(
    acerto_aprovado, compromisso, gestor, transportador
):
    f = novo_frete(compromisso, gestor, transportador)
    freight.excluir(f, usuario=gestor, motivo="Engano")
    f = freight.restaurar(f, usuario=gestor)
    assert f.status == Status.RASCUNHO and f.invoice_id is None
    assert not f.cost_entries.exists()


def test_custo_da_compra_relacionada_inclui_frete_complementar(
    acerto_aprovado, compromisso, gestor, transportador
):
    from apps.procurement.models import CommitmentItem

    compra = Purchase.objects.get(commitment_item__commitment=compromisso)
    antes = custo_da_compra(compra).custo_aquisicao
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    relacionada = (
        CommitmentItem.objects.select_related("purchase").get(purchase=compra).purchase
    )
    assert not hasattr(relacionada, "supplemental_freight")
    assert custo_da_compra(relacionada).custo_aquisicao == antes + f.amount


def test_telas_do_financeiro_direcionam_correcao_ao_complemento(
    acerto_aprovado, compromisso, gestor, transportador, client
):
    f = freight.confirmar(
        novo_frete(compromisso, gestor, transportador), usuario=gestor
    )
    client.force_login(gestor)
    destino = reverse("procurement:frete_detalhe", args=[f.pk])
    response = client.get(reverse("finance:titulo_editar", args=[f.invoice_id]))
    assert response.status_code == 302 and response.url == destino
    detalhe = client.get(reverse("finance:titulo_detalhe", args=[f.invoice_id]))
    assert destino in detalhe.content.decode()
    assert detalhe.context["pode_editar"] is False
    assert detalhe.context["pode_excluir"] is False
    freight.excluir(f, usuario=gestor, motivo="Engano")
    restore = client.post(reverse("procurement:frete_restaurar", args=[f.pk]))
    assert restore.status_code == 302
    f.refresh_from_db()
    assert f.status == Status.CONFIRMADA
