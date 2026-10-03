"""F5-12 — aprovar o acerto: uma compra por item, rateio, títulos com
favorecido e a trava de fechamento."""

import datetime
import threading

import pytest
from django.db import connection

from apps.audit.models import AuditAction, AuditEvent
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.finance.models import Invoice
from apps.herd.models import HerdLedgerEntry
from apps.procurement import closing, commitments, grading, receivings, trips
from apps.procurement.settlement import calcular_acerto
from apps.procurement.tests.conftest import DATA_ACERTO, DATA_RECEBIMENTO, D, tipo
from apps.purchases import services as compras
from apps.purchases.models import Purchase

pytestmark = pytest.mark.django_db


class TestAprovar:
    def test_aprovar_gera_uma_compra_por_item_recebido(
        self, acerto_duplo, aprovar, compromisso_duplo
    ):
        aprovar(acerto_duplo)

        primeiro, segundo = compromisso_duplo.items.order_by("number")
        assert Purchase.objects.count() == 2
        assert primeiro.purchase.category == primeiro.category
        assert segundo.purchase.category == segundo.category
        assert {p.status for p in Purchase.objects.all()} == {Status.CONFIRMADA}

    def test_valores_das_compras_vem_do_acerto(
        self, acerto_duplo, aprovar, compromisso_duplo
    ):
        aprovar(acerto_duplo)
        primeiro, segundo = compromisso_duplo.items.order_by("number")
        a, b = primeiro.purchase, segundo.purchase

        assert (a.head_count, a.animal_value, a.total_weight_kg) == (
            10,
            D("43200.00"),
            D("4900"),
        )
        assert (b.head_count, b.animal_value, b.total_weight_kg) == (
            19,
            D("57000.00"),
            D("10400"),
        )
        # o frete do contrato inteiro, como o usuário o distribuiu
        assert (a.freight_value, b.freight_value) == (D("344.83"), D("655.17"))
        assert a.freight_value + b.freight_value == D("1000.00")

    def test_compra_nasce_com_data_do_primeiro_recebimento(
        self, acerto_duplo, aprovar, compromisso_duplo
    ):
        """Pendência #24: o saldo histórico fica certo para trás."""
        aprovar(acerto_duplo)
        for item in compromisso_duplo.items.all():
            assert item.purchase.date == DATA_RECEBIMENTO

    def test_o_que_a_compra_de_sempre_faz_acontece(
        self, acerto_aprovado, compromisso, saldo_do_lote
    ):
        compra = compromisso.items.get().purchase
        assert saldo_do_lote(compra.lot) == 10  # rebanho
        assert (
            CostEntry.objects.filter(
                source_purchase=compra, status=Status.CONFIRMADA
            ).count()
            == 2
        )  # animais + frete
        # a compra só gera o título dos animais; o frete tem título próprio, do acerto
        assert Invoice.objects.filter(origin_purchase=compra).count() == 1
        assert (
            Invoice.objects.filter(
                origin_settlement=acerto_aprovado, component="FRETE"
            ).count()
            == 1
        )
        assert compra.lot.origin_purchase_id == compra.pk

    def test_o_gado_so_entra_no_rebanho_na_aprovacao(
        self, acerto, aprovar, compromisso
    ):
        assert not HerdLedgerEntry.objects.exists()  # recebido e em acerto
        aprovar(acerto)
        assert HerdLedgerEntry.objects.exists()

    def test_usa_o_lote_existente_do_item(
        self,
        escritorio,
        criar_compromisso,
        categoria_desmamados,
        lote_sao_francisco,
        transportador,
        classe,
        gestor,
    ):
        from apps.procurement.tests.conftest import dados_item

        c = commitments.aprovar_compromisso(
            criar_compromisso(
                itens=[dados_item(categoria_desmamados, lot=lote_sao_francisco)]
            ),
            usuario=gestor,
        )
        item = c.items.get()
        v = trips.criar_viagem(
            usuario=escritorio,
            compromisso=c,
            pickup_date=datetime.date(2025, 9, 3),
            cargas=[{"item": item, "planned_qty": 10, "shipped_qty": 10}],
        )
        receivings.criar_recebimento(
            usuario=escritorio,
            viagem=v,
            date=DATA_RECEBIMENTO,
            linhas=[{"load": v.loads.get(), "received_qty": 10}],
        )
        grading.registrar_romaneio(
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
        acerto = closing.criar_acerto(
            usuario=escritorio, compromisso=c, date=DATA_ACERTO
        )
        closing.aprovar_acerto(acerto, usuario=gestor)

        item.refresh_from_db()
        assert item.purchase.lot == lote_sao_francisco

    def test_item_nao_recebido_nao_vira_compra(
        self, escritorio, compromisso_duplo, gestor, categoria_vaca
    ):
        segundo = compromisso_duplo.items.get(number=2)
        recebimento = receivings.Receiving.objects.get()
        linha = recebimento.lines.get(load__item=segundo)
        receivings.editar_recebimento(
            recebimento,
            {},
            [
                {
                    "id": ln.pk,
                    "load": ln.load,
                    "received_qty": ln.received_qty,
                    "received_weight_kg": ln.received_weight_kg,
                }
                for ln in recebimento.lines.all()
                if ln.pk != linha.pk
            ],
            usuario=escritorio,
            motivo="As vacas não chegaram",
        )
        acerto = closing.criar_acerto(
            usuario=escritorio, compromisso=compromisso_duplo, date=DATA_ACERTO
        )
        closing.aprovar_acerto(acerto, usuario=gestor)

        assert Purchase.objects.count() == 1
        segundo.refresh_from_db()
        assert segundo.purchase is None

    def test_aprovar_audita_e_registra_a_linha_do_tempo(self, acerto_aprovado):
        from apps.audit.models import OperationEvent

        assert AuditEvent.objects.filter(
            entity_type="Settlement", action=AuditAction.CONFIRM
        ).exists()
        evento = OperationEvent.objects.get(entity_type="Settlement")
        assert evento.title == "Acerto aprovado"
        assert acerto_aprovado.approved_by is not None

    def test_aprovar_duas_vezes_e_recusado(self, acerto_aprovado, gestor):
        with pytest.raises(BusinessError, match="já foi aprovado"):
            closing.aprovar_acerto(acerto_aprovado, usuario=gestor)

    def test_escritorio_nao_aprova_o_que_lancou(self, acerto, escritorio):
        with pytest.raises(BusinessError, match="administrador ou gestor"):
            closing.aprovar_acerto(acerto, usuario=escritorio)
        acerto.refresh_from_db()
        assert acerto.status == Status.RASCUNHO

    def test_campo_nao_aprova(self, acerto, campo_baixao):
        with pytest.raises(BusinessError, match="permissão"):
            closing.aprovar_acerto(acerto, usuario=campo_baixao)

    def test_admin_aprova(self, acerto, admin):
        assert closing.aprovar_acerto(acerto, usuario=admin).status == Status.CONFIRMADA

    def test_tudo_ou_nada_se_a_segunda_compra_falha(
        self, acerto_duplo, gestor, compromisso_duplo, monkeypatch
    ):
        """Falhou no meio, nada entrou: nem a primeira compra."""
        original = compras.confirmar_compra
        chamadas = []

        def falha_na_segunda(compra, **kw):
            chamadas.append(compra.pk)
            if len(chamadas) == 2:
                raise BusinessError("falha simulada")
            return original(compra, **kw)

        monkeypatch.setattr(compras, "confirmar_compra", falha_na_segunda)
        with pytest.raises(BusinessError, match="falha simulada"):
            closing.aprovar_acerto(acerto_duplo, usuario=gestor)

        assert Purchase.objects.count() == 0
        assert not HerdLedgerEntry.objects.exists()
        acerto_duplo.refresh_from_db()
        assert acerto_duplo.status == Status.RASCUNHO
        assert not any(i.purchase_id for i in compromisso_duplo.items.all())


class TestComissaoEFavorecidos:
    """Frete por **viagem**, comissão por **comprador**, tributo por **linha**:
    cada um com favorecido e vencimento próprios, gerados pelo acerto."""

    def test_comissao_vira_titulo_com_favorecido(
        self, acerto, aprovar, compromisso, escritorio, comissionado, transportador
    ):
        commitments.definir_comissao(
            compromisso,
            tipo="PERCENTUAL",
            valor=D("1"),
            favorecido=comissionado,
            usuario=escritorio,
        )
        aprovar(acerto)
        compra = compromisso.items.get().purchase
        do_acerto = {
            t.component: t for t in Invoice.objects.filter(origin_settlement=acerto)
        }

        assert compra.commission_value == D("432.00")  # o custo do lote
        assert do_acerto["COMISSAO"].payee == comissionado
        assert do_acerto["COMISSAO"].amount == D("432.00")
        assert do_acerto["FRETE"].payee == transportador
        animais = Invoice.objects.get(origin_purchase=compra)
        assert animais.component == "ANIMAIS" and animais.payee == compromisso.seller

    def test_cada_comprador_tem_o_proprio_titulo_e_vencimento(
        self, acerto, aprovar, compromisso, escritorio, comissionado, outro_comissionado
    ):
        commitments.definir_comissao(
            compromisso,
            tipo="PERCENTUAL",
            valor=D("1"),
            favorecido=comissionado,
            vencimento=datetime.date(2025, 10, 10),
            usuario=escritorio,
        )
        commitments.definir_comissao(
            compromisso,
            tipo="VALOR",
            valor=D("250"),
            favorecido=outro_comissionado,
            usuario=escritorio,
        )
        aprovar(acerto)
        titulos = Invoice.objects.filter(
            origin_settlement=acerto, component="COMISSAO"
        ).order_by("amount")

        assert [(t.payee, t.amount) for t in titulos] == [
            (outro_comissionado, D("250.00")),
            (comissionado, D("432.00")),
        ]
        # vencimento próprio: o de um comprador não é o do outro
        assert titulos[1].due_date == datetime.date(2025, 10, 10)
        assert titulos[0].due_date == acerto.date
        # o custo do lote soma as duas comissões
        assert compromisso.items.get().purchase.commission_value == D("682.00")

    def test_frete_e_um_titulo_por_viagem_ao_transportador_dela(
        self, acerto_aprovado, compromisso, transportador
    ):
        titulo = Invoice.objects.get(
            origin_settlement=acerto_aprovado, component="FRETE"
        )
        assert titulo.payee == transportador and titulo.amount == D("500.00")
        assert titulo.ref.startswith("viagem:")

    def test_tributo_vira_titulo_com_o_favorecido_que_o_usuario_informou(
        self, acerto, aprovar, compromisso, escritorio, outro_comissionado
    ):
        closing.registrar_linhas(
            acerto,
            [
                {
                    "tax_type": tipo("Funrural"),
                    "amount": D("300"),
                    "rate_percent": D("1.5"),
                    "base_amount": D("20000"),
                    "payee": outro_comissionado,
                    "due_date": datetime.date(2025, 10, 20),
                },
                {"tax_type": tipo("GTA"), "amount": D("40")},
            ],
            usuario=escritorio,
        )
        aprovar(acerto)
        titulos = {
            t.amount: t
            for t in Invoice.objects.filter(
                origin_settlement=acerto, component="IMPOSTOS"
            )
        }
        # o sistema não presume alíquota nem favorecido: usa o que foi digitado
        assert titulos[D("300.00")].payee == outro_comissionado
        assert titulos[D("300.00")].due_date == datetime.date(2025, 10, 20)
        assert titulos[D("40.00")].payee is None
        assert len(titulos) == 2

    def test_reabrir_cancela_os_titulos_do_acerto_e_aprovar_de_novo_nao_duplica(
        self, acerto, aprovar, compromisso, escritorio, gestor
    ):
        aprovar(acerto)
        antes = Invoice.objects.filter(
            origin_settlement=acerto, status=Status.CONFIRMADA
        ).count()
        assert antes == 1  # o frete
        closing.reabrir_acerto(acerto, usuario=gestor, motivo="conferência")
        assert not Invoice.objects.filter(
            origin_settlement=acerto, status=Status.CONFIRMADA
        ).exists()
        acerto.refresh_from_db()
        closing.aprovar_acerto(acerto, usuario=gestor)
        assert (
            Invoice.objects.filter(
                origin_settlement=acerto, status=Status.CONFIRMADA
            ).count()
            == 1
        )
        assert Invoice.objects.filter(origin_settlement=acerto).count() == 1

    def test_pagamento_de_titulo_do_acerto_bloqueia_a_reabertura(
        self, acerto_aprovado, gestor, financeiro
    ):
        from apps.finance import services as fin

        frete = Invoice.objects.get(
            origin_settlement=acerto_aprovado, component="FRETE"
        )
        hoje = datetime.date.today()
        fin.programar_titulo(frete, usuario=gestor, data=hoje)
        fin.aprovar_titulo(frete, usuario=gestor)
        fin.baixar_titulo(
            frete,
            usuario=financeiro,
            date=hoje,
            amount=frete.amount,
            method="TED",
            document="TED-FRETE-1",
        )
        with pytest.raises(BlockingDependencyError, match="pagamento"):
            closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="x")

    def test_adiantamento_e_credito_reduzem_so_o_titulo_dos_animais(
        self, acerto, aprovar, compromisso, escritorio
    ):
        closing.registrar_linhas(
            acerto,
            [
                {"tax_type": tipo("Adiantamento"), "amount": D("5000")},
                {"tax_type": tipo("Crédito GR-3"), "amount": D("200")},
            ],
            usuario=escritorio,
        )
        aprovar(acerto)
        compra = compromisso.items.get().purchase
        titulo = Invoice.objects.get(origin_purchase=compra, component="ANIMAIS")

        assert compra.animal_value == D("43200.00")  # o custo não muda
        assert titulo.amount == D("38000.00")  # 43.200 − 5.000 − 200

    def test_desconto_reduz_a_compra_e_o_titulo(
        self, acerto, aprovar, compromisso, escritorio
    ):
        closing.registrar_linhas(
            acerto,
            [{"tax_type": tipo("Desconto"), "amount": D("1200")}],
            usuario=escritorio,
        )
        aprovar(acerto)
        compra = compromisso.items.get().purchase
        assert compra.animal_value == D("42000.00")
        assert Invoice.objects.get(
            origin_purchase=compra, component="ANIMAIS"
        ).amount == D("42000.00")

    def test_custo_de_aquisicao_da_compra_e_o_do_acerto(
        self, acerto, aprovar, compromisso, escritorio
    ):
        commitments.definir_comissao(
            compromisso,
            tipo="PERCENTUAL",
            base="BRUTO",
            valor=D("1"),
            favorecido=compromisso.commissioned,
            usuario=escritorio,
        )
        closing.registrar_linhas(
            acerto,
            [{"tax_type": tipo("Funrural"), "amount": D("300")}],
            usuario=escritorio,
        )
        esperado = calcular_acerto(compromisso).custo_aquisicao
        aprovar(acerto)
        from apps.purchases.services import custo_da_compra

        assert (
            custo_da_compra(compromisso.items.get().purchase).custo_aquisicao
            == esperado
        )

    def test_compra_direta_nao_e_afetada_pelo_gancho(
        self, escritorio, dados_compra_direta
    ):
        compra = compras.criar_compra(usuario=escritorio, **dados_compra_direta)
        compras.confirmar_compra(compra, usuario=escritorio)
        titulos = {t.component: t for t in compra.invoices.all()}
        assert titulos["FRETE"].payee is None  # "a definir", como na Fase 4: só o
        # acerto sabe a quem pagar o frete
        assert titulos["ANIMAIS"].amount == dados_compra_direta["animal_value"]


