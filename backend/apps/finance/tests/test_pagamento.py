"""F4-03, F4-04 e F4-05 — programar, aprovar, baixar (sem duplicar) e
desfazer a baixa. O dinheiro que sai de verdade."""

import datetime
import threading
from decimal import Decimal

import pytest
from django.db import connection

from apps.accounts.models import Role, User, UserFarmAccess
from apps.core.exceptions import (
    BlockingDependencyError,
    Bloqueio,
    BusinessError,
)
from apps.core.reversible import Status
from apps.finance import services
from apps.finance.models import Payment, PaymentStatus
from apps.finance.tests.conftest import AMANHA, HOJE, aprovado, baixa, programado
from apps.purchases import services as compras

pytestmark = pytest.mark.django_db

D = Decimal


class TestProgramar:
    def test_programar_leva_a_programado(self, titulo, escritorio):
        programado(titulo, escritorio)

        titulo.refresh_from_db()
        assert titulo.payment_status == PaymentStatus.PROGRAMADO
        assert titulo.scheduled_date == AMANHA
        assert titulo.scheduled_by == escritorio

    def test_data_no_passado_e_recusada(self, titulo, escritorio):
        with pytest.raises(BusinessError, match="passado"):
            services.programar_titulo(
                titulo, usuario=escritorio, data=HOJE - datetime.timedelta(days=1)
            )

    def test_titulo_sem_favorecido_nao_programa(self, escritorio, dados_compra):
        compra = compras.criar_compra(
            usuario=escritorio, **{**dados_compra, "seller": None}
        )
        compras.confirmar_compra(compra, usuario=escritorio)
        titulo = compra.invoices.get()

        with pytest.raises(BusinessError, match="não tem favorecido"):
            programado(titulo, escritorio)

    def test_titulo_a_receber_nao_se_programa(self, titulo_a_receber, escritorio):
        with pytest.raises(BusinessError, match="a receber"):
            programado(titulo_a_receber, escritorio)

    def test_campo_nao_programa(self, titulo, campo_baixao):
        with pytest.raises(BusinessError, match="permissão"):
            programado(titulo, campo_baixao)

    def test_devolver_tira_a_programacao(self, titulo, escritorio):
        programado(titulo, escritorio)

        services.desprogramar_titulo(titulo, usuario=escritorio)

        titulo.refresh_from_db()
        assert titulo.payment_status == PaymentStatus.A_PAGAR
        assert titulo.scheduled_date is None


class TestAprovar:
    def test_aprovar_exige_permissao_propria(self, titulo, escritorio):
        programado(titulo, escritorio)

        # ESCRITORIO programa, mas não aprova: `finance.approve_payment`.
        with pytest.raises(BusinessError, match="permissão para aprovar"):
            services.aprovar_titulo(titulo, usuario=escritorio)

    def test_nao_se_aprova_o_que_nao_foi_programado(self, titulo, gestor):
        with pytest.raises(BusinessError, match="ainda não foi programado"):
            services.aprovar_titulo(titulo, usuario=gestor)

    def test_aprovar_registra_quem_e_quando_e_audita(self, titulo, escritorio, gestor):
        from apps.audit.models import AuditEvent

        programado(titulo, escritorio)

        services.aprovar_titulo(titulo, usuario=gestor)

        titulo.refresh_from_db()
        assert titulo.payment_status == PaymentStatus.APROVADO
        assert titulo.approved_by == gestor and titulo.approved_at is not None
        assert AuditEvent.objects.filter(
            action="APPROVE", entity_type="Invoice", entity_id=str(titulo.pk)
        ).exists()

    def test_tirar_a_aprovacao_exige_motivo(self, titulo_aprovado, gestor):
        with pytest.raises(BusinessError, match="motivo"):
            services.desprogramar_titulo(titulo_aprovado, usuario=gestor, motivo="")

        services.desprogramar_titulo(
            titulo_aprovado, usuario=gestor, motivo="Valor errado"
        )
        titulo_aprovado.refresh_from_db()
        assert titulo_aprovado.payment_status == PaymentStatus.A_PAGAR
        assert titulo_aprovado.approved_by is None


