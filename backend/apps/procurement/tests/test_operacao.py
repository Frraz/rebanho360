"""Encerramento manual, situação depois do acerto, ADF e veículo, efeito do tipo
de tributo e o número único da operação (cliente, 2026-10-03)."""

import datetime

import pytest
from django.urls import reverse

from apps.audit.models import AuditAction, AuditEvent
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.finance import services as fin
from apps.finance.models import Invoice
from apps.procurement import closing, commitments, selectors, trips
from apps.procurement.selectors import SituacaoFinanceira
from apps.procurement.tests.conftest import D, tipo

pytestmark = pytest.mark.django_db


class TestNumeroUnicoDaOperacao:
    def test_a_operacao_inteira_carrega_o_mesmo_numero(
        self, compromisso, viagem, recebimento, acerto
    ):
        assert compromisso.code == "OP-000001"
        assert viagem.code == "OP-000001/V1"
        assert recebimento.code == "OP-000001/R1"
        assert acerto.code == "OP-000001/AC1"

    def test_a_compra_do_item_e_o_titulo_seguem_o_numero(
        self, acerto_aprovado, compromisso
    ):
        compra = compromisso.items.get().purchase
        assert compra.code == "OP-000001/I1"
        # no financeiro e no centro de custo: pela compra de origem
        titulo = Invoice.objects.get(origin_purchase=compra)
        assert titulo.origem.code.startswith("OP-000001")
        custos = compra.cost_entries.all()
        assert custos and all("OP-000001/I1" in c.description for c in custos)

    def test_operacao_antiga_segue_com_o_esquema_antigo(
        self, compromisso, escritorio, item
    ):
        antigo = type(compromisso).objects.filter(pk=compromisso.pk)
        antigo.update(code="CM-2025/26-0001")
        compromisso.refresh_from_db()
        viagem = trips.criar_viagem(
            usuario=escritorio,
            compromisso=compromisso,
            pickup_date=datetime.date(2025, 9, 3),
            cargas=[{"item": item, "planned_qty": 1}],
        )
        assert viagem.code == "VG-2025/26-0001"

    def test_numeracao_nao_repete_entre_safras(self, criar_compromisso):
        codigos = [criar_compromisso().code for _ in range(3)]
        assert codigos == ["OP-000001", "OP-000002", "OP-000003"]


class TestEncerramentoManual:
    def test_o_sistema_nao_encerra_sozinho_nem_com_tudo_pago(
        self, acerto_aprovado, compromisso
    ):
        assert not compromisso.encerrada
        assert (
            selectors.situacao_financeira(compromisso) != SituacaoFinanceira.ENCERRADA
        )

    def test_gestor_encerra_e_fica_registrado(
        self, acerto_aprovado, compromisso, gestor
    ):
        commitments.encerrar_operacao(
            compromisso, usuario=gestor, observacao="Tudo conferido"
        )
        compromisso.refresh_from_db()
        assert compromisso.encerrada
        assert compromisso.closed_by == gestor
        assert compromisso.closure_note == "Tudo conferido"
        assert (
            selectors.situacao_financeira(compromisso) == SituacaoFinanceira.ENCERRADA
        )
        assert AuditEvent.objects.filter(
            action=AuditAction.UPDATE,
            entity_id=str(compromisso.pk),
            reason="Tudo conferido",
        ).exists()

    def test_escritorio_nao_encerra(self, acerto_aprovado, compromisso, escritorio):
        with pytest.raises(BusinessError, match="administrador ou gestor"):
            commitments.encerrar_operacao(compromisso, usuario=escritorio)

    def test_so_se_encerra_com_acerto_aprovado(self, compromisso, gestor):
        with pytest.raises(BusinessError, match="Aprove o acerto"):
            commitments.encerrar_operacao(compromisso, usuario=gestor)

    def test_encerrar_duas_vezes_e_recusado(self, acerto_aprovado, compromisso, gestor):
        commitments.encerrar_operacao(compromisso, usuario=gestor)
        with pytest.raises(BusinessError, match="já está encerrada"):
            commitments.encerrar_operacao(compromisso, usuario=gestor)

    def test_encerrada_nao_recebe_lancamento_ate_reabrir_com_motivo(
        self, acerto_aprovado, compromisso, gestor, escritorio, comissionado
    ):
        commitments.encerrar_operacao(compromisso, usuario=gestor)
        compromisso.refresh_from_db()
        with pytest.raises(BlockingDependencyError, match="encerrada"):
            commitments.exigir_operacao_aberta(compromisso, "lançar")
        assert any("encerrada" in str(b) for b in compromisso.bloqueios())
        with pytest.raises(BusinessError, match="motivo"):
            commitments.reabrir_operacao(compromisso, usuario=gestor, motivo="")
        commitments.reabrir_operacao(
            compromisso, usuario=gestor, motivo="Faltou um acerto"
        )
        compromisso.refresh_from_db()
        assert not compromisso.encerrada and compromisso.closed_by is None

    def test_pela_tela(self, client, acerto_aprovado, compromisso, gestor):
        client.force_login(gestor)
        url = reverse("procurement:operacao_encerrar", args=[compromisso.pk])
        assert client.get(url).status_code == 200
        resposta = client.post(url, {"note": "Fechado"})
        assert resposta.status_code == 302
        compromisso.refresh_from_db()
        assert compromisso.encerrada
        html = client.get(
            reverse("procurement:compromisso_detalhe", args=[compromisso.pk])
        ).content.decode()
        assert "Encerrada" in html and "Reabrir operação" in html