@pytest.fixture
def dados_compra_direta(sao_francisco, categoria_desmamados, produtor):
    return {
        "date": datetime.date(2025, 9, 18),
        "seller": produtor,
        "destination_farm": sao_francisco,
        "category": categoria_desmamados,
        "head_count": 50,
        "animal_value": D("100000"),
        "freight_value": D("800"),
    }


class TestCompraDoCicloNaoSeCorrigeDireto:
    def test_editar_direto_e_recusado_com_o_caminho(
        self, acerto_aprovado, compromisso, escritorio
    ):
        compra = compromisso.items.get().purchase
        with pytest.raises(BusinessError, match="Corrija pelo acerto"):
            compras.editar_compra(
                compra, {"head_count": 11}, usuario=escritorio, motivo="x"
            )

    def test_excluir_direto_e_recusado(self, acerto_aprovado, compromisso, gestor):
        compra = compromisso.items.get().purchase
        with pytest.raises(BusinessError, match=acerto_aprovado.code):
            compras.excluir_compra(compra, usuario=gestor, motivo="x")

    def test_restaurar_direto_e_recusado(self, acerto_aprovado, compromisso, gestor):
        compra = compromisso.items.get().purchase
        with pytest.raises(BusinessError, match="Corrija pelo acerto"):
            compras.restaurar_compra(compra, usuario=gestor)


