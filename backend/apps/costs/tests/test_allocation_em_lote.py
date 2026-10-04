"""O rateio em lote (`BaseDeRateio`) e a cabeça-dia em SQL têm de dar **o mesmo
número** da conta original, que lia o razão inteiro em Python a cada chamada.

A implementação antiga fica aqui, no teste, como oráculo: se a otimização mudar
um centavo ou uma cabeça-dia em qualquer razão sorteada, este teste quebra.
"""

import datetime
import random
from collections import defaultdict
from decimal import Decimal

import pytest

from apps.costs import services
from apps.costs.allocation import (
    BaseDeRateio,
    cabecas_dia_por_lote,
    cabecas_no_fim_por_lote,
    ratear_custos_indiretos,
    ratear_em_centavos,
)
from apps.costs.models import AllocationCriterion, CostCenter
from apps.herd.models import HerdLedgerEntry, MovementType
from apps.herd.services import registrar_movimento
from apps.livestock.models import Lot

pytestmark = pytest.mark.django_db

D = Decimal
INICIO = datetime.date(2025, 9, 1)


def cabecas_dia_original(*, farm, start, end):
    """A conta de antes da otimização, linha a linha em Python."""
    linhas = (
        HerdLedgerEntry.objects.filter(farm=farm, date__lte=end)
        .order_by("date", "id")
        .values_list("lot_id", "date", "quantity")
    )
    saldo_antes, eventos = defaultdict(int), defaultdict(list)
    for lot_id, data, quantidade in linhas:
        if data < start:
            saldo_antes[lot_id] += quantidade
        else:
            eventos[lot_id].append((data, quantidade))
    resultado = {}
    for lot_id in sorted(set(saldo_antes) | set(eventos)):
        atual, cursor, acumulado = saldo_antes[lot_id], start, 0
        for data, quantidade in eventos[lot_id]:
            acumulado += atual * (data - cursor).days
            atual += quantidade
            cursor = data
        acumulado += atual * ((end - cursor).days + 1)
        if acumulado > 0:
            resultado[lot_id] = D(acumulado)
    return resultado


