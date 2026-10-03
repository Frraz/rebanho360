"""F5-13 — reabrir, excluir e restaurar o acerto: tudo ou nada, o saldo
volta ao que era **na data original**, e baixa feita bloqueia com o caminho."""

import datetime

import pytest

from apps.audit.models import AuditAction, AuditEvent, OperationEvent
from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.impact import analisar_impacto
from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.finance import services as fin
from apps.finance.models import Invoice
from apps.herd.models import HerdLedgerEntry
from apps.procurement import closing, commitments
from apps.procurement.models import FiscalNote
from apps.procurement.tests.conftest import DATA_RECEBIMENTO, D
from apps.purchases.models import Purchase

pytestmark = pytest.mark.django_db


def compra_do(compromisso):
    return compromisso.items.get().purchase


def pagar(titulo, *, programador, aprovador, financeiro):
    fin.programar_titulo(
        titulo,
        usuario=programador,
        data=datetime.date.today() + datetime.timedelta(days=1),
    )
    fin.aprovar_titulo(titulo, usuario=aprovador)
    return fin.baixar_titulo(
        titulo,
        usuario=financeiro,
        date=datetime.date.today(),
        amount=titulo.amount,
        method="TED",
        document="TED-1",
    )


class TestReabrir:
    def test_reabrir_devolve_o_acerto_a_em_andamento_e_desfaz_tudo(
        self, acerto_aprovado, compromisso, gestor, saldo_do_lote
    ):
        compra = compra_do(compromisso)
        lote = compra.lot
        assert saldo_do_lote(lote) == 10

        closing.reabrir_acerto(
            acerto_aprovado, usuario=gestor, motivo="Romaneio errado"
        )

        acerto_aprovado.refresh_from_db()
        compra.refresh_from_db()
        assert acerto_aprovado.status == Status.RASCUNHO
        assert acerto_aprovado.approved_at is None
        assert compra.status == Status.EXCLUIDA
        assert saldo_do_lote(lote) == 0  # rebanho
        assert not CostEntry.objects.filter(
            source_purchase=compra, status=Status.CONFIRMADA
        ).exists()  # custos
        assert not Invoice.objects.filter(
            origin_purchase=compra, status=Status.CONFIRMADA
        ).exists()  # títulos

    def test_o_saldo_volta_ao_que_era_na_data_original(
        self, acerto_aprovado, compromisso, gestor, saldo_do_lote
    ):
        """Regra 1: o razão é append-only; a compensação leva a data do fato."""
        lote = compra_do(compromisso).lot
        antes = HerdLedgerEntry.objects.count()

        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")

        assert HerdLedgerEntry.objects.count() > antes  # compensação, nunca apaga
        compensacao = HerdLedgerEntry.objects.filter(lot=lote, quantity__lt=0).get()
        assert compensacao.date == DATA_RECEBIMENTO  # a data do fato original
        assert saldo_do_lote(lote, ate=DATA_RECEBIMENTO) == 0

    def test_exige_motivo(self, acerto_aprovado, gestor):
        with pytest.raises(BusinessError, match="Motivo é obrigatório"):
            closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="  ")
        acerto_aprovado.refresh_from_db()
        assert acerto_aprovado.status == Status.CONFIRMADA

    def test_so_reabre_acerto_aprovado(self, acerto, gestor):
        with pytest.raises(BusinessError, match="Só se reabre um acerto aprovado"):
            closing.reabrir_acerto(acerto, usuario=gestor, motivo="x")

    def test_escritorio_nao_reabre(self, acerto_aprovado, escritorio):
        with pytest.raises(BusinessError, match="administrador ou gestor"):
            closing.reabrir_acerto(acerto_aprovado, usuario=escritorio, motivo="x")

    def test_registra_quem_quando_e_por_que(self, acerto_aprovado, gestor):
        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Peso trocado")

        evento = AuditEvent.objects.filter(
            entity_type="Settlement", action=AuditAction.UPDATE
        ).get()
        assert evento.actor == gestor and evento.reason == "Peso trocado"
        assert "status" in evento.changed_fields
        assert evento.before["status"] == Status.CONFIRMADA
        assert evento.after["status"] == Status.RASCUNHO
        linha = OperationEvent.objects.filter(title="Acerto reaberto").get()
        assert "Peso trocado" in linha.description

    def test_a_compra_desfeita_sai_na_mesma_cascata_do_acerto(
        self, acerto_aprovado, compromisso, gestor
    ):
        ultimo = AuditEvent.objects.order_by("-id").first().id
        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")

        eventos = AuditEvent.objects.filter(id__gt=ultimo)
        raizes = {e.cascade_root for e in eventos if e.cascade_root}
        assert len(raizes) == 1  # um ato, não sete eventos soltos
        tipos = {e.entity_type for e in eventos if e.cascade_root}
        assert {"Settlement", "Purchase", "HerdMovement", "CostEntry"} <= tipos

    def test_depois_de_reabrir_edita_de_novo_e_aprova_outra_vez(
        self, acerto_aprovado, compromisso, gestor, escritorio, classe, item
    ):
        from apps.procurement import grading

        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Peso trocado")
        existente = item.gradings.get()
        grading.registrar_romaneio(
            item,
            [
                {
                    "id": existente.pk,
                    "carcass_class": classe,
                    "band": 4,
                    "head_count": 10,
                    "carcass_weight_kg": D("2550"),
                }
            ],
            usuario=escritorio,
            motivo="Romaneio corrigido",
        )
        acerto_aprovado.refresh_from_db()
        closing.aprovar_acerto(acerto_aprovado, usuario=gestor)

        compra = compra_do(compromisso)
        assert compra.status == Status.CONFIRMADA
        assert compra.animal_value == D("45900.00")  # 170 @ × R$ 270
        assert compra.invoices.filter(status=Status.CONFIRMADA).count() == 1  # animais
        assert (
            acerto_aprovado.invoices.filter(status=Status.CONFIRMADA).count() == 1
        )  # frete

    def test_reaprovar_nao_duplica_compra_nem_titulo(
        self, acerto_aprovado, compromisso, gestor
    ):
        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")
        acerto_aprovado.refresh_from_db()
        closing.aprovar_acerto(acerto_aprovado, usuario=gestor)

        assert Purchase.objects.count() == 1  # a mesma compra, restaurada
        assert Invoice.objects.filter(status=Status.CONFIRMADA).count() == 2


