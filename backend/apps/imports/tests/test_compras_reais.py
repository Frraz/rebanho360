"""F2-11 — importador de COMPRA DE GADO contra a planilha real: 13
compras, 954 cabeças, R$ 2.457.752,15, sem digitação dupla."""

from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.herd import services as herd
from apps.herd.models import HerdMovement, MovementType
from apps.imports import services
from apps.imports.models import ImportKind, RowStatus
from apps.imports.tests.conftest import precisa_da_planilha, upload_real
from apps.livestock.models import AnimalCategory, Lot
from apps.properties.models import Farm
from apps.purchases.models import Purchase

pytestmark = [pytest.mark.django_db, precisa_da_planilha]

D = Decimal


@pytest.fixture
def previa(usuario_escritorio):
    return services.criar_importacao(
        kind=ImportKind.COMPRAS, arquivo=upload_real(), usuario=usuario_escritorio
    )


def mapear_bezerros(batch, usuario):
    categoria = AnimalCategory.objects.get(name="Machos Desm. até 12m")
    return services.salvar_opcoes(
        batch, {"category_map": {"bezerros": categoria.pk}}, usuario=usuario
    )


class TestPrevia:
    def test_bezerros_sem_mapeamento_ficam_pendentes_com_sugestao_a_confirmar(
        self, previa
    ):
        resumo = services.resumo_da_previa(previa)

        assert resumo["prontas"] == 0
        assert resumo["pendentes"] == 13
        pendencia = previa.rows.first().pendencias[0]
        assert pendencia["campo"] == "category"
        assert pendencia["sugestao"]["rotulo"] == "Machos Desm. até 12m"
        assert pendencia["sugestao"]["motivo"] == "a confirmar com o produtor"

    def test_apos_confirmar_o_mapeamento_as_13_ficam_prontas(
        self, previa, usuario_escritorio
    ):
        previa = mapear_bezerros(previa, usuario_escritorio)

        resumo = services.resumo_da_previa(previa)

        assert (resumo["prontas"], resumo["pendentes"], resumo["erros"]) == (13, 0, 0)
        assert resumo["lidas"] == 732  # a aba tem centenas de linhas de #DIV/0!
        assert resumo["em_branco"] == 719

    def test_fazenda_casa_pelo_nome_sem_precisar_de_mapeamento(
        self, previa, usuario_escritorio
    ):
        previa = mapear_bezerros(previa, usuario_escritorio)

        assert not any(
            m["campo"] == "destination_farm"
            for r in previa.rows.all()
            for m in r.pendencias
        )

    def test_nada_e_gravado_antes_da_confirmacao(self, previa, usuario_escritorio):
        mapear_bezerros(previa, usuario_escritorio)

        assert Purchase.objects.count() == 0
        assert HerdMovement.objects.count() == 0
        assert CostEntry.objects.count() == 0


class TestImportacao:
    @pytest.fixture
    def importada(self, previa, usuario_escritorio):
        previa = mapear_bezerros(previa, usuario_escritorio)
        return services.importar(previa, usuario=usuario_escritorio)

    def test_13_compras_confirmadas_954_cabecas_e_2_457_752_15(self, importada):
        assert importada["importadas"] == 13
        assert importada["cabecas"] == 954
        assert importada["total"] == D("2457752.15")
        compras = Purchase.objects.all()
        assert compras.count() == 13
        assert all(c.status == Status.CONFIRMADA for c in compras)
        assert compras.aggregate(t=Sum("animal_value"))["t"] == D("2457752.15")

    def test_954_cabecas_entraram_no_rebanho_sem_digitacao_dupla(self, importada):
        sao_francisco = Farm.objects.get(code="SFR")

        assert herd.saldo(farm=sao_francisco)["head_count"] == 954
        movimentos = HerdMovement.objects.filter(type=MovementType.COMPRA)
        assert movimentos.count() == 13  # um por compra, não dois

    def test_2_457_752_15_em_custos_gerados_pelas_compras(self, importada):
        custos = CostEntry.objects.filter(source_purchase__isnull=False)

        assert custos.count() == 13  # frete/comissão/impostos vazios na planilha
        assert custos.aggregate(t=Sum("amount"))["t"] == D("2457752.15")
        assert {c.cost_center.name for c in custos} == {"DESPESA GADO"}

    def test_um_lote_por_compra_e_a_compra_de_105_bezerros_bate_com_a_planilha(
        self, importada
    ):
        assert Lot.objects.count() == 13
        compra = Purchase.objects.get(head_count=105)

        assert compra.animal_value == D("260172.15")
        from apps.purchases.services import custo_da_compra

        assert custo_da_compra(compra).media_por_cabeca.quantize(D("0.01")) == D(
            "2477.83"
        )

    def test_cada_linha_aponta_para_a_compra_que_criou(self, importada):
        from apps.imports.models import ImportRow

        linhas = ImportRow.objects.filter(status=RowStatus.IMPORTADA)

        assert linhas.count() == 13
        assert all(isinstance(lin.target, Purchase) for lin in linhas)

    def test_mesmo_arquivo_de_novo_e_detectado(self, importada, usuario_escritorio):
        with pytest.raises(services.ImportacaoDuplicada):
            services.criar_importacao(
                kind=ImportKind.COMPRAS,
                arquivo=upload_real(),
                usuario=usuario_escritorio,
            )

    def test_compra_importada_e_editavel_e_excluivel_como_qualquer_outra(
        self, importada, usuario_gestor
    ):
        from apps.purchases import services as compras

        compra = Purchase.objects.get(head_count=126)

        compras.excluir_compra(
            compra, usuario=usuario_gestor, motivo="Importada duplicada"
        )

        compra.refresh_from_db()
        assert compra.status == Status.EXCLUIDA
        assert herd.saldo(farm=compra.destination_farm)["head_count"] == 954 - 126
