"""F3-06 — `WeightGainService`: GMD e @ produzida.

Regra que o teste trava: **não se estima peso de entrada**. Sem pesagem
inicial, GMD é `None` e a tela diz por quê.
"""

import datetime
from decimal import Decimal

import pytest

from apps.herd import services
from apps.herd.models import WeighingReason
from apps.herd.weight_gain import desempenho_do_lote, gmd_do_ultimo_trecho

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture(autouse=True)
def custos_semeados(db):
    """A compra gera custos, e precisa da classe CUSTEIO e dos centros."""
    from apps.costs.seed import garantir_classes_e_centros

    garantir_classes_e_centros()


def pesar(lote, farm, usuario, dia, cabecas, kg, motivo=WeighingReason.CONFERENCIA):
    return services.registrar_pesagem(
        date=dia,
        farm=farm,
        lot=lote,
        reason=motivo,
        head_count=cabecas,
        total_weight_kg=D(kg),
        usuario=usuario,
    )


class TestGmd:
    def test_sem_pesagem_nenhuma_e_none_com_motivo(self, lote_baixao):
        d = desempenho_do_lote(lote_baixao)
        assert d.gmd is None and d.trechos == ()
        assert "sem pesagem registrada" in d.motivos[0]

    def test_so_uma_pesagem_e_none_com_motivo(self, lote_baixao, baixao, gestor):
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 9, 1), 10, "2000")
        d = desempenho_do_lote(lote_baixao)
        assert d.gmd is None
        assert "só há uma pesagem" in d.motivos[0]
        assert gmd_do_ultimo_trecho(lote_baixao) is None

    def test_duas_pesagens_do_mesmo_dia_nao_dao_gmd(self, lote_baixao, baixao, gestor):
        dia = datetime.date(2025, 9, 1)
        pesar(lote_baixao, baixao, gestor, dia, 10, "2000")
        pesar(lote_baixao, baixao, gestor, dia, 10, "2100")
        assert desempenho_do_lote(lote_baixao).gmd is None

    def test_gmd_entre_duas_pesagens(self, lote_baixao, baixao, gestor):
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 9, 1), 10, "2000")
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 9, 11), 10, "2074")

        d = desempenho_do_lote(lote_baixao)

        assert d.gmd == D("0.74")
        assert d.dias == 10
        assert d.ganho_por_cabeca_kg == D("7.4")

    def test_sem_pesagem_de_entrada_o_gmd_diz_que_cobre_so_o_periodo_pesado(
        self, lote_baixao, baixao, gestor
    ):
        """O peso de entrada não é estimado: o GMD existe, mas a tela avisa
        que ele não é do lote inteiro."""
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 9, 1), 10, "2000")
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 9, 11), 10, "2074")

        d = desempenho_do_lote(lote_baixao)

        assert not d.gmd_desde_a_entrada
        assert any("Sem pesagem de entrada" in m for m in d.motivos)

    def test_com_pesagem_de_compra_o_gmd_e_desde_a_entrada(
        self, lote_baixao, baixao, gestor
    ):
        pesar(
            lote_baixao,
            baixao,
            gestor,
            datetime.date(2025, 9, 1),
            10,
            "1500",
            motivo=WeighingReason.COMPRA,
        )
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 10, 1), 10, "1800")

        d = desempenho_do_lote(lote_baixao)

        assert d.gmd_desde_a_entrada
        assert d.gmd == D("1")  # 30 kg por cabeça em 30 dias
        assert not any("Sem pesagem de entrada" in m for m in d.motivos)

    def test_gmd_total_e_por_trecho_sao_coisas_diferentes(
        self, lote_baixao, baixao, gestor
    ):
        pesar(
            lote_baixao,
            baixao,
            gestor,
            datetime.date(2025, 9, 1),
            10,
            "1500",
            motivo=WeighingReason.COMPRA,
        )
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 10, 1), 10, "1800")
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 10, 11), 10, "1850")

        d = desempenho_do_lote(lote_baixao)

        assert [t.gmd for t in d.trechos] == [D("1"), D("0.5")]
        assert gmd_do_ultimo_trecho(lote_baixao) == D("0.5")
        # Do primeiro ao último: 35 kg/cabeça em 40 dias.
        assert d.gmd == D("0.875")

    def test_cabecas_pesadas_diferentes_usam_peso_medio_nao_total(
        self, lote_baixao, baixao, gestor
    ):
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 9, 1), 10, "2000")
        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 9, 11), 20, "4148")
        assert desempenho_do_lote(lote_baixao).gmd == D("0.74")

    def test_pesagem_excluida_nao_conta(self, lote_baixao, baixao, gestor):
        from apps.core import reversible

        pesar(lote_baixao, baixao, gestor, datetime.date(2025, 9, 1), 10, "2000")
        ultima = pesar(
            lote_baixao, baixao, gestor, datetime.date(2025, 9, 11), 10, "2074"
        )
        reversible.excluir(ultima, usuario=gestor, motivo="digitada errado")
        assert desempenho_do_lote(lote_baixao).gmd is None

    def test_peso_informado_na_compra_serve_de_entrada(
        self, season, baixao, gestor, categoria_desmamados
    ):
        from apps.purchases import services as compras

        compra = compras.criar_compra(
            usuario=gestor,
            date=datetime.date(2025, 9, 1),
            destination_farm=baixao,
            category=categoria_desmamados,
            head_count=10,
            total_weight_kg=D("1500"),
            animal_value=D("20000"),
        )
        compra = compras.confirmar_compra(compra, usuario=gestor)
        lote = compra.lot
        pesar(lote, baixao, gestor, datetime.date(2025, 10, 1), 10, "1800")

        d = desempenho_do_lote(lote)

        assert d.gmd_desde_a_entrada and d.gmd == D("1")
        assert d.primeiro.origem == "Peso informado na compra"

    def test_compra_sem_peso_nao_vira_peso_de_entrada(
        self, season, baixao, gestor, categoria_desmamados
    ):
        from apps.purchases import services as compras

        compra = compras.criar_compra(
            usuario=gestor,
            date=datetime.date(2025, 9, 1),
            destination_farm=baixao,
            category=categoria_desmamados,
            head_count=10,
            animal_value=D("20000"),
        )
        compra = compras.confirmar_compra(compra, usuario=gestor)
        pesar(compra.lot, baixao, gestor, datetime.date(2025, 10, 1), 10, "1800")

        d = desempenho_do_lote(compra.lot)

        assert d.gmd is None  # uma pesagem só; peso de entrada NÃO foi inventado
        assert not d.gmd_desde_a_entrada