class TestBloqueios:
    def test_baixa_de_titulo_bloqueia_com_o_link_do_pagamento(
        self, acerto_aprovado, compromisso, gestor, escritorio, financeiro
    ):
        titulo = Invoice.objects.get(
            origin_purchase=compra_do(compromisso), component="ANIMAIS"
        )
        pagamento = pagar(
            titulo, programador=escritorio, aprovador=gestor, financeiro=financeiro
        )

        with pytest.raises(BlockingDependencyError, match="baixa"):
            closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")

        impacto = analisar_impacto(acerto_aprovado)
        assert impacto.bloqueado
        com_link = [b for b in impacto.bloqueios if getattr(b, "url", "")]
        assert any(str(pagamento.pk) in b.url for b in com_link)
        acerto_aprovado.refresh_from_db()
        assert acerto_aprovado.status == Status.CONFIRMADA  # nada mudou

    def test_desfazer_a_baixa_libera_a_reabertura(
        self, acerto_aprovado, compromisso, gestor, escritorio, financeiro
    ):
        titulo = Invoice.objects.get(
            origin_purchase=compra_do(compromisso), component="ANIMAIS"
        )
        pagamento = pagar(
            titulo, programador=escritorio, aprovador=gestor, financeiro=financeiro
        )
        fin.desfazer_baixa(pagamento, usuario=financeiro, motivo="Pix estornado")

        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")
        acerto_aprovado.refresh_from_db()
        assert acerto_aprovado.status == Status.RASCUNHO

    def test_nota_fiscal_registrada_bloqueia_com_o_caminho(
        self, acerto_aprovado, gestor, escritorio
    ):
        closing.registrar_notas(
            acerto_aprovado,
            [
                {
                    "number": "752",
                    "series": "1",
                    "issue_date": DATA_RECEBIMENTO,
                    "amount": D("43200"),
                }
            ],
            usuario=escritorio,
        )
        with pytest.raises(BlockingDependencyError, match="nota fiscal registrada"):
            closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")
        bloqueio = [
            b
            for b in analisar_impacto(acerto_aprovado).bloqueios
            if "nota fiscal" in str(b)
        ][0]
        assert bloqueio.url.endswith("#notas-fiscais")

    def test_retirar_a_nota_com_motivo_libera(
        self, acerto_aprovado, gestor, escritorio
    ):
        closing.registrar_notas(
            acerto_aprovado,
            [
                {
                    "number": "752",
                    "series": "1",
                    "issue_date": DATA_RECEBIMENTO,
                    "amount": D("43200"),
                }
            ],
            usuario=escritorio,
        )
        closing.registrar_notas(
            acerto_aprovado, [], usuario=escritorio, motivo="Nota cancelada"
        )
        assert FiscalNote.all_objects.count() == 1  # continua no banco
        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")

    def test_safra_encerrada_bloqueia(self, acerto_aprovado, gestor, season):
        from apps.organizations.models import SeasonStatus

        season.status = SeasonStatus.ENCERRADA
        season.save()
        with pytest.raises(BlockingDependencyError, match="encerrada"):
            closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")

    def test_acerto_em_andamento_nao_tem_bloqueio(self, acerto):
        assert analisar_impacto(acerto).bloqueios == []


