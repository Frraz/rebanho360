"""Indicadores do Relatório do consultor (cliente, 2026-10-03, pendência #39):
mortalidade por causa, curva ABC de custos, inventário valorizado, TIR da safra
e confinamento. Como todo relatório, **não calcula por conta**: usa os
serviços e seletores que a tela já usa, e dado ausente sai como "—".

Duas premissas **informadas pelo usuário** — o sistema não escolhe:

- o preço de mercado da @ (parâmetro `preco_arroba`) valoriza o estoque; sem
  ele o inventário mostra o custo acumulado e deixa o valor de mercado em "—";
- a arroba viva usada na valorização é a da planilha do consultor: 30 kg de
  peso vivo (`330 kg = 11 @`). É uma constante deste módulo, não da carcaça
  (15 kg), que é a base do resto do sistema.

A eficiência biológica depende do consumo de matéria seca, que o sistema não
registra (consumo detalhado ficou fora do escopo): ela não aparece aqui.
"""

import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from apps.core.irr import anualizar, taxa_interna_de_retorno
from apps.core.money import safe_div
from apps.core.reversible import Status
from apps.costs import selectors as custos
from apps.herd.models import DeathCause, HerdLedgerEntry, MovementType
from apps.herd.mortality import taxa_de_mortalidade
from apps.herd.selectors import listar_movimentos_para
from apps.herd.weight_gain import desempenho_dos_lotes, pontos_de_peso_dos_lotes
from apps.livestock.models import Lot, LotRegime, LotStatus
from apps.livestock.selectors import (
    cabecas_que_entraram_por_lote,
    financeiro_dos_lotes,
)
from apps.reports.services import (
    DINHEIRO,
    INTEIRO,
    NUMERO,
    PERCENTUAL,
    Coluna,
    Relatorio,
    _contexto,
    _filtro_de_periodo,
)
from apps.sales import selectors as vendas_selectors

ZERO = Decimal("0")
CEM = Decimal("100")
#: Arroba **viva** do inventário do consultor (330 kg = 11 @).
KG_POR_ARROBA_VIVA = Decimal("30")
#: Cortes da curva ABC: A até 80% do desembolso, B até 95%, C o resto.
LIMITE_A, LIMITE_B = Decimal("80"), Decimal("95")


# --------------------------------------------------------------------------
# Mortalidade por causa
# --------------------------------------------------------------------------


def mortalidade_por_causa(user, *, season, farm, start=None, end=None) -> Relatorio:
    """Mortes por causa informada. A taxa de mortalidade é a de sempre
    (`taxa_de_mortalidade`); **o sistema não diz o que é "acima do normal"**."""
    qs = listar_movimentos_para(user).filter(
        status=Status.CONFIRMADA, type=MovementType.MORTE
    )
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(origin_farm=farm)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)

    rotulos = dict(DeathCause.choices)
    por_causa = {
        d["death_cause"]: d["total"]
        for d in qs.values("death_cause").annotate(total=Sum("quantity"))
    }
    total = sum(por_causa.values())
    linhas = []
    for causa, mortes in sorted(por_causa.items(), key=lambda kv: -kv[1]):
        linhas.append(
            {
                "causa": (
                    rotulos.get(causa, "Não informada") if causa else "Não informada"
                ),
                "mortes": mortes,
                "participacao": safe_div(Decimal(mortes) * CEM, Decimal(total)),
            }
        )

    # A taxa por fazenda, no mesmo período.
    inicio = start or (season.start_date if season else None)
    fim = end or (min(datetime.date.today(), season.end_date) if season else None)
    taxas = []
    if inicio and fim and inicio <= fim:
        fazendas = (
            [farm]
            if farm is not None
            else sorted(
                {m.origin_farm for m in qs.select_related("origin_farm")}, key=str
            )
        )
        for f in fazendas:
            t = taxa_de_mortalidade(farm=f, start=inicio, end=fim)
            taxas.append({"fazenda": f.name, "mortes": t.mortes, "taxa": t.taxa})
    secao = Relatorio(
        titulo="Taxa de mortalidade por fazenda",
        descricao="Mortes ÷ saldo médio do período × 100.",
        colunas=[
            Coluna("fazenda", "Fazenda"),
            Coluna("mortes", "Mortes", INTEIRO),
            Coluna("taxa", "Mortalidade", PERCENTUAL),
        ],
        linhas=taxas,
    )
    return Relatorio(
        titulo="Mortalidade por causa",
        descricao="Quantas cabeças morreram, e de quê — quando a causa foi informada.",
        colunas=[
            Coluna("causa", "Causa"),
            Coluna("mortes", "Mortes", INTEIRO),
            Coluna("participacao", "% das mortes", PERCENTUAL),
        ],
        linhas=linhas,
        totais={"causa": "Total", "mortes": total},
        filtros=[*_contexto(season, farm), *_filtro_de_periodo(start, end)],
        notas=[
            'A causa é opcional no lançamento da morte; "Não informada" quer dizer '
            "que ninguém a registrou. O sistema não define o que é mortalidade "
            "acima do normal.",
        ],
        secoes=[secao],
    )