class TestBaixa:
    def test_pagar_sem_aprovacao_e_recusado(self, titulo, escritorio, financeiro):
        with pytest.raises(BusinessError, match="depois da aprovação"):
            baixa(titulo, financeiro)
        programado(titulo, escritorio)
        with pytest.raises(BusinessError, match="depois da aprovação"):
            baixa(titulo, financeiro)

        assert Payment.objects.count() == 0

    def test_baixa_total_quita_o_titulo(self, titulo_aprovado, financeiro):
        pagamento = baixa(titulo_aprovado, financeiro)

        titulo_aprovado.refresh_from_db()
        assert titulo_aprovado.payment_status == PaymentStatus.PAGO
        assert titulo_aprovado.balance == D("0")
        assert pagamento.status == Status.CONFIRMADA
        assert pagamento.code == "PG-2025/26-0001"

    def test_baixa_parcial_soma_ate_o_total_e_nunca_ultrapassa(
        self, titulo_aprovado, financeiro
    ):
        baixa(titulo_aprovado, financeiro, valor=D("100000"), documento="TED-1")
        titulo_aprovado.refresh_from_db()
        assert titulo_aprovado.payment_status == PaymentStatus.PARCIAL
        assert titulo_aprovado.balance == D("288080.00")

        with pytest.raises(BusinessError, match="ultrapassa o que falta"):
            baixa(titulo_aprovado, financeiro, valor=D("288080.01"), documento="TED-2")

        baixa(titulo_aprovado, financeiro, valor=D("288080.00"), documento="TED-2")
        titulo_aprovado.refresh_from_db()
        assert titulo_aprovado.payment_status == PaymentStatus.PAGO
        assert titulo_aprovado.paid_total == D("388080.00")

    def test_titulo_quitado_nao_recebe_outra_baixa(self, titulo_aprovado, financeiro):
        baixa(titulo_aprovado, financeiro)

        with pytest.raises(BusinessError, match="já está quitado"):
            baixa(titulo_aprovado, financeiro, valor=D("1"), documento="OUTRO")

    def test_o_mesmo_documento_duas_vezes_e_recusado(self, titulo_aprovado, financeiro):
        baixa(titulo_aprovado, financeiro, valor=D("1000"), documento="PIX-1")

        with pytest.raises(BusinessError, match="Já existe uma baixa"):
            baixa(titulo_aprovado, financeiro, valor=D("1000"), documento="PIX-1")

        assert Payment.objects.count() == 1

    def test_documento_e_obrigatorio(self, titulo_aprovado, financeiro):
        with pytest.raises(BusinessError, match="documento"):
            baixa(titulo_aprovado, financeiro, documento="  ")

    def test_data_futura_e_recusada(self, titulo_aprovado, financeiro):
        with pytest.raises(BusinessError, match="futuro"):
            baixa(titulo_aprovado, financeiro, data=AMANHA)

    def test_gestor_e_escritorio_nao_dao_baixa(
        self, titulo_aprovado, gestor, escritorio
    ):
        for usuario in (gestor, escritorio):
            with pytest.raises(BusinessError, match="permissão para dar baixa"):
                baixa(titulo_aprovado, usuario)

    def test_o_banco_garante_uma_baixa_por_titulo_e_documento(
        self, titulo_aprovado, financeiro
    ):
        from django.db import IntegrityError, transaction

        baixa(titulo_aprovado, financeiro, valor=D("10"), documento="X")

        with pytest.raises(IntegrityError), transaction.atomic():
            Payment.objects.create(
                code="PG-DUP",
                invoice=titulo_aprovado,
                date=HOJE,
                amount=D("10"),
                method="PIX",
                document="X",
                status=Status.CONFIRMADA,
            )

    def test_recebimento_nao_passa_por_aprovacao(self, titulo_a_receber, financeiro):
        pagamento = baixa(titulo_a_receber, financeiro, valor=D("1000"))

        titulo_a_receber.refresh_from_db()
        assert titulo_a_receber.payment_status == PaymentStatus.PARCIAL
        assert pagamento.code == "RC-2025/26-0001"


