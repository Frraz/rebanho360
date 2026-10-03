"""F2-03 — `CostAllocationService`. O teste que importa: a soma das cotas
é exatamente igual ao custo original, sem centavo perdido."""

import datetime
import random
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.costs import services
from apps.costs.allocation import (
    cabecas_dia_por_lote,
    custo_direto_do_lote,
    ratear_custos_indiretos,
    ratear_em_centavos,
)
from apps.costs.models import AllocationCriterion
from apps.herd.models import MovementType
from apps.herd.services import registrar_movimento
from apps.livestock.models import Lot

pytestmark = pytest.mark.django_db

D = Decimal


class TestRateioEmCentavos:
    def test_cem_reais_em_tres_partes_iguais_nao_perde_centavo(self):
        cotas = ratear_em_centavos(D("100.00"), {"a": D(1), "b": D(1), "c": D(1)})

        assert sum(cotas.values()) == D("100.00")
        assert sorted(cotas.values()) == [D("33.33"), D("33.33"), D("33.34")]

    def test_proporcional_aos_pesos(self):
        cotas = ratear_em_centavos(D("300.00"), {"a": D(200), "b": D(100)})

        assert cotas == {"a": D("200.00"), "b": D("100.00")}

    def test_soma_exata_para_valores_e_pesos_quaisquer(self):
        """Propriedade, não exemplo: para muitos casos aleatórios, a soma
        das cotas é exatamente o total."""
        sorteio = random.Random(360)
        for _ in range(300):
            total = D(sorteio.randint(1, 10_000_000)) / 100
            pesos = {
                i: D(sorteio.randint(1, 5000)) for i in range(sorteio.randint(1, 9))
            }
            cotas = ratear_em_centavos(total, pesos)
            if pesos:
                assert sum(cotas.values()) == total

    def test_determinismo_duas_execucoes_dao_o_mesmo_resultado(self):
        pesos = {"a": D(1), "b": D(1), "c": D(1)}

        assert ratear_em_centavos(D("0.01"), pesos) == ratear_em_centavos(
            D("0.01"), pesos
        )

    def test_sem_peso_devolve_vazio_em_vez_de_inventar_destino(self):
        assert ratear_em_centavos(D("50.00"), {}) == {}
        assert ratear_em_centavos(D("50.00"), {"a": D(0)}) == {}


@pytest.fixture
def fazenda_com_dois_lotes(baixao, season, categoria_desmamados, gestor):
    """Lote A: 100 cabeças o mês inteiro (1-30/set). Lote B: 100 cabeças
    só a partir do dia 16 — metade do mês."""
    lote_a = Lot.objects.create(
        code="LT-BXO-A",
        farm=baixao,
        season=season,
        entry_date=datetime.date(2025, 9, 1),
    )
    lote_b = Lot.objects.create(
        code="LT-BXO-B",
        farm=baixao,
        season=season,
        entry_date=datetime.date(2025, 9, 16),
    )
    for lote, dia in ((lote_a, 1), (lote_b, 16)):
        registrar_movimento(
            type=MovementType.COMPRA,
            date=datetime.date(2025, 9, dia),
            quantity=100,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote,
            destination_category=categoria_desmamados,
        )
    return lote_a, lote_b


class TestCabecaDia:
    def test_mes_inteiro_pesa_o_dobro_de_meio_mes(self, baixao, fazenda_com_dois_lotes):
        lote_a, lote_b = fazenda_com_dois_lotes

        pesos = cabecas_dia_por_lote(
            farm=baixao, start=datetime.date(2025, 9, 1), end=datetime.date(2025, 9, 30)
        )

        assert pesos[lote_a.pk] == D(3000)  # 100 × 30 dias
        assert pesos[lote_b.pk] == D(1500)  # 100 × 15 dias (16 a 30)

    def test_saldo_anterior_ao_periodo_conta_desde_o_primeiro_dia(
        self, baixao, fazenda_com_dois_lotes
    ):
        lote_a, _ = fazenda_com_dois_lotes

        pesos = cabecas_dia_por_lote(
            farm=baixao,
            start=datetime.date(2025, 9, 20),
            end=datetime.date(2025, 9, 29),
        )

        assert pesos[lote_a.pk] == D(1000)  # 100 × 10 dias

    def test_morte_no_meio_do_periodo_reduz_o_peso(
        self, baixao, fazenda_com_dois_lotes, categoria_desmamados, gestor
    ):
        lote_a, _ = fazenda_com_dois_lotes
        registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 9, 11),
            quantity=10,
            usuario=gestor,
            origin_farm=baixao,
            origin_lot=lote_a,
            origin_category=categoria_desmamados,
            reason="Causa desconhecida",
        )

        pesos = cabecas_dia_por_lote(
            farm=baixao, start=datetime.date(2025, 9, 1), end=datetime.date(2025, 9, 30)
        )

        # 100 × 10 dias (1-10) + 90 × 20 dias (11-30)
        assert pesos[lote_a.pk] == D(2800)