# --------------------------------------------------------------------------
# Curva ABC de custos (perfil de desembolso)
# --------------------------------------------------------------------------


def curva_abc_de_custos(user, *, season, farm, start=None, end=None) -> Relatorio:
    """Cada centro de custo, do maior para o menor, com o acumulado e o perfil:
    **A** até 80% do desembolso, **B** até 95%, **C** o resto."""
    qs = custos.listar_custos_para(user, season=season, farm=farm)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    dados = (
        qs.values("cost_center__name").annotate(total=Sum("amount")).order_by("-total")
    )
    centros = [(d["cost_center__name"], d["total"]) for d in dados]
    total = sum((t for _, t in centros), ZERO)
    faturamento = sum(
        (
            v.total_value
            for v in vendas_selectors.vendas_confirmadas_para(
                user, season=season, farm=farm, start=start, end=end
            )
        ),
        ZERO,
    )
    linhas, acumulado = [], ZERO
    for nome, valor in centros:
        participacao = safe_div(valor * CEM, total)
        # O perfil é o da faixa em que o centro **começa**: o maior centro é
        # sempre A, mesmo que sozinho passe de 80%.
        antes_pct = safe_div(acumulado * CEM, total) or ZERO
        acumulado += valor
        perfil = "A" if antes_pct < LIMITE_A else ("B" if antes_pct < LIMITE_B else "C")
        linhas.append(
            {
                "perfil": perfil,
                "centro": nome,
                "valor": valor,
                "participacao": participacao,
                "acumulado": safe_div(acumulado * CEM, total),
                "faturamento": safe_div(valor * CEM, faturamento),
            }
        )
    return Relatorio(
        titulo="Curva ABC de custos",
        descricao="Onde está o desembolso: os centros que concentram o custo, do maior ao menor.",
        colunas=[
            Coluna("perfil", "Perfil"),
            Coluna("centro", "Centro de custo"),
            Coluna("valor", "Desembolso", DINHEIRO),
            Coluna("participacao", "% do desembolso", PERCENTUAL),
            Coluna("acumulado", "% acumulado", PERCENTUAL),
            Coluna("faturamento", "% do faturamento", PERCENTUAL),
        ],
        linhas=linhas,
        totais={"centro": "Total", "valor": total} if linhas else None,
        filtros=[*_contexto(season, farm), *_filtro_de_periodo(start, end)],
        notas=[
            "Perfil A: o centro começa dentro dos primeiros 80% do desembolso; B: "
            'até 95%; C: o resto. "% do faturamento" usa as vendas do mesmo '
            'recorte; sem venda, fica em "—".',
        ],
    )


# --------------------------------------------------------------------------
# Inventário valorizado
# --------------------------------------------------------------------------