class TestSituacaoFinanceira:
    def test_sem_acerto_aprovado_nao_ha_situacao(self, compromisso):
        assert selectors.situacao_financeira(compromisso) is None

    def test_o_financeiro_faz_a_operacao_avancar(
        self, acerto_aprovado, compromisso, gestor, financeiro
    ):
        assert (
            selectors.situacao_financeira(compromisso)
            == SituacaoFinanceira.AGUARDANDO_FINANCEIRO
        )
        titulos = list(
            Invoice.objects.filter(origin_settlement=acerto_aprovado)
        ) + list(
            Invoice.objects.filter(
                origin_purchase__commitment_item__commitment=compromisso
            )
        )
        hoje = datetime.date.today()
        for titulo in titulos:
            fin.programar_titulo(titulo, usuario=gestor, data=hoje)
        assert (
            selectors.situacao_financeira(compromisso)
            == SituacaoFinanceira.PAGAMENTO_PROGRAMADO
        )
        for n, titulo in enumerate(titulos):
            fin.aprovar_titulo(titulo, usuario=gestor)
            fin.baixar_titulo(
                titulo,
                usuario=financeiro,
                date=hoje,
                amount=titulo.amount,
                method="TED",
                document=f"TED-{n}",
            )
        assert selectors.situacao_financeira(compromisso) == SituacaoFinanceira.PAGO


class TestAdfEVeiculo:
    def test_adf_e_so_um_numero_sem_anexo(self, viagem, escritorio):
        trips.editar_viagem(
            viagem,
            {
                "adf_number": " 12345/A ",
                "vehicle": "Boiadeiro 3 eixos",
                "driver_name": "Zé",
            },
            None,
            usuario=escritorio,
            motivo="Documentação chegou",
        )
        viagem.refresh_from_db()
        assert viagem.adf_number == "12345/A"
        assert viagem.vehicle == "Boiadeiro 3 eixos"

    def test_aparece_na_tela_da_viagem(self, client, viagem, escritorio):
        trips.editar_viagem(
            viagem, {"adf_number": "ADF-77"}, None, usuario=escritorio, motivo="x"
        )
        client.force_login(escritorio)
        html = client.get(
            reverse("procurement:viagem_detalhe", args=[viagem.pk])
        ).content.decode()
        assert "ADF-77" in html


class TestEfeitoDoTipoDeTributo:
    """Cliente, 2026-10-03: o sistema não presume quem arca. O efeito vem do tipo
    — que o usuário define — ou, sem ele, do padrão da natureza."""

    def test_tipo_com_efeito_proprio_manda_mais_que_a_natureza(
        self, acerto, compromisso, escritorio
    ):
        from apps.commercial.models import TaxType

        taxa = tipo("GTA")  # natureza TAXA: soma ao custo por padrão
        from apps.procurement.settlement import calcular_acerto

        base = calcular_acerto(compromisso)
        TaxType.objects.filter(pk=taxa.pk).update(effect="ABATE_NO_LIQUIDO")
        closing.registrar_linhas(
            acerto,
            [{"tax_type": TaxType.objects.get(pk=taxa.pk), "amount": D("100")}],
            usuario=escritorio,
        )
        c = calcular_acerto(compromisso)
        assert c.custo_aquisicao == base.custo_aquisicao  # não somou ao custo
        assert c.liquido_ao_produtor == base.liquido_ao_produtor - 100

    def test_sem_efeito_no_tipo_vale_o_padrao_da_natureza(
        self, acerto, compromisso, escritorio
    ):
        from apps.procurement.settlement import calcular_acerto

        base = calcular_acerto(compromisso)
        closing.registrar_linhas(
            acerto, [{"tax_type": tipo("GTA"), "amount": D("100")}], usuario=escritorio
        )
        assert (
            calcular_acerto(compromisso).custo_aquisicao == base.custo_aquisicao + 100
        )
