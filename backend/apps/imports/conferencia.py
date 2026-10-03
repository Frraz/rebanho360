"""F2-14 — conferência pós-importação: sistema × planilha.

A importação só é aceita se estes números baterem
(docs/migracao/01#conferência-pós-importação). Cada verificação diz o que
a planilha tem, o que o sistema tem, e — quando diverge — o que pode
explicar a diferença. Qualquer divergência salta aos olhos.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, Sum

from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.herd.models import HerdMovement, MovementType, WeighingAnimal
from apps.herd.services import saldo
from apps.imports import readers
from apps.imports.models import ImportKind, ImportRow, RowStatus
from apps.livestock.models import AnimalCategory
from apps.properties.models import Farm
from apps.purchases.models import Purchase
from apps.sales.models import Sale

D = Decimal

# Valores da planilha CONTROLE PASTO — safra 25/26 (docs/00-visao-geral.md).
ESPERADO = {
    "custos_lancamentos": 235,
    "custos_total": D("1046907.76"),
    "centros_com_lancamento": 11,
    "compras": 13,
    "compras_cabecas": 954,
    "compras_valor": D("2457752.15"),
    "abates_cabecas": 354,
    "vendas": 3,
    "vendas_cabecas": 354,
    "vendas_valor": D("2298586.23"),
    "pesagens_animais": 4058,
    "saldo_sao_francisco": 1954,
    "categorias": 11,
    "transferencias_nao_pareadas": 0,
}


@dataclass
class Verificacao:
    nome: str
    esperado: object
    sistema: object
    nota: str = ""

    @property
    def ok(self) -> bool:
        return self.esperado == self.sistema


def _fmt(valor) -> str:
    if isinstance(valor, Decimal):
        from apps.core.formatting import dinheiro_br

        return dinheiro_br(valor)
    return str(valor)


def conferir() -> list[Verificacao]:
    ativos = Status.CONFIRMADA

    # --- custos: os 235 da planilha, sem os que as compras geram ---
    avulsos = CostEntry.objects.filter(status=ativos, source_purchase__isnull=True)
    n_custos = avulsos.count()
    total_custos = avulsos.aggregate(t=Sum("amount"))["t"] or D("0")
    # Linhas de R$ 0,00 ignoradas por decisão: a planilha as conta, o sistema não as lança.
    zeradas = sum(
        1
        for r in ImportRow.objects.filter(
            batch__kind=ImportKind.CUSTOS, status=RowStatus.IGNORADA
        )
        if (readers.decimal_da_celula(r.raw.get("valor")) or D("0")) == 0
    )
    centros = avulsos.values("cost_center").distinct().count()

    # --- compras ---
    compras = Purchase.objects.filter(status=ativos)
    agregado = compras.aggregate(
        n=Count("id"), cab=Sum("head_count"), valor=Sum("animal_value")
    )
    custos_das_compras = CostEntry.objects.filter(
        status=ativos, source_purchase__isnull=False
    ).aggregate(t=Sum("amount"))["t"] or D("0")

    # --- vendas e pesagens ---
    vendas = Sale.objects.filter(status=ativos).aggregate(
        n=Count("id"), cab=Sum("head_count"), valor=Sum("total_value")
    )
    animais_pesados = WeighingAnimal.objects.filter(weighing__status=ativos).count()

    # --- rebanho ---
    abates = (
        HerdMovement.objects.filter(status=ativos, type=MovementType.ABATE).aggregate(
            q=Sum("quantity")
        )["q"]
        or 0
    )
    sao_francisco = Farm.objects.filter(name__iexact="São Francisco").first()
    saldo_sfr = saldo(farm=sao_francisco)["head_count"] if sao_francisco else 0

    # --- transferências: pendentes nas importações abertas ---
    # (lote já concluído também conta: o que ficou pendente continua pendente)
    orfas = (
        ImportRow.objects.filter(
            batch__kind=ImportKind.MOVIMENTACOES,
            status=RowStatus.PENDENTE,
            raw__tipo__startswith="TRANSF",
        )
        .exclude(batch__status="CANCELADO")
        .count()
    )
    pendentes_de_custo = (
        ImportRow.objects.filter(
            batch__kind=ImportKind.CUSTOS, status=RowStatus.PENDENTE
        )
        .exclude(batch__status="CANCELADO")
        .count()
    )

    nota_saldo = ""
    if saldo_sfr != ESPERADO["saldo_sao_francisco"]:
        diferenca = saldo_sfr - ESPERADO["saldo_sao_francisco"]
        nota_saldo = (
            f"diferença de {diferenca:+d} cabeças. A aba da fazenda registra só as compras que "
            "alguém lançou nela; a soma das compras da aba COMPRA DE GADO é maior. "
            "Veja o aviso na prévia da importação de movimentações."
        )

    return [
        Verificacao(
            "Lançamentos de custo (nunca 417)",
            ESPERADO["custos_lancamentos"],
            n_custos + zeradas,
            (
                f"{n_custos} lançados + {zeradas} linha(s) de R$ 0,00 ignorada(s)"
                if zeradas
                else ""
            ),
        ),
        Verificacao("Total de custos da safra", ESPERADO["custos_total"], total_custos),
        Verificacao(
            "Centros de custo com lançamento",
            ESPERADO["centros_com_lancamento"],
            centros,
        ),
        Verificacao(
            "Linhas de custo ainda pendentes (não importadas)",
            0,
            pendentes_de_custo,
            "resolva na prévia da importação de custos" if pendentes_de_custo else "",
        ),
        Verificacao("Compras confirmadas", ESPERADO["compras"], agregado["n"] or 0),
        Verificacao(
            "Cabeças compradas", ESPERADO["compras_cabecas"], agregado["cab"] or 0
        ),
        Verificacao(
            "Valor das compras", ESPERADO["compras_valor"], agregado["valor"] or D("0")
        ),
        Verificacao(
            "Custos gerados pelas compras (sem digitar de novo)",
            ESPERADO["compras_valor"],
            custos_das_compras,
        ),
        Verificacao(
            "Cabeças abatidas (movimentos)",
            ESPERADO["abates_cabecas"],
            abates,
            (
                "se passar de 354, as vendas debitaram a saída de novo em vez de "
                "adotar a que a aba da fazenda já registrou"
                if abates > ESPERADO["abates_cabecas"]
                else ""
            ),
        ),
        Verificacao(
            "Vendas e abates confirmados", ESPERADO["vendas"], vendas["n"] or 0
        ),
        Verificacao("Cabeças vendidas", ESPERADO["vendas_cabecas"], vendas["cab"] or 0),
        Verificacao(
            "Valor das vendas", ESPERADO["vendas_valor"], vendas["valor"] or D("0")
        ),
        Verificacao(
            "Animais pesados (nenhum brinco perdido)",
            ESPERADO["pesagens_animais"],
            animais_pesados,
        ),
        Verificacao(
            "Saldo São Francisco",
            ESPERADO["saldo_sao_francisco"],
            saldo_sfr,
            nota_saldo,
        ),
        Verificacao(
            "Categorias animais", ESPERADO["categorias"], AnimalCategory.objects.count()
        ),
        Verificacao(
            "Transferências não pareadas (nunca importadas em silêncio)",
            ESPERADO["transferencias_nao_pareadas"],
            orfas,
            (
                "decida cada uma na prévia: ignorar, ou definir origem e destino"
                if orfas
                else ""
            ),
        ),
    ]


def tabela_de_texto(verificacoes: list[Verificacao]) -> str:
    largura = max(len(v.nome) for v in verificacoes)
    linhas = [f"{'Verificação'.ljust(largura)}  {'Planilha':>16}  {'Sistema':>16}   "]
    linhas.append("-" * (largura + 42))
    for v in verificacoes:
        marca = "✓" if v.ok else "✗ DIVERGE"
        linhas.append(
            f"{v.nome.ljust(largura)}  {_fmt(v.esperado):>16}  {_fmt(v.sistema):>16}   {marca}"
        )
        if v.nota:
            linhas.append(f"{' ' * largura}  → {v.nota}")
    return "\n".join(linhas)
