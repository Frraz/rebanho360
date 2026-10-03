"""F4-01 e F4-02 — título e geração a partir da operação, idempotente."""

import datetime
import threading
from decimal import Decimal

import pytest
from django.db import connection

from apps.audit.models import AuditEvent
from apps.core.exceptions import BusinessError
from apps.core.reversible import Status
from apps.finance import services
from apps.finance.models import Direction, Invoice, PaymentStatus
from apps.purchases import services as compras

pytestmark = pytest.mark.django_db

D = Decimal


class TestGeracaoDaCompra:
    def test_confirmar_gera_o_titulo_dos_animais_sem_digitar_nada(
        self, compra, vendedor, conta_do_vendedor, sao_francisco
    ):
        titulo = compra.invoices.get()

        assert titulo.component == "ANIMAIS"
        assert titulo.direction == Direction.PAGAR
        assert titulo.amount == D("388080.00")
        assert titulo.payee == vendedor
        # Dado bancário vem do cadastro do parceiro, nunca redigitado.
        assert titulo.bank_account == conta_do_vendedor
        assert titulo.farm == sao_francisco
        assert titulo.season == compra.season
        assert titulo.payment_status == PaymentStatus.A_PAGAR
        assert titulo.code == "TT-2025/26-0001"

    def test_vencimento_e_a_data_da_compra_mais_o_prazo(self, compra):
        titulo = compra.invoices.get()

        assert titulo.issue_date == datetime.date(2025, 9, 18)
        assert titulo.due_date == datetime.date(2025, 10, 18)

    def test_sem_prazo_vence_na_data_da_compra(self, escritorio, dados_compra):
        compra = compras.criar_compra(
            usuario=escritorio, **{**dados_compra, "payment_days": None}
        )
        compra = compras.confirmar_compra(compra, usuario=escritorio)

        assert compra.invoices.get().due_date == compra.date

    def test_frete_comissao_e_impostos_viram_titulos_sem_favorecido(
        self, escritorio, dados_compra
    ):
        compra = compras.criar_compra(
            usuario=escritorio,
            **{
                **dados_compra,
                "freight_value": D("4500"),
                "commission_value": D("1966.50"),
                "tax_value": D("100"),
            },
        )
        compra = compras.confirmar_compra(compra, usuario=escritorio)

        por_componente = {t.component: t for t in compra.invoices.all()}
        assert set(por_componente) == {"ANIMAIS", "FRETE", "COMISSAO", "IMPOSTOS"}
        assert por_componente["FRETE"].amount == D("4500")
        assert por_componente["FRETE"].payee is None  # pendência #17
        assert por_componente["ANIMAIS"].payee is not None

    def test_rascunho_nao_gera_titulo(self, escritorio, dados_compra):
        compras.criar_compra(usuario=escritorio, **dados_compra)

        assert Invoice.objects.count() == 0

    def test_importacao_do_historico_nao_gera_titulo(self, escritorio, dados_compra):
        """A planilha traz o que já foi pago fora do sistema: títulos de 2025
        apareceriam todos como vencidos."""
        compra = compras.criar_compra(usuario=escritorio, **dados_compra)
        compras.confirmar_compra(compra, usuario=escritorio, gerar_titulos=False)

        assert Invoice.objects.count() == 0

    def test_venda_gera_titulo_a_receber_do_comprador(
        self, venda, frigorifico, sao_francisco
    ):
        titulo = venda.invoices.get()

        assert titulo.direction == Direction.RECEBER
        assert titulo.component == "VENDA"
        assert titulo.payee == frigorifico
        assert titulo.amount == venda.total_value
        assert titulo.due_date == venda.date + datetime.timedelta(days=15)


class TestIdempotencia:
    def test_gerar_duas_vezes_nao_duplica(self, compra, escritorio):
        services.gerar_titulos_da_compra(compra, usuario=escritorio)
        services.gerar_titulos_da_compra(compra, usuario=escritorio)

        assert compra.invoices.count() == 1

    def test_o_banco_recusa_o_segundo_titulo_da_mesma_chave(self, compra, titulo):
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            Invoice.objects.create(
                code="TT-DUP",
                direction=Direction.PAGAR,
                component="ANIMAIS",
                season=compra.season,
                farm=compra.destination_farm,
                origin_purchase=compra,
                issue_date=compra.date,
                due_date=compra.date,
                amount=D("1"),
                status=Status.CONFIRMADA,
            )


