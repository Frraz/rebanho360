"""`SaleResultService` — o resultado do lote: *o boi pagou o que custou criar?*

    resultado = receita − aquisição − custos diretos − custos rateados
    margem/@  = valor recebido por @ − custo por @

Fonte única: tela do lote, relatório de resultado e dashboard. Os custos vêm
de `financeiro_do_lote` (a mesma conta que a tela do lote já mostra) — nada
é recalculado aqui. Nenhum derivado é gravado (regra 6): "congelar" o
resultado do lote encerrado é o período terminar na `exit_date`, não um
campo com o número.

Decisões registradas na pendência #14 (reversíveis, isoladas neste módulo):

- `custo/@` = custo do lote ÷ @ de carcaça **vendida**. Assim
  `resultado = margem/@ × @ vendidas` fecha exato.
- Lote **ainda com animais** mostra resultado **parcial**: o custo é rateado
  pela fração vendida, `vendidas ÷ (vendidas + saldo)`. Com o saldo zero a
  fração é 1 e o parcial vira o resultado do lote inteiro.
- Sem custo de aquisição (como o lote "saldo anterior" da planilha) não há
  resultado: "—", com o motivo. Nunca um lucro inventado.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.money import kg_to_arroba, safe_div
from apps.core.reversible import Status
from apps.sales.models import Sale


@dataclass(frozen=True)
class ResultadoDoLote:
    lote: object
    vendas: int = 0
    cabecas_vendidas: int = 0
    saldo_atual: int = 0
    encerrado: bool = False
    # Lote ainda com animais: custo rateado pela fração vendida.
    parcial: bool = False
    fracao_vendida: Decimal | None = None

    receita: Decimal | None = None
    custo_aquisicao: Decimal | None = None
    custos_diretos: Decimal | None = None
    custos_rateados: Decimal | None = None
    custo_total: Decimal | None = None  # do lote inteiro
    custo_considerado: Decimal | None = None  # a parte que cabe ao vendido
    criterios_de_rateio: list = field(default_factory=list)

    resultado: Decimal | None = None
    resultado_por_cabeca: Decimal | None = None
    arrobas_vendidas: Decimal | None = None
    valor_por_arroba: Decimal | None = None
    custo_por_arroba: Decimal | None = None
    margem_por_arroba: Decimal | None = None

    vendas_sem_carcaca: int = 0
    # Por que cada "—" é "—".
    motivos: list = field(default_factory=list)


def _montar_resultado(lot, vendas, saldo_atual, financeiro) -> ResultadoDoLote:
    """O resultado do lote a partir de vendas, saldo e `financeiro` já
    carregados. `financeiro` só é lido se há venda."""
    encerrado = lot.status == "ENCERRADO"

    if not vendas:
        return ResultadoDoLote(
            lote=lot,
            saldo_atual=saldo_atual,
            encerrado=encerrado,
            motivos=["Nenhuma venda confirmada neste lote: não há resultado."],
        )

    cabecas_vendidas = sum(v.head_count for v in vendas)
    receita = sum((v.total_value for v in vendas), Decimal("0"))
    sem_carcaca = [v for v in vendas if not v.carcass_weight_kg]
    motivos: list[str] = []

    # @ vendida: só vale se TODAS as vendas têm carcaça. Somar a carcaça de
    # algumas e a receita de todas daria um valor por @ inflado.
    arrobas = None
    if sem_carcaca:
        motivos.append(
            f"Valor, custo e margem por @ indisponíveis: {len(sem_carcaca)} "
            "venda(s) sem peso de carcaça."
        )
    else:
        arrobas = kg_to_arroba(sum((v.carcass_weight_kg for v in vendas), Decimal("0")))

    base = {
        "lote": lot,
        "vendas": len(vendas),
        "cabecas_vendidas": cabecas_vendidas,
        "saldo_atual": saldo_atual,
        "encerrado": encerrado,
        "receita": receita,
        "custo_aquisicao": financeiro["aquisicao"],
        "custos_diretos": financeiro["custos_diretos"],
        "custos_rateados": financeiro["custos_rateados"],
        "custo_total": financeiro["custo_total"],
        "criterios_de_rateio": financeiro["criterios_de_rateio"],
        "arrobas_vendidas": arrobas,
        "valor_por_arroba": safe_div(receita, arrobas),
        "vendas_sem_carcaca": len(sem_carcaca),
    }

    if financeiro["aquisicao"] is None:
        motivos.append(
            "Resultado indisponível: o lote não tem compra registrada, então não "
            "há custo de aquisição. Sem ele o resultado seria um lucro inventado."
        )
        return ResultadoDoLote(**base, motivos=motivos)
    if financeiro["aviso_rateio"]:
        motivos.append(f"Resultado indisponível: {financeiro['aviso_rateio']}")
        return ResultadoDoLote(**base, motivos=motivos)

    # `Decimal(...)`: int ÷ int em Python é `float`, e float é proibido (regra 2).
    fracao = safe_div(Decimal(cabecas_vendidas), cabecas_vendidas + saldo_atual)
    custo_considerado = financeiro["custo_total"] * fracao
    resultado = receita - custo_considerado
    parcial = saldo_atual > 0
    if parcial:
        motivos.append(
            f"Resultado parcial: o lote ainda tem {saldo_atual} cabeças. O custo "
            "é rateado pela fração já vendida e o resultado fecha quando o saldo zerar."
        )

    custo_por_arroba = safe_div(custo_considerado, arrobas)
    valor_por_arroba = base["valor_por_arroba"]
    return ResultadoDoLote(
        **base,
        parcial=parcial,
        fracao_vendida=fracao,
        custo_considerado=custo_considerado,
        resultado=resultado,
        resultado_por_cabeca=safe_div(resultado, cabecas_vendidas),
        custo_por_arroba=custo_por_arroba,
        margem_por_arroba=(
            valor_por_arroba - custo_por_arroba
            if valor_por_arroba is not None and custo_por_arroba is not None
            else None
        ),
        motivos=motivos,
    )


def resultados_dos_lotes(lots, *, financeiros=None, financeiro_de=None) -> dict:
    """`{lot_id: ResultadoDoLote}` de vários lotes, com um número fixo de
    consultas (vendas, saldos e o `financeiro` dos lotes que têm venda).

    `financeiros`: `{lot_id: dict}` já calculado (a aba de lotes tem o dos
    lotes todos); o que faltar é calculado aqui, só para lote com venda.
    `financeiro_de`: função `lotes -> {lot_id: dict}` que calcula esse resto
    (o `Escopo.financeiro_dos_lotes` guarda o que já calculou e não repete o
    rateio entre abas); sem ela, o cálculo é feito aqui."""
    from apps.herd import services as herd_services
    from apps.livestock.selectors import financeiro_dos_lotes

    lots = list(lots)
    vendas = defaultdict(list)
    for v in Sale.objects.filter(
        lot_id__in=[lt.pk for lt in lots], status=Status.CONFIRMADA
    ):
        vendas[v.lot_id].append(v)
    saldos = herd_services.saldo_por_lote(lots)

    financeiros = dict(financeiros or {})
    faltam = [lt for lt in lots if vendas[lt.pk] and lt.pk not in financeiros]
    if faltam:
        financeiros.update((financeiro_de or financeiro_dos_lotes)(faltam))
    return {
        lt.pk: _montar_resultado(
            lt, vendas[lt.pk], saldos.get(lt.pk, 0), financeiros.get(lt.pk)
        )
        for lt in lots
    }


def resultado_do_lote(lot, *, financeiro=None) -> ResultadoDoLote:
    """`financeiro` já calculado (a tela do lote o tem em mãos) evita repetir o
    rateio, que é a parte cara. Um lote é o caso de `resultados_dos_lotes`."""
    return resultados_dos_lotes(
        [lot], financeiros={lot.pk: financeiro} if financeiro else None
    )[lot.pk]