class TestQuemAprovaNaoExecuta:
    def test_quem_aprovou_nao_paga_havendo_outro_financeiro(
        self, titulo, escritorio, financeiro, financeiro2
    ):
        programado(titulo, escritorio)
        services.aprovar_titulo(titulo, usuario=financeiro)

        with pytest.raises(BusinessError, match="Quem aprova não é quem paga"):
            baixa(titulo, financeiro)

        # Outra pessoa do financeiro dá a baixa normalmente.
        baixa(titulo, financeiro2)
        titulo.refresh_from_db()
        assert titulo.payment_status == PaymentStatus.PAGO

    def test_unico_usuario_financeiro_pode_aprovar_e_pagar_e_fica_na_auditoria(
        self, titulo, escritorio, financeiro
    ):
        from apps.audit.models import AuditEvent

        programado(titulo, escritorio)
        services.aprovar_titulo(titulo, usuario=financeiro)

        baixa(titulo, financeiro)

        assert AuditEvent.objects.filter(
            entity_type="Invoice", reason__contains="mesma pessoa"
        ).exists()

    def test_outro_financeiro_sem_acesso_a_fazenda_nao_conta_como_alternativa(
        self, titulo, escritorio, financeiro, goiano_sem_acesso
    ):
        programado(titulo, escritorio)
        services.aprovar_titulo(titulo, usuario=financeiro)

        baixa(titulo, financeiro)  # o outro não enxerga São Francisco

        titulo.refresh_from_db()
        assert titulo.payment_status == PaymentStatus.PAGO

    def test_gestor_aprova_e_financeiro_paga_sem_atrito(
        self, titulo, escritorio, gestor, financeiro
    ):
        aprovado(titulo, escritorio, gestor)

        baixa(titulo, financeiro)

        titulo.refresh_from_db()
        assert titulo.payment_status == PaymentStatus.PAGO


@pytest.fixture
def goiano_sem_acesso():
    from apps.properties.models import Farm

    outra = Farm.objects.create(name="Goiano", code="GOI")
    user = User.objects.create_user(
        username="fin_goiano", password="x", role=Role.FINANCEIRO
    )
    UserFarmAccess.objects.create(user=user, farm=outra, can_write=True)
    return user