@pytest.mark.django_db(transaction=True)
def test_confirmacao_concorrente_gera_um_titulo_nao_dois():
    from apps.accounts.models import Role, User
    from apps.costs.models import CostCenter, CostClass
    from apps.livestock.models import AnimalCategory, Sex
    from apps.organizations.models import Company, Season
    from apps.properties.models import Farm

    CostClass.objects.get_or_create(name="CUSTEIO")
    for nome in ("DESPESA GADO", "FRETE", "COMISSÃO", "IMPOSTO E TAXAS"):
        CostCenter.objects.get_or_create(name=nome)
    usuario = User.objects.create_user(username="dupla", password="x", role=Role.GESTOR)
    company = Company.objects.create(name="Fazendas Reunidas")
    Season.objects.create(
        company=company,
        name="2025/2026",
        start_date=datetime.date(2025, 7, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    farm = Farm.objects.create(name="São Francisco", code="SFR")
    categoria = AnimalCategory.objects.create(name="Machos Desm.", sex=Sex.MACHO)
    compra = compras.criar_compra(
        usuario=usuario,
        date=datetime.date(2025, 9, 18),
        destination_farm=farm,
        category=categoria,
        head_count=126,
        animal_value=D("388080"),
    )

    resultados = []
    barreira = threading.Barrier(2)

    def clicar():
        barreira.wait()
        try:
            compras.confirmar_compra(compra, usuario=usuario)
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
    assert Invoice.objects.filter(origin_purchase=compra).count() == 1


class TestAcompanhaACompra:
    def test_corrigir_o_valor_da_compra_corrige_o_titulo_e_anula_a_aprovacao(
        self, compra, titulo_aprovado, escritorio
    ):
        compras.editar_compra(
            compra,
            {"animal_value": D("380000.00")},
            usuario=escritorio,
            motivo="Valor corrigido na nota",
        )

        titulo = compra.invoices.get()
        assert titulo.status == Status.CONFIRMADA
        assert titulo.amount == D("380000.00")
        # A aprovação valia para o valor antigo.
        assert titulo.payment_status == PaymentStatus.A_PAGAR
        assert titulo.approved_by is None
        assert compra.invoices.count() == 1

    def test_corrigir_so_uma_observacao_mantem_a_aprovacao(
        self, compra, titulo_aprovado, escritorio
    ):
        compras.editar_compra(
            compra,
            {"notes": "Pagar até sexta"},
            usuario=escritorio,
            motivo="Observação",
        )

        titulo = compra.invoices.get()
        assert titulo.payment_status == PaymentStatus.APROVADO
        assert titulo.approved_by is not None

    def test_corrigir_a_data_da_compra_recalcula_o_vencimento(self, compra, escritorio):
        compras.editar_compra(
            compra,
            {"date": datetime.date(2025, 9, 20)},
            usuario=escritorio,
            motivo="Data certa",
        )

        titulo = compra.invoices.get()
        assert titulo.issue_date == datetime.date(2025, 9, 20)
        assert titulo.due_date == datetime.date(2025, 10, 20)

    def test_vencimento_ajustado_no_titulo_sobrevive_a_correcao_da_compra(
        self, compra, titulo, financeiro, escritorio
    ):
        services.editar_titulo(
            titulo,
            {"due_date": datetime.date(2025, 12, 1)},
            usuario=financeiro,
            motivo="Combinado novo prazo",
        )
        compras.editar_compra(
            compra, {"notes": "x"}, usuario=escritorio, motivo="Observação"
        )

        assert compra.invoices.get().due_date == datetime.date(2025, 12, 1)

    def test_valor_que_passa_a_existir_gera_o_titulo_novo(self, compra, escritorio):
        compras.editar_compra(
            compra,
            {"freight_value": D("4500")},
            usuario=escritorio,
            motivo="Frete esquecido",
        )

        assert compra.invoices.filter(component="FRETE", amount=D("4500")).exists()

    def test_excluir_a_compra_cancela_o_titulo_na_mesma_cascata(self, compra, gestor):
        compras.excluir_compra(compra, usuario=gestor, motivo="Duplicada")

        titulo = compra.invoices.get()
        assert titulo.status == Status.EXCLUIDA
        evento = AuditEvent.objects.filter(
            entity_type="Invoice", action="DELETE", entity_id=str(titulo.pk)
        ).get()
        assert evento.cascade_root is not None
        raiz = AuditEvent.objects.filter(cascade_root=evento.cascade_root)
        assert raiz.filter(entity_type="Purchase").exists()

    def test_restaurar_a_compra_traz_o_titulo_de_volta_com_a_aprovacao(
        self, compra, titulo_aprovado, gestor
    ):
        compras.excluir_compra(compra, usuario=gestor, motivo="Engano")
        compras.restaurar_compra(compra, usuario=gestor)

        titulo = compra.invoices.get()
        assert titulo.status == Status.CONFIRMADA
        assert titulo.payment_status == PaymentStatus.APROVADO

    def test_titulo_cancelado_a_mao_continua_cancelado_apos_corrigir_a_compra(
        self, compra, titulo, gestor, escritorio
    ):
        services.excluir_titulo(titulo, usuario=gestor, motivo="Pago em dinheiro")
        compras.editar_compra(
            compra, {"notes": "x"}, usuario=escritorio, motivo="Observação"
        )

        assert compra.invoices.get().status == Status.EXCLUIDA


class TestOperacaoDoHistorico:
    def test_gerar_para_compra_ja_confirmada_antes_do_financeiro(
        self, escritorio, dados_compra
    ):
        compra = compras.criar_compra(usuario=escritorio, **dados_compra)
        compras.confirmar_compra(compra, usuario=escritorio, gerar_titulos=False)

        gerados = services.gerar_titulos_de_operacao_existente(
            compra, usuario=escritorio
        )

        assert [t.component for t in gerados] == ["ANIMAIS"]
        assert (
            services.gerar_titulos_de_operacao_existente(compra, usuario=escritorio)[
                0
            ].pk
            == gerados[0].pk
        )

    def test_corrigir_compra_do_historico_nao_cria_titulo_sozinho(
        self, escritorio, dados_compra
    ):
        compra = compras.criar_compra(usuario=escritorio, **dados_compra)
        compra = compras.confirmar_compra(
            compra, usuario=escritorio, gerar_titulos=False
        )

        compras.editar_compra(
            compra, {"notes": "x"}, usuario=escritorio, motivo="Observação"
        )

        assert Invoice.objects.count() == 0


class TestTituloAvulso:
    def test_lancar_titulo_avulso_usa_a_conta_padrao_do_favorecido(
        self, financeiro, sao_francisco, vendedor, conta_do_vendedor
    ):
        titulo = services.criar_titulo(
            usuario=financeiro,
            direction=Direction.PAGAR,
            component="OUTRO",
            farm=sao_francisco,
            payee=vendedor,
            issue_date=datetime.date(2025, 9, 1),
            due_date=datetime.date(2025, 9, 30),
            amount=D("500"),
        )

        assert titulo.bank_account == conta_do_vendedor
        assert titulo.status == Status.CONFIRMADA

    def test_conta_de_outro_parceiro_e_recusada(
        self, financeiro, sao_francisco, outro_parceiro, conta_do_vendedor
    ):
        with pytest.raises(BusinessError, match="não é do favorecido"):
            services.criar_titulo(
                usuario=financeiro,
                direction=Direction.PAGAR,
                component="OUTRO",
                farm=sao_francisco,
                payee=outro_parceiro,
                bank_account=conta_do_vendedor,
                issue_date=datetime.date(2025, 9, 1),
                due_date=datetime.date(2025, 9, 30),
                amount=D("500"),
            )

    def test_vencimento_antes_da_emissao_e_recusado(self, financeiro, sao_francisco):
        with pytest.raises(BusinessError, match="vencimento"):
            services.criar_titulo(
                usuario=financeiro,
                direction=Direction.PAGAR,
                component="OUTRO",
                farm=sao_francisco,
                issue_date=datetime.date(2025, 9, 10),
                due_date=datetime.date(2025, 9, 1),
                amount=D("500"),
            )

    def test_campo_nao_lanca_titulo(self, campo_baixao, baixao):
        with pytest.raises(BusinessError, match="permissão"):
            services.criar_titulo(
                usuario=campo_baixao,
                direction=Direction.PAGAR,
                component="OUTRO",
                farm=baixao,
                issue_date=datetime.date(2025, 9, 1),
                due_date=datetime.date(2025, 9, 30),
                amount=D("500"),
            )

    def test_titulo_com_origem_nao_edita_o_valor(self, titulo, financeiro):
        services.editar_titulo(
            titulo,
            {"amount": D("1"), "document": "NF 123"},
            usuario=financeiro,
            motivo="Nota",
        )

        titulo.refresh_from_db()
        assert titulo.amount == D("388080.00")  # vem da compra
        assert titulo.document == "NF 123"

    def test_editar_exige_motivo(self, titulo, financeiro):
        with pytest.raises(BusinessError, match="Motivo"):
            services.editar_titulo(
                titulo, {"document": "NF"}, usuario=financeiro, motivo=" "
            )