class TestTravaDeFechamento:
    """Aprovado, tudo que alimenta o valor recusa edição e diz o caminho."""

    def test_romaneio(self, acerto_aprovado, item, classe, escritorio):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            grading.registrar_romaneio(item, [], usuario=escritorio, motivo="x")

    def test_item_do_compromisso(
        self, acerto_aprovado, compromisso, item, categoria_desmamados, escritorio
    ):
        from apps.procurement.tests.conftest import dados_item

        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            commitments.editar_compromisso(
                compromisso,
                {},
                [{"id": item.pk} | dados_item(categoria_desmamados)],
                usuario=escritorio,
                motivo="x",
            )

    def test_nova_viagem(self, acerto_aprovado, compromisso, item, escritorio):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            trips.criar_viagem(
                usuario=escritorio,
                compromisso=compromisso,
                pickup_date=datetime.date(2025, 9, 3),
                cargas=[{"item": item, "planned_qty": 1}],
            )

    def test_novo_recebimento_com_outra_viagem(
        self, acerto_aprovado, viagem, escritorio
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            receivings.criar_recebimento(
                usuario=escritorio,
                viagem=viagem,
                date=DATA_RECEBIMENTO,
                linhas=[{"load": viagem.loads.get(), "received_qty": 1}],
            )

    def test_mensagem_diz_o_caminho(self, acerto_aprovado, item, escritorio):
        with pytest.raises(BlockingDependencyError) as erro:
            grading.registrar_romaneio(item, [], usuario=escritorio, motivo="x")
        assert acerto_aprovado.code in str(erro.value)
        assert "com motivo" in str(erro.value)


@pytest.mark.django_db(transaction=True)
def test_aprovar_ao_mesmo_tempo_gera_uma_compra_por_item_e_um_titulo_por_componente(
    acerto_duplo, gestor, compromisso_duplo
):
    """Clique duplo, ou duas pessoas: uma vence, a outra vê o acerto aprovado."""
    resultados = []
    barreira = threading.Barrier(2)

    def clicar():
        barreira.wait()
        try:
            closing.aprovar_acerto(acerto_duplo, usuario=gestor)
            resultados.append("ok")
        except BusinessError:
            resultados.append("erro")
        finally:
            connection.close()

    threads = [threading.Thread(target=clicar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(resultados) == ["erro", "ok"]
    assert Purchase.objects.count() == 2  # uma por item
    for compra in Purchase.objects.all():
        componentes = list(compra.invoices.values_list("component", flat=True))
        assert len(componentes) == len(set(componentes))  # um título por componente
    assert (
        HerdLedgerEntry.objects.filter(entry_type__isnull=True).count() == 0
        if hasattr(HerdLedgerEntry, "entry_type")
        else True
    )