@pytest.mark.django_db(transaction=True)
def test_clique_duplo_nao_paga_duas_vezes():
    """Duas requisições simultâneas com o mesmo documento: uma vence."""
    from apps.costs.models import CostCenter, CostClass
    from apps.livestock.models import AnimalCategory, Sex
    from apps.organizations.models import Company, Season
    from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
    from apps.properties.models import Farm

    CostClass.objects.get_or_create(name="CUSTEIO")
    CostCenter.objects.get_or_create(name="DESPESA GADO")
    gestor = User.objects.create_user(username="g", password="x", role=Role.GESTOR)
    financeiro = User.objects.create_user(
        username="f", password="x", role=Role.FINANCEIRO
    )
    company = Company.objects.create(name="Fazendas Reunidas")
    Season.objects.create(
        company=company,
        name="2025/2026",
        start_date=datetime.date(2025, 7, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    farm = Farm.objects.create(name="São Francisco", code="SFR")
    UserFarmAccess.objects.create(user=financeiro, farm=farm, can_write=True)
    categoria = AnimalCategory.objects.create(name="Machos Desm.", sex=Sex.MACHO)
    vendedor = Partner.objects.create(name="Vendedor")
    PartnerRole.objects.create(partner=vendedor, role=PartnerRoleChoice.FORNECEDOR)
    compra = compras.criar_compra(
        usuario=gestor,
        date=datetime.date(2025, 9, 18),
        seller=vendedor,
        destination_farm=farm,
        category=categoria,
        head_count=10,
        animal_value=D("10000"),
    )
    compras.confirmar_compra(compra, usuario=gestor)
    titulo = compra.invoices.get()
    services.programar_titulo(titulo, usuario=gestor, data=AMANHA)
    services.aprovar_titulo(titulo, usuario=gestor)

    resultados = []
    barreira = threading.Barrier(2)

    def clicar():
        barreira.wait()
        try:
            services.baixar_titulo(
                titulo,
                usuario=financeiro,
                date=HOJE,
                amount=D("10000"),
                method="PIX",
                document="E2E-123",
            )
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
    assert Payment.objects.filter(invoice=titulo).count() == 1
    titulo.refresh_from_db()
    assert titulo.paid_total == D("10000")


@pytest.mark.django_db(transaction=True)
def test_duas_baixas_diferentes_simultaneas_nunca_passam_do_total():
    """Mesmo com documentos distintos, a soma não ultrapassa o título."""
    from apps.costs.models import CostCenter, CostClass
    from apps.livestock.models import AnimalCategory, Sex
    from apps.organizations.models import Company, Season
    from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
    from apps.properties.models import Farm

    CostClass.objects.get_or_create(name="CUSTEIO")
    CostCenter.objects.get_or_create(name="DESPESA GADO")
    gestor = User.objects.create_user(username="g", password="x", role=Role.GESTOR)
    financeiro = User.objects.create_user(
        username="f", password="x", role=Role.FINANCEIRO
    )
    company = Company.objects.create(name="Fazendas Reunidas")
    Season.objects.create(
        company=company,
        name="2025/2026",
        start_date=datetime.date(2025, 7, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    farm = Farm.objects.create(name="São Francisco", code="SFR")
    UserFarmAccess.objects.create(user=financeiro, farm=farm, can_write=True)
    categoria = AnimalCategory.objects.create(name="Machos Desm.", sex=Sex.MACHO)
    vendedor = Partner.objects.create(name="Vendedor")
    PartnerRole.objects.create(partner=vendedor, role=PartnerRoleChoice.FORNECEDOR)
    compra = compras.criar_compra(
        usuario=gestor,
        date=datetime.date(2025, 9, 18),
        seller=vendedor,
        destination_farm=farm,
        category=categoria,
        head_count=10,
        animal_value=D("10000"),
    )
    compras.confirmar_compra(compra, usuario=gestor)
    titulo = compra.invoices.get()
    services.programar_titulo(titulo, usuario=gestor, data=AMANHA)
    services.aprovar_titulo(titulo, usuario=gestor)

    resultados = []
    barreira = threading.Barrier(2)

    def pagar(documento):
        barreira.wait()
        try:
            services.baixar_titulo(
                titulo,
                usuario=financeiro,
                date=HOJE,
                amount=D("7000"),
                method="PIX",
                document=documento,
            )
            resultados.append("ok")
        except BusinessError:
            resultados.append("erro")
        finally:
            connection.close()

    threads = [threading.Thread(target=pagar, args=(f"DOC-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(resultados) == ["erro", "ok"]
    titulo.refresh_from_db()
    assert titulo.paid_total == D("7000")
    assert titulo.payment_status == PaymentStatus.PARCIAL


class TestDesfazerBaixa:
    def test_financeiro_desfaz_com_motivo_e_o_titulo_volta_a_aprovado(
        self, titulo_aprovado, financeiro
    ):
        pagamento = baixa(titulo_aprovado, financeiro)

        services.desfazer_baixa(pagamento, usuario=financeiro, motivo="TED devolvida")

        pagamento.refresh_from_db()
        titulo_aprovado.refresh_from_db()
        assert pagamento.status == Status.EXCLUIDA
        assert titulo_aprovado.payment_status == PaymentStatus.APROVADO
        assert titulo_aprovado.paid_total == D("0")

    def test_desfazer_uma_de_duas_baixas_deixa_parcial(
        self, titulo_aprovado, financeiro
    ):
        a = baixa(titulo_aprovado, financeiro, valor=D("100"), documento="A")
        baixa(titulo_aprovado, financeiro, valor=D("200"), documento="B")

        services.desfazer_baixa(a, usuario=financeiro, motivo="Erro")

        titulo_aprovado.refresh_from_db()
        assert titulo_aprovado.payment_status == PaymentStatus.PARCIAL
        assert titulo_aprovado.paid_total == D("200")

    def test_gestor_nao_desfaz_baixa(self, titulo_aprovado, financeiro, gestor):
        pagamento = baixa(titulo_aprovado, financeiro)

        with pytest.raises(BusinessError, match="financeiro ou o administrador"):
            services.desfazer_baixa(pagamento, usuario=gestor, motivo="x")

    def test_exige_motivo(self, titulo_aprovado, financeiro):
        pagamento = baixa(titulo_aprovado, financeiro)

        with pytest.raises(BusinessError, match="Motivo"):
            services.desfazer_baixa(pagamento, usuario=financeiro, motivo="")

    def test_documento_da_baixa_desfeita_pode_ser_lancado_de_novo(
        self, titulo_aprovado, financeiro
    ):
        pagamento = baixa(titulo_aprovado, financeiro, documento="TED-9")
        services.desfazer_baixa(pagamento, usuario=financeiro, motivo="Valor errado")

        baixa(titulo_aprovado, financeiro, valor=D("5"), documento="TED-9")

        assert Payment.objects.filter(status=Status.CONFIRMADA).count() == 1

    def test_restaurar_a_baixa_reaplica(self, titulo_aprovado, financeiro):
        pagamento = baixa(titulo_aprovado, financeiro)
        services.desfazer_baixa(pagamento, usuario=financeiro, motivo="Engano")

        services.restaurar_baixa(pagamento, usuario=financeiro)

        titulo_aprovado.refresh_from_db()
        assert titulo_aprovado.payment_status == PaymentStatus.PAGO


class TestBaixaBloqueiaAMontante:
    """F4-05: enquanto a baixa existir, nada a montante pode ser desfeito."""

    def test_nao_exclui_a_compra_com_pagamento_baixado_e_diz_o_caminho(
        self, compra, titulo_aprovado, financeiro, gestor
    ):
        pagamento = baixa(titulo_aprovado, financeiro)

        bloqueios = compra.bloqueios()
        assert isinstance(bloqueios[0], Bloqueio)
        assert pagamento.code in bloqueios[0].texto
        assert "desfaça antes a baixa" in bloqueios[0].texto
        assert bloqueios[0].url.endswith(f"/financeiro/pagamentos/{pagamento.pk}/")

        with pytest.raises(BlockingDependencyError, match="desfaça antes a baixa"):
            compras.excluir_compra(compra, usuario=gestor, motivo="Engano")
        compra.refresh_from_db()
        assert compra.status == Status.CONFIRMADA

    def test_nao_corrige_a_compra_paga(
        self, compra, titulo_aprovado, financeiro, escritorio
    ):
        baixa(titulo_aprovado, financeiro)

        with pytest.raises(BlockingDependencyError):
            compras.editar_compra(
                compra, {"notes": "x"}, usuario=escritorio, motivo="Observação"
            )

    def test_desfeita_a_baixa_a_compra_exclui_de_novo(
        self, compra, titulo_aprovado, financeiro, gestor
    ):
        pagamento = baixa(titulo_aprovado, financeiro)
        services.desfazer_baixa(pagamento, usuario=financeiro, motivo="Engano")

        compras.excluir_compra(compra, usuario=gestor, motivo="Duplicada")

        compra.refresh_from_db()
        assert compra.status == Status.EXCLUIDA
        assert compra.invoices.get().status == Status.EXCLUIDA

    def test_excluir_compra_cujo_lote_foi_vendido_e_pago_e_bloqueado(
        self, compra, gestor, financeiro, escritorio, frigorifico, sao_francisco
    ):
        """O caso do documento: o lote foi vendido e o pagamento da venda já
        foi baixado — o link leva direto ao pagamento."""
        from apps.sales import services as vendas

        venda = vendas.criar_venda(
            usuario=escritorio,
            date=datetime.date(2025, 10, 1),
            type="VENDA",
            buyer=frigorifico,
            farm=sao_francisco,
            lot=compra.lot,
            category=compra.category,
            head_count=10,
            total_weight_kg=D("4500"),
            total_value=D("50000"),
        )
        vendas.confirmar_venda(venda, usuario=escritorio)
        recebimento = baixa(
            venda.invoices.get(), financeiro, valor=D("50000"), documento="REC-1"
        )

        bloqueios = compra.bloqueios()

        textos = [str(b) for b in bloqueios]
        assert any(venda.code in t and "desfaça antes a baixa" in t for t in textos)
        link = next(b for b in bloqueios if venda.code in str(b))
        assert link.url.endswith(f"/financeiro/pagamentos/{recebimento.pk}/")
        with pytest.raises(BlockingDependencyError):
            compras.excluir_compra(compra, usuario=gestor, motivo="Engano")

    def test_nao_exclui_a_venda_com_recebimento_baixado(
        self, venda, titulo_a_receber, financeiro, gestor
    ):
        from apps.sales import services as vendas

        baixa(titulo_a_receber, financeiro, valor=D("1000"))

        with pytest.raises(BlockingDependencyError, match="desfaça antes a baixa"):
            vendas.excluir_venda(venda, usuario=gestor, motivo="Engano")

    def test_excluir_o_titulo_com_baixa_e_bloqueado(
        self, titulo_aprovado, financeiro, gestor
    ):
        baixa(titulo_aprovado, financeiro)

        with pytest.raises(BlockingDependencyError, match="desfaça antes a baixa"):
            services.excluir_titulo(titulo_aprovado, usuario=gestor, motivo="x")

    def test_safra_encerrada_bloqueia_desfazer_a_baixa(
        self, titulo_aprovado, financeiro, season
    ):
        from apps.organizations.models import SeasonStatus

        pagamento = baixa(titulo_aprovado, financeiro)
        season.status = SeasonStatus.ENCERRADA
        season.save()

        with pytest.raises(BlockingDependencyError, match="reabrir a safra"):
            services.desfazer_baixa(pagamento, usuario=financeiro, motivo="x")