class TestArrobasProduzidas:
    """Lote de 10 cabeças: entrada a 150 kg vivos; abate com 2.400 kg de
    carcaça. Com rendimento de entrada de 50%: carcaça de entrada
    = 150 × 10 × 50% = 750 kg → (2.400 − 750) ÷ 15 = 110 @."""

    @pytest.fixture
    def lote_abatido(self, season, baixao, gestor, categoria_desmamados):
        from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
        from apps.purchases import services as compras
        from apps.sales import services as vendas

        compra = compras.criar_compra(
            usuario=gestor,
            date=datetime.date(2025, 9, 1),
            destination_farm=baixao,
            category=categoria_desmamados,
            head_count=10,
            total_weight_kg=D("1500"),
            animal_value=D("20000"),
        )
        compra = compras.confirmar_compra(compra, usuario=gestor)
        frigorifico = Partner.objects.create(name="COPERFRIGU")
        PartnerRole.objects.create(
            partner=frigorifico, role=PartnerRoleChoice.FRIGORIFICO
        )
        venda = vendas.criar_venda(
            usuario=gestor,
            date=datetime.date(2026, 3, 1),
            type="ABATE",
            buyer=frigorifico,
            farm=baixao,
            lot=compra.lot,
            category=categoria_desmamados,
            head_count=10,
            total_weight_kg=D("5000"),
            carcass_weight_kg=D("2400"),
            total_value=D("40000"),
        )
        vendas.confirmar_venda(venda, usuario=gestor)
        return compra.lot

    def test_com_rendimento_informado_e_marcada_como_estimativa(self, lote_abatido):
        d = desempenho_do_lote(lote_abatido, rendimento_entrada=D("50"))

        assert d.arrobas_produzidas == D("110")
        assert d.arrobas_estimadas
        assert d.cabecas_abatidas == 10
        assert d.rendimento_entrada == D("50")

    def test_sem_rendimento_informado_nao_ha_arroba_produzida(self, lote_abatido):
        """Pendência #15: ninguém disse qual rendimento usar, o sistema não escolhe."""
        d = desempenho_do_lote(lote_abatido)

        assert d.arrobas_produzidas is None and not d.arrobas_estimadas
        assert any("rendimento de entrada estimado" in m for m in d.motivos)

    @pytest.mark.parametrize("invalido", [D("0"), D("100"), D("-5"), D("150")])
    def test_rendimento_fora_de_0_a_100_e_recusado(self, lote_abatido, invalido):
        d = desempenho_do_lote(lote_abatido, rendimento_entrada=invalido)
        assert d.arrobas_produzidas is None
        assert any("entre 0% e 100%" in m for m in d.motivos)

    def test_lote_sem_abate_nao_tem_arroba_produzida(self, lote_baixao):
        d = desempenho_do_lote(lote_baixao, rendimento_entrada=D("50"))
        assert d.arrobas_produzidas is None
        assert any(
            "sem abate confirmado" in m or "não tem abate" in m for m in d.motivos
        )

    def test_abate_sem_carcaca_nao_tem_arroba_produzida(self, lote_abatido, gestor):
        from apps.sales import services as vendas
        from apps.sales.models import Sale

        venda = Sale.objects.get(lot=lote_abatido)
        vendas.editar_venda(
            venda, {"carcass_weight_kg": None}, usuario=gestor, motivo="romaneio errado"
        )
        d = desempenho_do_lote(lote_abatido, rendimento_entrada=D("50"))
        assert d.arrobas_produzidas is None
        assert any("sem peso de carcaça" in m for m in d.motivos)