@pytest.fixture
def razao_sorteado(baixao, season, categoria_desmamados, gestor):
    """Vários lotes, entradas em dias diferentes e mortes no meio do caminho."""
    sorteio = random.Random(360)
    lotes = []
    for n in range(7):
        entrada = INICIO + datetime.timedelta(days=sorteio.randint(0, 40))
        lote = Lot.objects.create(
            code=f"LT-RND-{n}", farm=baixao, season=season, entry_date=entrada
        )
        cabecas = sorteio.randint(20, 300)
        registrar_movimento(
            type=MovementType.COMPRA,
            date=entrada,
            quantity=cabecas,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote,
            destination_category=categoria_desmamados,
        )
        for _ in range(sorteio.randint(0, 4)):
            mortes = sorteio.randint(1, max(1, cabecas // 10))
            if mortes >= cabecas:
                break
            registrar_movimento(
                type=MovementType.MORTE,
                date=entrada + datetime.timedelta(days=sorteio.randint(1, 60)),
                quantity=mortes,
                usuario=gestor,
                origin_farm=baixao,
                origin_lot=lote,
                origin_category=categoria_desmamados,
                reason="Causa desconhecida",
            )
            cabecas -= mortes
        lotes.append(lote)
    return lotes


JANELAS = (
    (datetime.date(2025, 9, 1), datetime.date(2025, 9, 30)),
    (datetime.date(2025, 9, 20), datetime.date(2025, 9, 29)),
    (datetime.date(2025, 10, 5), datetime.date(2025, 12, 31)),
    (datetime.date(2025, 9, 15), datetime.date(2025, 9, 15)),  # um dia só
    (datetime.date(2025, 8, 1), datetime.date(2026, 3, 1)),  # começa antes de tudo
    (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30)),  # só saldo anterior
)


class TestCabecaDiaIgualAoOriginal:
    def test_sql_e_a_conta_antiga_dao_o_mesmo_numero(self, baixao, razao_sorteado):
        com_dado = 0
        for start, end in JANELAS:
            esperado = cabecas_dia_original(farm=baixao, start=start, end=end)
            assert cabecas_dia_por_lote(farm=baixao, start=start, end=end) == esperado
            com_dado += bool(esperado)
        assert com_dado >= 4, "o sorteio não exercitou a cabeça-dia"

    def test_base_em_memoria_e_a_conta_antiga_dao_o_mesmo_numero(
        self, baixao, razao_sorteado
    ):
        base = BaseDeRateio(baixao)
        for start, end in JANELAS:
            assert base.cabecas_dia(start, end) == cabecas_dia_original(
                farm=baixao, start=start, end=end
            )

    def test_cabecas_no_fim_do_periodo(self, baixao, razao_sorteado):
        base = BaseDeRateio(baixao)
        for _, end in JANELAS:
            assert base.cabecas_no_fim(end) == cabecas_no_fim_por_lote(
                farm=baixao, end=end
            )

    def test_lotes_sem_movimento_no_periodo_ficam_de_fora(self, baixao):
        assert cabecas_dia_por_lote(farm=baixao, start=INICIO, end=INICIO) == {}
        assert BaseDeRateio(baixao).cabecas_dia(INICIO, INICIO) == {}

    def test_base_lida_ate_uma_data_recusa_data_posterior(self, baixao):
        base = BaseDeRateio(baixao, ate=datetime.date(2025, 9, 30))
        with pytest.raises(ValueError, match="2025-10-01"):
            base.cabecas_dia(INICIO, datetime.date(2025, 10, 1))


class TestRateioEmLoteIgualAoOriginal:
    def _custos(self, gestor, baixao, custeio):
        sorteio = random.Random(7)
        centros = list(CostCenter.objects.order_by("id")[:3])
        for centro in centros:
            for _ in range(5):
                services.registrar_custo(
                    date=INICIO + datetime.timedelta(days=sorteio.randint(0, 120)),
                    farm=baixao,
                    cost_center=centro,
                    cost_class=custeio,
                    amount=D(sorteio.randint(1, 900_000)) / 100,
                    description="Item",
                    usuario=gestor,
                )
        # um centro por cada critério que depende do razão
        for centro, criterio in zip(
            centros,
            (
                AllocationCriterion.POR_CABECA_DIA,
                AllocationCriterion.POR_CABECA_SIMPLES,
                AllocationCriterion.POR_CABECA_DIA,
            ),
            strict=True,
        ):
            centro.allocation_criterion = criterio
            centro.save(update_fields=["allocation_criterion"])

    def _original(self, farm, start, end):
        """Rateio com a leitura antiga: mesmos centros, pesos pela conta antiga."""
        from django.db.models import Sum

        from apps.core.reversible import Status
        from apps.costs.models import CostEntry

        totais = (
            CostEntry.objects.filter(
                farm=farm,
                status=Status.CONFIRMADA,
                lot__isnull=True,
                date__gte=start,
                date__lte=end,
            )
            .values("cost_center_id")
            .annotate(total=Sum("amount"))
            .order_by("cost_center_id")
        )
        saida = {}
        for linha in totais:
            centro = CostCenter.objects.get(pk=linha["cost_center_id"])
            if centro.allocation_criterion == AllocationCriterion.POR_CABECA_DIA:
                pesos = cabecas_dia_original(farm=farm, start=start, end=end)
            else:
                pesos = cabecas_no_fim_por_lote(farm=farm, end=end)
            saida[centro.pk] = (
                linha["total"],
                ratear_em_centavos(linha["total"], pesos),
            )
        return saida

    def test_cotas_de_cada_centro_sao_as_mesmas(
        self, baixao, gestor, custeio, razao_sorteado
    ):
        self._custos(gestor, baixao, custeio)
        base = BaseDeRateio(baixao)

        comparadas = 0
        for start, end in JANELAS:
            esperado = self._original(baixao, start, end)
            obtido = base.ratear(start=start, end=end)
            assert {c.centro.pk: (c.total, c.cotas) for c in obtido.centros} == esperado
            comparadas += sum(1 for _, cotas in esperado.values() if cotas)
        assert comparadas >= 5, "o sorteio não exercitou o rateio"

    def test_o_atalho_de_uma_janela_so_tambem_confere(
        self, baixao, gestor, custeio, razao_sorteado
    ):
        self._custos(gestor, baixao, custeio)
        start, end = JANELAS[0]

        obtido = ratear_custos_indiretos(farm=baixao, start=start, end=end)

        assert {c.centro.pk: (c.total, c.cotas) for c in obtido.centros} == (
            self._original(baixao, start, end)
        )

    def test_soma_das_cotas_continua_sendo_o_custo_exato(
        self, baixao, gestor, custeio, razao_sorteado
    ):
        self._custos(gestor, baixao, custeio)
        base = BaseDeRateio(baixao)
        for start, end in JANELAS:
            for centro in base.ratear(start=start, end=end).centros:
                if centro.cotas:
                    assert sum(centro.cotas.values(), D("0")) == centro.total


def ratear_em_centavos_original(total: Decimal, pesos: dict) -> dict:
    """O maior resto em `Decimal` de alta precisão, como era antes de o caminho
    de pesos inteiros ser feito em `int`."""
    from decimal import ROUND_FLOOR, localcontext

    cent = Decimal("0.01")
    positivos = {k: p for k, p in pesos.items() if p > 0}
    soma = sum(positivos.values(), Decimal("0"))
    if not positivos or soma <= 0:
        return {}
    with localcontext() as ctx:
        ctx.prec = 60
        centavos = int((total / cent).to_integral_value())
        exatos = {k: Decimal(centavos) * p / soma for k, p in positivos.items()}
        pisos = {
            k: int(v.to_integral_value(rounding=ROUND_FLOOR)) for k, v in exatos.items()
        }
        resto = centavos - sum(pisos.values())
        ordem = sorted(
            positivos,
            key=lambda k: (-(exatos[k] - pisos[k]), list(positivos).index(k)),
        )
        for chave in ordem[:resto]:
            pisos[chave] += 1
    return {k: Decimal(v) * cent for k, v in pisos.items()}


def ratear_exato(total: Decimal, pesos: dict) -> dict:
    """A regra do rateio com frações exatas (`Fraction`): piso de cada cota e os
    centavos que sobram para as maiores frações; empate pela ordem de entrada."""
    from fractions import Fraction

    positivos = {k: p for k, p in pesos.items() if p > 0}
    soma = sum(positivos.values(), Decimal("0"))
    if not positivos or soma <= 0:
        return {}
    centavos = int((total / Decimal("0.01")).to_integral_value())
    exatos = {
        k: Fraction(centavos) * Fraction(p) / Fraction(soma)
        for k, p in positivos.items()
    }
    pisos = {k: v.numerator // v.denominator for k, v in exatos.items()}
    ordem = sorted(
        positivos, key=lambda k: (-(exatos[k] - pisos[k]), list(positivos).index(k))
    )
    for chave in ordem[: centavos - sum(pisos.values())]:
        pisos[chave] += 1
    return {k: Decimal(v) * Decimal("0.01") for k, v in pisos.items()}


def _sorteio_de_pesos(sorteio):
    total = D(sorteio.randint(1, 50_000_000)) / 100
    n = sorteio.randint(1, 14)
    teto = sorteio.choice((3, 40, 5000, 10**7))  # pesos pequenos geram empate
    return total, {i: D(sorteio.randint(0, teto)) for i in range(n)}


class TestRateioEmCentavosInteiros:
    def test_pesos_inteiros_seguem_a_regra_exata_inclusive_nos_empates(self):
        sorteio = random.Random(2026)
        for _ in range(3000):
            total, pesos = _sorteio_de_pesos(sorteio)
            assert ratear_em_centavos(total, pesos) == ratear_exato(total, pesos)

    def test_sem_empate_da_o_mesmo_numero_que_a_conta_decimal_antiga(self):
        """Onde a divisão não empata, a conta antiga e a nova coincidem: a mudança
        só desfaz o ruído de arredondamento que decidia os empates."""
        sorteio = random.Random(7)
        comparados = 0
        for _ in range(3000):
            total, pesos = _sorteio_de_pesos(sorteio)
            positivos = {k: p for k, p in pesos.items() if p > 0}
            if not positivos:
                continue
            soma = int(sum(positivos.values()))
            centavos = int((total / Decimal("0.01")).to_integral_value())
            restos = [centavos * int(p) % soma for p in positivos.values()]
            if len(set(restos)) != len(restos):
                continue  # há empate de fração: a antiga decidia no ruído
            comparados += 1
            assert ratear_em_centavos(total, pesos) == ratear_em_centavos_original(
                total, pesos
            )
        assert comparados > 300

    def test_pesos_fracionados_seguem_o_caminho_decimal(self):
        pesos = {"a": D("1.5"), "b": D("2.5"), "c": D("3.25")}
        assert ratear_em_centavos(D("100.00"), pesos) == ratear_em_centavos_original(
            D("100.00"), pesos
        )