class TestDependentesDasCompras:
    """Gado que já saiu do lote: só a cascata confirmada desfaz."""

    def _vender(self, compromisso, escritorio, frigorifico, categoria):
        from apps.sales import services as vendas

        compra = compra_do(compromisso)
        dados = {
            "date": datetime.date(2025, 9, 10),
            "type": "ABATE",
            "buyer": frigorifico,
            "farm": compra.destination_farm,
            "lot": compra.lot,
            "category": compra.category,
            "head_count": 4,
            "total_weight_kg": D("2000"),
            "carcass_weight_kg": D("1000"),
            "total_value": D("20000"),
        }
        venda = vendas.criar_venda(usuario=escritorio, **dados)
        return vendas.confirmar_venda(venda, usuario=escritorio)

    def test_sem_cascata_pede_confirmacao_e_nao_desfaz_nada(
        self, acerto_aprovado, compromisso, gestor, escritorio, frigorifico
    ):
        venda = self._vender(compromisso, escritorio, frigorifico, None)

        with pytest.raises(DependencyError) as erro:
            closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")
        assert any(d.pk == venda.pk for d in erro.value.dependents)
        acerto_aprovado.refresh_from_db()
        assert acerto_aprovado.status == Status.CONFIRMADA
        assert compra_do(compromisso).status == Status.CONFIRMADA

    def test_com_cascata_desfaz_a_venda_e_a_compra_na_mesma_transacao(
        self, acerto_aprovado, compromisso, gestor, escritorio, frigorifico
    ):
        venda = self._vender(compromisso, escritorio, frigorifico, None)

        closing.reabrir_acerto(
            acerto_aprovado, usuario=gestor, motivo="Corrigir", cascata=True
        )
        venda.refresh_from_db()
        assert venda.status == Status.EXCLUIDA
        assert compra_do(compromisso).status == Status.EXCLUIDA

    def test_a_analise_de_impacto_lista_o_que_depende(
        self, acerto_aprovado, compromisso, escritorio, frigorifico
    ):
        venda = self._vender(compromisso, escritorio, frigorifico, None)
        impacto = analisar_impacto(acerto_aprovado)
        assert impacto.exige_cascata
        assert any(d.pk == venda.pk for d in impacto.dependentes)
        assert any("a compra OP-" in e for e in impacto.efeitos)