def _cabecas_em(lotes, ate: datetime.date) -> dict:
    """`{lot_id: cabeças}` na data, de vários lotes numa consulta."""
    return {
        lot_id: total or 0
        for lot_id, total in HerdLedgerEntry.objects.filter(
            lot_id__in=[lt.pk for lt in lotes], date__lte=ate
        )
        .values_list("lot_id")
        .annotate(total=Sum("quantity"))
        .order_by("lot_id")
    }


def _peso_medio_em(pontos, ate: datetime.date) -> Decimal | None:
    """O último peso médio conhecido até a data (pesagem, ou o peso da compra)."""
    pontos = [p for p in pontos if p.date <= ate]
    return pontos[-1].peso_medio_kg if pontos else None


def _lotes_do_escopo(user, *, farm=None, regime=None):
    qs = Lot.objects.for_user(user).exclude(status=LotStatus.EXCLUIDO)
    if farm is not None:
        qs = qs.filter(farm=farm)
    if regime is not None:
        qs = qs.filter(regime=regime)
    return qs.select_related("farm").order_by("farm__name", "code")


def valorizar_estoque(user, *, farm, ate: datetime.date, preco_arroba) -> list[dict]:
    """O estoque de cada lote na data: cabeças, peso médio, @ vivas, custo
    acumulado e — com o preço da @ informado — o valor de mercado."""
    linhas = []
    todos = list(_lotes_do_escopo(user, farm=farm))
    em_estoque = _cabecas_em(todos, ate)
    lotes = [lt for lt in todos if em_estoque.get(lt.pk, 0) > 0]
    pontos = pontos_de_peso_dos_lotes(lotes)
    custos_dos_lotes = financeiro_dos_lotes(
        lotes, entradas=cabecas_que_entraram_por_lote(lotes), ate=ate
    )
    for lote in lotes:
        cabecas = em_estoque[lote.pk]
        peso = _peso_medio_em(pontos[lote.pk], ate)
        arrobas = (
            safe_div(Decimal(cabecas) * peso, KG_POR_ARROBA_VIVA) if peso else None
        )
        custo = custos_dos_lotes[lote.pk]["custo_total"]
        mercado = (
            arrobas * Decimal(preco_arroba)
            if arrobas is not None and preco_arroba is not None
            else None
        )
        linhas.append(
            {
                "lote": lote.code,
                "fazenda": lote.farm.name,
                "cabecas": cabecas,
                "peso_medio": peso,
                "arrobas": arrobas,
                "custo": custo,
                "mercado": mercado,
            }
        )
    return linhas