class TestRateioDeCustosIndiretos:
    def _custo(self, usuario, farm, centro, classe, valor, **kw):
        return services.registrar_custo(
            date=datetime.date(2025, 9, 10),
            farm=farm,
            cost_center=centro,
            cost_class=classe,
            amount=D(valor),
            description="Item",
            usuario=usuario,
            **kw,
        )

    def test_soma_das_cotas_e_exatamente_o_custo_original(
        self, baixao, gestor, fazenda_com_dois_lotes, centro_funcionario, custeio
    ):
        self._custo(gestor, baixao, centro_funcionario, custeio, "10000.01")
        self._custo(gestor, baixao, centro_funcionario, custeio, "333.33")

        resultado = ratear_custos_indiretos(
            farm=baixao, start=datetime.date(2025, 9, 1), end=datetime.date(2025, 9, 30)
        )

        assert resultado.total == D("10333.34")
        assert sum(resultado.cotas_por_lote.values()) == D("10333.34")
        assert resultado.sem_base == 0

    def test_lote_de_mes_inteiro_absorve_o_dobro(
        self, baixao, gestor, fazenda_com_dois_lotes, centro_funcionario, custeio
    ):
        lote_a, lote_b = fazenda_com_dois_lotes
        self._custo(gestor, baixao, centro_funcionario, custeio, "900.00")

        resultado = ratear_custos_indiretos(
            farm=baixao, start=datetime.date(2025, 9, 1), end=datetime.date(2025, 9, 30)
        )

        assert resultado.cotas_por_lote == {
            lote_a.pk: D("600.00"),
            lote_b.pk: D("300.00"),
        }

    def test_o_criterio_aplicado_fica_gravado_no_resultado(
        self, baixao, gestor, fazenda_com_dois_lotes, centro_funcionario, custeio
    ):
        self._custo(gestor, baixao, centro_funcionario, custeio, "100.00")

        resultado = ratear_custos_indiretos(
            farm=baixao, start=datetime.date(2025, 9, 1), end=datetime.date(2025, 9, 30)
        )

        assert resultado.centros[0].criterio == AllocationCriterion.POR_CABECA_DIA
        assert resultado.centros[0].criterio_rotulo == "Cabeça-dia"

    def test_custo_direto_vai_inteiro_ao_lote_e_nao_entra_no_rateio(
        self, baixao, gestor, fazenda_com_dois_lotes, centro_funcionario, custeio
    ):
        lote_a, _ = fazenda_com_dois_lotes
        self._custo(gestor, baixao, centro_funcionario, custeio, "500.00", lot=lote_a)
        self._custo(gestor, baixao, centro_funcionario, custeio, "100.00")

        resultado = ratear_custos_indiretos(
            farm=baixao, start=datetime.date(2025, 9, 1), end=datetime.date(2025, 9, 30)
        )

        assert resultado.total == D("100.00")
        assert custo_direto_do_lote(lote_a) == D("500.00")

    def test_centro_pode_usar_outro_criterio(
        self, baixao, gestor, fazenda_com_dois_lotes, centro_funcionario, custeio
    ):
        lote_a, lote_b = fazenda_com_dois_lotes
        centro_funcionario.allocation_criterion = AllocationCriterion.POR_CABECA_SIMPLES
        centro_funcionario.save()
        self._custo(gestor, baixao, centro_funcionario, custeio, "100.00")

        resultado = ratear_custos_indiretos(
            farm=baixao, start=datetime.date(2025, 9, 1), end=datetime.date(2025, 9, 30)
        )

        # Os dois têm 100 cabeças no fim do período: metade para cada.
        assert resultado.cotas_por_lote == {
            lote_a.pk: D("50.00"),
            lote_b.pk: D("50.00"),
        }

    def test_arroba_produzida_diz_que_depende_da_fase_3(
        self, baixao, gestor, fazenda_com_dois_lotes, centro_funcionario, custeio
    ):
        centro_funcionario.allocation_criterion = (
            AllocationCriterion.POR_ARROBA_PRODUZIDA
        )
        centro_funcionario.save()
        self._custo(gestor, baixao, centro_funcionario, custeio, "100.00")

        with pytest.raises(BusinessError, match="Fase 3"):
            ratear_custos_indiretos(
                farm=baixao,
                start=datetime.date(2025, 9, 1),
                end=datetime.date(2025, 9, 30),
            )

    def test_rateio_manual_exige_os_pesos(
        self, baixao, gestor, fazenda_com_dois_lotes, centro_funcionario, custeio
    ):
        lote_a, lote_b = fazenda_com_dois_lotes
        centro_funcionario.allocation_criterion = AllocationCriterion.MANUAL
        centro_funcionario.save()
        self._custo(gestor, baixao, centro_funcionario, custeio, "100.00")
        periodo = {
            "farm": baixao,
            "start": datetime.date(2025, 9, 1),
            "end": datetime.date(2025, 9, 30),
        }

        with pytest.raises(BusinessError, match="rateio manual"):
            ratear_custos_indiretos(**periodo)

        resultado = ratear_custos_indiretos(
            **periodo,
            pesos_manuais={centro_funcionario.pk: {lote_a.pk: D(3), lote_b.pk: D(1)}},
        )
        assert resultado.cotas_por_lote == {
            lote_a.pk: D("75.00"),
            lote_b.pk: D("25.00"),
        }

    def test_fazenda_sem_animais_nao_some_com_o_dinheiro(
        self, baixao, gestor, centro_funcionario, custeio, season
    ):
        self._custo(gestor, baixao, centro_funcionario, custeio, "100.00")

        resultado = ratear_custos_indiretos(
            farm=baixao, start=datetime.date(2025, 9, 1), end=datetime.date(2025, 9, 30)
        )

        assert resultado.cotas_por_lote == {}
        assert resultado.sem_base == D("100.00")
        assert resultado.total == D("100.00")