class TestExcluirERestaurar:
    def test_excluir_acerto_em_andamento(self, acerto, escritorio):
        closing.excluir_acerto(acerto, usuario=escritorio, motivo="Aberto sem querer")
        acerto.refresh_from_db()
        assert acerto.status == Status.EXCLUIDA

    def test_excluir_acerto_aprovado_desfaz_as_compras(
        self, acerto_aprovado, compromisso, gestor
    ):
        closing.excluir_acerto(acerto_aprovado, usuario=gestor, motivo="Duplicado")
        assert compra_do(compromisso).status == Status.EXCLUIDA

    def test_escritorio_nao_exclui_acerto_aprovado(self, acerto_aprovado, escritorio):
        with pytest.raises(BusinessError, match="permissão"):
            closing.excluir_acerto(acerto_aprovado, usuario=escritorio, motivo="x")

    def test_depois_de_excluir_abre_outro(
        self, acerto, compromisso, escritorio, gestor
    ):
        closing.excluir_acerto(acerto, usuario=gestor, motivo="Refazer")
        novo = closing.criar_acerto(
            usuario=escritorio,
            compromisso=compromisso,
            date=datetime.date(2025, 9, 21),
        )
        assert novo.code == "OP-000001/AC2"

    def test_restaurar_aprovado_reaprova_com_os_valores_de_agora(
        self, acerto_aprovado, compromisso, gestor
    ):
        excluido = closing.excluir_acerto(
            acerto_aprovado, usuario=gestor, motivo="Engano"
        )
        restaurado = closing.restaurar_acerto(excluido, usuario=gestor)

        assert restaurado.status == Status.CONFIRMADA
        assert compra_do(compromisso).status == Status.CONFIRMADA
        assert Purchase.objects.count() == 1

    def test_rascunho_excluido_volta_em_andamento_nao_aprovado(
        self, acerto, compromisso, gestor
    ):
        excluido = closing.excluir_acerto(acerto, usuario=gestor, motivo="Engano")
        restaurado = closing.restaurar_acerto(excluido, usuario=gestor)

        assert restaurado.status == Status.RASCUNHO
        assert not Purchase.objects.exists()  # restaurar não aprova

    def test_depois_de_reabrir_e_excluir_restaura_em_andamento(
        self, acerto_aprovado, gestor
    ):
        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")
        acerto_aprovado.refresh_from_db()
        excluido = closing.excluir_acerto(
            acerto_aprovado, usuario=gestor, motivo="Refazer"
        )
        assert (
            closing.restaurar_acerto(excluido, usuario=gestor).status == Status.RASCUNHO
        )

    def test_nao_restaura_se_ja_ha_outro_acerto(
        self, acerto, compromisso, escritorio, gestor
    ):
        excluido = closing.excluir_acerto(acerto, usuario=gestor, motivo="Refazer")
        closing.criar_acerto(
            usuario=escritorio, compromisso=compromisso, date=datetime.date(2025, 9, 21)
        )
        with pytest.raises(BusinessError, match="só um acerto vale por vez"):
            closing.restaurar_acerto(excluido, usuario=gestor)

    def test_excluir_o_compromisso_com_acerto_aprovado_e_bloqueado_com_o_caminho(
        self, acerto_aprovado, compromisso, gestor
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            commitments.excluir_compromisso(
                compromisso, usuario=gestor, motivo="Cancelado", cascata=True
            )

    def test_reabrir_e_depois_excluir_o_compromisso_em_cascata(
        self, acerto_aprovado, compromisso, gestor
    ):
        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")
        commitments.excluir_compromisso(
            compromisso, usuario=gestor, motivo="Cancelado", cascata=True
        )
        acerto_aprovado.refresh_from_db()
        assert acerto_aprovado.status == Status.EXCLUIDA
        compromisso.refresh_from_db()
        assert compromisso.status == Status.EXCLUIDA