def inventario_valorizado(user, *, season, farm, preco_arroba=None, **_) -> Relatorio:
    """O estoque de hoje, lote a lote, a custo e — com o preço da @ informado —
    a valor de mercado. Substitui as abas INVENTÁRIO e ESTOQUE do consultor."""
    hoje = datetime.date.today()
    linhas = valorizar_estoque(user, farm=farm, ate=hoje, preco_arroba=preco_arroba)
    custo_total = sum(
        (lin["custo"] for lin in linhas if lin["custo"] is not None), ZERO
    )
    mercado_total = (
        sum((lin["mercado"] for lin in linhas if lin["mercado"] is not None), ZERO)
        if preco_arroba is not None
        and any(lin["mercado"] is not None for lin in linhas)
        else None
    )
    notas = [
        "Peso médio: a última pesagem do lote (ou o peso da compra). Sem peso, o "
        'lote não tem valor de mercado — fica em "—", nunca zero.',
        "Arroba viva de 30 kg, como na planilha do consultor.",
    ]
    if preco_arroba is None:
        notas.insert(
            0,
            "Informe o preço da @ para ver o valor de mercado: o sistema não "
            "escolhe um preço.",
        )
    return Relatorio(
        titulo="Inventário valorizado",
        descricao="O rebanho de hoje, lote a lote: cabeças, peso, @ vivas, custo acumulado e valor de mercado.",
        colunas=[
            Coluna("fazenda", "Fazenda"),
            Coluna("lote", "Lote"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("peso_medio", "Peso médio (kg)", NUMERO),
            Coluna("arrobas", "@ vivas", NUMERO),
            Coluna("custo", "Custo acumulado", DINHEIRO),
            Coluna("mercado", "Valor de mercado", DINHEIRO),
        ],
        linhas=linhas,
        totais=(
            {
                "fazenda": "Total",
                "cabecas": sum(lin["cabecas"] for lin in linhas),
                "custo": custo_total,
                "mercado": mercado_total,
            }
            if linhas
            else None
        ),
        filtros=[
            *_contexto(season, farm),
            f"em {hoje:%d/%m/%Y}",
            (
                f"@ a R$ {preco_arroba}"
                if preco_arroba is not None
                else "sem preço de @ informado"
            ),
        ],
        notas=notas,
    )


# --------------------------------------------------------------------------
# TIR da safra
# --------------------------------------------------------------------------


def _indice_do_mes(inicio: datetime.date, data: datetime.date) -> int:
    return (data.year - inicio.year) * 12 + (data.month - inicio.month)


def tir_da_safra(user, *, season, farm, preco_arroba=None, **_) -> Relatorio:
    """Fluxo de caixa **mensal** da safra e a taxa interna de retorno.

    Saídas: os custos lançados (inclusive os que as compras geram). Entradas: as
    vendas. Com o preço da @ informado, o estoque do início entra como saída e
    o do fim como entrada (a operação "se vende" ao valor de mercado);
    sem preço, a TIR é a do caixa puro e só existe se já houve venda.
    """
    vazio = Relatorio(
        titulo="TIR da safra",
        descricao="Taxa interna de retorno do fluxo mensal da safra.",
        colunas=[Coluna("mes", "Mês")],
        linhas=[],
        filtros=[*_contexto(season, farm)],
        notas=["Escolha uma safra no contexto do topo."],
    )
    if season is None:
        return vazio
    inicio = season.start_date
    fim = min(datetime.date.today(), season.end_date)
    if fim < inicio:
        return vazio
    meses = _indice_do_mes(inicio, fim) + 1

    saidas = defaultdict(lambda: ZERO)
    for c in custos.listar_custos_para(user, season=season, farm=farm):
        saidas[_indice_do_mes(inicio, c.date)] += c.amount
    entradas = defaultdict(lambda: ZERO)
    for v in vendas_selectors.vendas_confirmadas_para(user, season=season, farm=farm):
        entradas[_indice_do_mes(inicio, v.date)] += v.total_value

    estoque_inicial = estoque_final = None
    if preco_arroba is not None:
        dia_antes = inicio - datetime.timedelta(days=1)
        estoque_inicial = sum(
            (
                lin["mercado"] or ZERO
                for lin in valorizar_estoque(
                    user, farm=farm, ate=dia_antes, preco_arroba=preco_arroba
                )
            ),
            ZERO,
        )
        estoque_final = sum(
            (
                lin["mercado"] or ZERO
                for lin in valorizar_estoque(
                    user, farm=farm, ate=fim, preco_arroba=preco_arroba
                )
            ),
            ZERO,
        )

    fluxos, linhas, acumulado = [], [], ZERO
    for m in range(meses):
        ano_mes = (inicio.year * 12 + inicio.month - 1) + m
        rotulo = f"{ano_mes % 12 + 1:02d}/{ano_mes // 12}"
        saida = saidas.get(m, ZERO)
        entrada = entradas.get(m, ZERO)
        est_ini = estoque_inicial if (m == 0 and estoque_inicial) else ZERO
        est_fim = estoque_final if (m == meses - 1 and estoque_final) else ZERO
        liquido = entrada + est_fim - saida - est_ini
        acumulado += liquido
        fluxos.append(liquido)
        linhas.append(
            {
                "mes": rotulo,
                "saidas": saida,
                "entradas": entrada,
                "estoque_inicial": est_ini or None,
                "estoque_final": est_fim or None,
                "liquido": liquido,
                "acumulado": acumulado,
            }
        )
    tir_mensal = taxa_interna_de_retorno(fluxos)
    resultado = Relatorio(
        titulo="Taxa interna de retorno",
        descricao="A taxa que zera o valor presente do fluxo mensal.",
        colunas=[
            Coluna("indicador", "Indicador"),
            Coluna("valor", "Valor", PERCENTUAL),
        ],
        linhas=[
            {
                "indicador": "TIR ao mês",
                "valor": tir_mensal * CEM if tir_mensal is not None else None,
            },
            {
                "indicador": "TIR ao ano (composta)",
                "valor": (
                    anualizar(tir_mensal) * CEM if tir_mensal is not None else None
                ),
            },
        ],
    )
    notas = [
        'Fluxo mensal da safra até hoje. "—" na TIR = o fluxo não troca de sinal '
        "(só saídas ou só entradas): sem venda, e sem estoque valorizado, não há "
        "retorno a medir.",
    ]
    if preco_arroba is None:
        notas.append(
            "Sem o preço da @, o estoque não entra: é a TIR do caixa puro. Informe "
            "o preço para incluir o estoque inicial e o final."
        )
    return Relatorio(
        titulo="TIR da safra",
        descricao="Fluxo de caixa mensal da safra e a taxa interna de retorno.",
        colunas=[
            Coluna("mes", "Mês"),
            Coluna("saidas", "Custos", DINHEIRO),
            Coluna("entradas", "Vendas", DINHEIRO),
            Coluna("estoque_inicial", "Estoque inicial", DINHEIRO),
            Coluna("estoque_final", "Estoque final", DINHEIRO),
            Coluna("liquido", "Fluxo do mês", DINHEIRO),
            Coluna("acumulado", "Acumulado", DINHEIRO),
        ],
        linhas=linhas,
        totais={
            "mes": "Total",
            "saidas": sum((lin["saidas"] for lin in linhas), ZERO),
            "entradas": sum((lin["entradas"] for lin in linhas), ZERO),
            "liquido": acumulado,
        },
        filtros=[
            *_contexto(season, farm),
            (
                f"@ a R$ {preco_arroba}"
                if preco_arroba is not None
                else "sem preço de @ informado"
            ),
        ],
        notas=notas,
        secoes=[resultado],
    )


# --------------------------------------------------------------------------
# Confinamento
# --------------------------------------------------------------------------


def confinamento(user, *, season, farm, **_) -> Relatorio:
    """Os lotes marcados como **confinamento**, com o desempenho que o sistema já
    mede: dias, GMD, @ produzida, custo e custo por @ (das vendas)."""
    linhas = []
    lotes = [
        lt
        for lt in _lotes_do_escopo(user, farm=farm, regime=LotRegime.CONFINAMENTO)
        if season is None or lt.season_id == season.pk
    ]
    desempenhos = desempenho_dos_lotes(lotes)
    entradas = cabecas_que_entraram_por_lote(lotes)
    financeiros = financeiro_dos_lotes(lotes, entradas=entradas)
    for lote in lotes:
        desempenho = desempenhos[lote.pk]
        entrada = next((p for p in desempenho.pontos if p.e_entrada), None)
        ultimo = desempenho.ultimo
        entraram = entradas.get(lote.pk, 0)
        fin = financeiros[lote.pk]
        arrobas = desempenho.arrobas_produzidas
        linhas.append(
            {
                "lote": lote.code,
                "fazenda": lote.farm.name,
                "cabecas": entraram,
                "peso_entrada": entrada.peso_medio_kg if entrada else None,
                "peso_atual": ultimo.peso_medio_kg if ultimo else None,
                "dias": desempenho.dias,
                "gmd": desempenho.gmd,
                "arrobas": arrobas,
                "custo": fin["custo_total"],
                "custo_arroba": (
                    safe_div(fin["custo_total"], arrobas)
                    if fin["custo_total"] is not None and arrobas
                    else None
                ),
            }
        )
    return Relatorio(
        titulo="Confinamento",
        descricao="Lotes em confinamento: permanência, ganho de peso, @ produzida e custo.",
        colunas=[
            Coluna("fazenda", "Fazenda"),
            Coluna("lote", "Lote"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("peso_entrada", "Peso entrada (kg)", NUMERO),
            Coluna("peso_atual", "Último peso (kg)", NUMERO),
            Coluna("dias", "Permanência (dias)", INTEIRO),
            Coluna("gmd", "GMD (kg/dia)", NUMERO),
            Coluna("arrobas", "@ produzidas", NUMERO),
            Coluna("custo", "Custo total", DINHEIRO),
            Coluna("custo_arroba", "Custo por @", DINHEIRO),
        ],
        linhas=linhas,
        filtros=[*_contexto(season, farm)],
        notas=[
            "O lote é marcado como confinamento no cadastro do lote. @ produzida e "
            "custo por @ aparecem quando há o rendimento de entrada informado na "
            'compra e peso de saída; sem eles ficam em "—".',
        ],
    )


# --------------------------------------------------------------------------
# Indicadores reprodutivos
# --------------------------------------------------------------------------


def indicadores_reprodutivos(user, *, season, farm, **_) -> Relatorio:
    """Um ciclo por linha, com os índices de `reproduction.indicators` — os
    mesmos da tela. O sistema não diz o que é um índice bom ou ruim."""
    from apps.reproduction import indicators
    from apps.reproduction.models import BreedingCycle

    ciclos = BreedingCycle.objects.for_user(user).exclude(status=Status.EXCLUIDA)
    if season is not None:
        ciclos = ciclos.filter(season=season)
    if farm is not None:
        ciclos = ciclos.filter(farm=farm)
    linhas = []
    for c in ciclos.select_related("farm", "season").order_by("farm__name"):
        ind = indicators.indicadores_do_ciclo(c)
        linhas.append(
            {
                "fazenda": c.farm.name,
                "safra": c.season.name,
                "expostas": ind.expostas,
                "prenhes": ind.prenhes,
                "vazias": ind.vazias,
                "fertilidade": ind.fertilidade_geral_pct,
                "em_reproducao": ind.em_reproducao_pct,
                "inseminadas": ind.inseminadas_pct,
                "fert_ia": ind.fertilidade_ia_pct,
                "fert_touro": ind.fertilidade_touro_pct,
                "nascidos": ind.nascidos,
                "desmamados": c.weaned_calves,
                "desmama": ind.desmama_pct,
            }
        )
    return Relatorio(
        titulo="Indicadores reprodutivos",
        descricao="Fertilidade, % de inseminadas, nascimentos e desmama de cada ciclo.",
        colunas=[
            Coluna("fazenda", "Fazenda"),
            Coluna("safra", "Safra"),
            Coluna("expostas", "Em monta", INTEIRO),
            Coluna("prenhes", "Prenhes", INTEIRO),
            Coluna("vazias", "Vazias", INTEIRO),
            Coluna("fertilidade", "Fertilidade", PERCENTUAL),
            Coluna("em_reproducao", "Fêmeas em reprodução", PERCENTUAL),
            Coluna("inseminadas", "Inseminadas", PERCENTUAL),
            Coluna("fert_ia", "Fertilidade IA/IATF", PERCENTUAL),
            Coluna("fert_touro", "Fertilidade touro", PERCENTUAL),
            Coluna("nascidos", "Nascidos", INTEIRO),
            Coluna("desmamados", "Desmamados", INTEIRO),
            Coluna("desmama", "Desmama", PERCENTUAL),
        ],
        linhas=linhas,
        filtros=[*_contexto(season, farm)],
        notas=[
            "Nascidos vêm do razão do rebanho (movimentações de nascimento); o "
            'restante é o que foi informado no ciclo. "—" = falta o dado.',
        ],
    )
