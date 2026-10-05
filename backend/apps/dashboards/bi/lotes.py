"""Aba **Lotes** — desempenho zootécnico e econômico, lote a lote.

GMD e @ produzida vêm de `desempenho_do_lote`; resultado, de
`resultado_do_lote`; custo do lote, de `financeiro_do_lote` — os mesmos
serviços da tela do lote. Lote sem dado mostra "—" e o motivo, nunca zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.urls import reverse

from apps.core.money import safe_div
from apps.herd.weight_gain import DesempenhoDoLote, desempenho_dos_lotes
from apps.livestock.models import LotStatus
from apps.livestock.selectors import cabecas_que_entraram_por_lote
from apps.sales.result import ResultadoDoLote

from . import rebanho, specs, vendas
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")
LIMITE_DE_LOTES_NA_TABELA = 60
#: Lotes com curva de peso coloridas; os demais ficam cinza, ao fundo.
LOTES_DESTACADOS_NA_CURVA = 5

#: Faixas de GMD (kg/dia) do histograma — ordenadas, uma matiz.
FAIXAS_DE_GMD = (
    (None, Decimal("0.2"), "menos de 0,2"),
    (Decimal("0.2"), Decimal("0.4"), "0,2 a 0,4"),
    (Decimal("0.4"), Decimal("0.6"), "0,4 a 0,6"),
    (Decimal("0.6"), Decimal("0.8"), "0,6 a 0,8"),
    (Decimal("0.8"), Decimal("1.0"), "0,8 a 1,0"),
    (Decimal("1.0"), None, "1,0 ou mais"),
)


@dataclass(frozen=True)
class LinhaDeLote:
    lote: object
    cabecas: int
    entraram: int
    dias: int
    desempenho: DesempenhoDoLote
    resultado: ResultadoDoLote | None

    @property
    def gmd(self):
        return self.desempenho.gmd

    @property
    def peso_atual(self):
        return self.desempenho.ultimo.peso_medio_kg if self.desempenho.ultimo else None

    @property
    def peso_entrada(self):
        p = self.desempenho.primeiro
        return p.peso_medio_kg if p is not None and p.e_entrada else None

    @property
    def encerrado(self) -> bool:
        return self.lote.status == LotStatus.ENCERRADO

    @property
    def pesos_para_media(self) -> int:
        u = self.desempenho.ultimo
        return u.cabecas if u else 0


def linhas_de_lotes(e: Escopo) -> list[LinhaDeLote]:
    """Lotes com animais hoje + lotes com venda na safra. Lote de safra
    encerrada sem venda no período não entra: não é desta safra."""

    def calcular():
        com_saldo = {lt.lote.pk: lt for lt in rebanho.lotes_com_saldo(e)}
        resultados = {r.lote.pk: r for r in vendas.resultados_dos_lotes(e)}
        lotes = {lt.lote.pk: lt.lote for lt in com_saldo.values()}
        lotes.update({pk: r.lote for pk, r in resultados.items()})
        # Entradas e desempenho dos lotes todos de uma vez: o número de
        # consultas não cresce com a quantidade de lotes.
        entraram = cabecas_que_entraram_por_lote(lotes.values())
        desempenhos = desempenho_dos_lotes(lotes.values())
        linhas = []
        for pk, lote in lotes.items():
            fim = lote.exit_date or e.fim
            linhas.append(
                LinhaDeLote(
                    lote=lote,
                    cabecas=com_saldo[pk].cabecas if pk in com_saldo else 0,
                    entraram=entraram.get(pk, 0),
                    dias=max((min(fim, e.fim) - lote.entry_date).days, 0),
                    desempenho=desempenhos[pk],
                    resultado=resultados.get(pk),
                )
            )
        return sorted(linhas, key=lambda lt: (lt.lote.farm.name, lt.lote.code))

    return e.memo("linhas_de_lotes", calcular)


def custos_por_cabeca(e: Escopo) -> dict[int, Decimal | None]:
    """Custo total do lote ÷ cabeças que entraram, do serviço do lote. É a parte
    cara (rateio por lote): só a aba Lotes pede."""

    def calcular():
        if not e.ver_dinheiro:
            return {}
        linhas = linhas_de_lotes(e)
        financeiros = e.financeiro_dos_lotes([lt.lote for lt in linhas])
        return {
            lt.lote.pk: financeiros[lt.lote.pk]["custo_por_cabeca"] for lt in linhas
        }

    return e.memo("custos_por_cabeca", calcular)


def gmd_medio(linhas) -> Decimal | None:
    """Ponderado pelas cabeças da última pesagem: lote grande pesa mais."""
    com = [lt for lt in linhas if lt.gmd is not None and lt.pesos_para_media]
    return safe_div(
        sum((lt.gmd * lt.pesos_para_media for lt in com), ZERO),
        sum(lt.pesos_para_media for lt in com),
    )


# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------


def kpis(e: Escopo) -> list[Kpi]:
    linhas = linhas_de_lotes(e)
    abertos = [lt for lt in linhas if not lt.encerrado]
    encerrados = [lt for lt in linhas if lt.encerrado]
    com_gmd = [lt for lt in linhas if lt.gmd is not None]
    media = gmd_medio(linhas)
    melhor = max(com_gmd, key=lambda lt: lt.gmd, default=None)
    pior = min(com_gmd, key=lambda lt: lt.gmd, default=None)
    sem_pesagem = [lt for lt in linhas if not lt.desempenho.pontos]
    ganhos = [
        (lt.desempenho.ganho_por_cabeca_kg, lt.pesos_para_media) for lt in com_gmd
    ]
    ganho_medio = safe_div(
        sum((g * n for g, n in ganhos), ZERO), sum(n for _, n in ganhos)
    )
    arrobas = [
        lt.desempenho.arrobas_produzidas
        for lt in linhas
        if lt.desempenho.arrobas_produzidas
    ]
    duracao = [lt.dias for lt in encerrados]
    return [
        Kpi(
            "Lotes com animais",
            specs.formatar(len(abertos)),
            nota=f"{len(encerrados)} encerrado(s) com venda na safra",
            url=reverse("livestock:lote_lista"),
            destaque=True,
        ),
        Kpi(
            "GMD médio",
            specs.formatar(media, "kgdia"),
            nota=f"{len(com_gmd)} lote(s) com duas pesagens",
            ajuda="Ganho médio diário ponderado pelas cabeças pesadas. Lote com uma pesagem só não tem GMD.",
        ),
        Kpi(
            "Melhor GMD",
            specs.formatar(melhor.gmd, "kgdia") if melhor else specs.TRAVESSAO,
            nota=melhor.lote.code if melhor else "",
            estado="bom" if melhor else "",
            estado_texto="Maior ganho" if melhor else "",
        ),
        Kpi(
            "Menor GMD",
            specs.formatar(pior.gmd, "kgdia") if pior else specs.TRAVESSAO,
            nota=pior.lote.code if pior else "",
            estado="atencao" if pior and melhor is not pior else "",
            estado_texto="Menor ganho" if pior and melhor is not pior else "",
        ),
        Kpi(
            "Ganho por cabeça",
            specs.formatar(ganho_medio, "kg2"),
            nota="entre a primeira e a última pesagem",
        ),
        Kpi(
            "@ produzidas",
            (
                specs.formatar(sum(arrobas, ZERO), "arroba")
                if arrobas
                else specs.TRAVESSAO
            ),
            nota=f"{len(arrobas)} lote(s) abatido(s) com carcaça",
            ajuda="(Carcaça de saída − carcaça de entrada) ÷ 15, só de lote com abate e peso de carcaça.",
        ),
        Kpi(
            "Duração média dos lotes encerrados",
            specs.formatar(safe_div(Decimal(sum(duracao)), len(duracao)), "dias"),
            nota="da entrada à saída",
        ),
        Kpi(
            "Lotes sem pesagem",
            specs.formatar(len(sem_pesagem)),
            nota="sem GMD possível",
            estado="atencao" if sem_pesagem else "bom",
            estado_texto="Pesar" if sem_pesagem else "Todos pesados",
        ),
    ]


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def grafico_gmd(e: Escopo) -> specs.Grafico:
    linhas = [lt for lt in linhas_de_lotes(e) if lt.gmd is not None]
    ordenadas = sorted(linhas, key=lambda lt: -lt.gmd)
    media = gmd_medio(linhas_de_lotes(e))
    g = specs.ranking(
        "lotes-gmd",
        "GMD de cada lote",
        [(lt.lote.code, lt.gmd) for lt in ordenadas],
        formato="kgdia",
        nome_serie="GMD",
        mostrar_participacao=False,
        limite=20,
        aditivo=False,
        largura="metade",
        nota="Ganho médio diário entre a primeira e a última pesagem. A linha é a média ponderada.",
        url=reverse("livestock:lote_lista"),
    )
    if media is not None:
        g.opcoes["linhas_ref"] = [
            {
                "valor": specs.num(media),
                "rotulo": f"Média {specs.formatar(media, 'kgdia')}",
            }
        ]
    return g


def grafico_distribuicao_gmd(e: Escopo) -> specs.Grafico:
    contagem = [0] * len(FAIXAS_DE_GMD)
    for lt in linhas_de_lotes(e):
        if lt.gmd is None:
            continue
        for i, (de, ate, _) in enumerate(FAIXAS_DE_GMD):
            if (de is None or lt.gmd >= de) and (ate is None or lt.gmd < ate):
                contagem[i] += 1
                break
    return specs.cartesiano(
        "lotes-gmd-distribuicao",
        "Quantos lotes em cada faixa de GMD",
        [r for _, _, r in FAIXAS_DE_GMD],
        [specs.serie("Lotes", contagem, cor="marca", rotulo=True, ordinal=True)],
        formato="num0",
        titulo_x="GMD (kg/dia)",
        titulo_y="Lotes",
        largura="metade",
    )


def grafico_curvas_de_peso(e: Escopo) -> specs.Grafico:
    """Peso médio × dias desde a entrada. Mais de 8 linhas coloridas viram
    espaguete: os maiores lotes ganham cor e os demais ficam cinza, ao fundo."""
    candidatas = [lt for lt in linhas_de_lotes(e) if len(lt.desempenho.pontos) >= 2]
    candidatas.sort(key=lambda lt: -max(lt.entraram, 1))
    series = []
    for i, lt in enumerate(candidatas):
        inicio = lt.desempenho.pontos[0].date
        dados = [
            ((p.date - inicio).days, p.peso_medio_kg) for p in lt.desempenho.pontos
        ]
        destacado = i < LOTES_DESTACADOS_NA_CURVA
        series.append(
            specs.serie(
                lt.lote.code if destacado else f"{lt.lote.code} ",
                dados,
                tipo="line",
                cor=i if destacado else "neutro",
                fundo=not destacado,
            )
        )
    g = specs.cartesiano(
        "lotes-curvas-peso",
        "Curva de peso de cada lote",
        [],
        series,
        formato="kg",
        x_tipo="valor",
        titulo_x="Dias desde a primeira pesagem",
        titulo_y="Peso médio (kg)",
        nota=(
            f"Os {LOTES_DESTACADOS_NA_CURVA} maiores lotes em cor; os demais em cinza. "
            "A inclinação é o GMD."
        ),
        largura="cheia",
        altura=340,
    )
    # A tabela de uma curva é um par (dia, peso) por lote: o `x` vazio acima
    # não a descreve.
    linhas = [
        [s["nome"].strip(), f"{int(d[0])}", specs.formatar(d[1], "kg")]
        for s in series
        for d in s["dados"]
    ]
    g.com_tabela(
        Tabela(
            ["Lote", "Dias desde a 1ª pesagem", "Peso médio"], linhas, numericas=[1, 2]
        )
    )
    return g


def grafico_gmd_x_custo(e: Escopo) -> specs.Grafico | None:
    if not e.ver_dinheiro:
        return None
    custos = custos_por_cabeca(e)
    pontos = [
        {
            "x": custos[lt.lote.pk],
            "y": lt.gmd,
            "r": lt.entraram,
            "nome": lt.lote.code,
        }
        for lt in linhas_de_lotes(e)
        if lt.gmd is not None and custos.get(lt.lote.pk) is not None
    ]
    return specs.dispersao(
        "lotes-gmd-custo",
        "Custo por cabeça × GMD",
        [{"nome": "Lotes", "cor": "marca", "pontos": pontos}],
        formato_x="brl",
        formato_y="kgdia",
        titulo_x="Custo por cabeça (R$)",
        titulo_y="GMD (kg/dia)",
        colunas_tabela="Cabeças que entraram",
        nota="Custo total do lote (aquisição + custos + rateio) ÷ cabeças que entraram. Quem custa mais está ganhando mais peso?",
        largura="metade",
    )


def grafico_margem_por_arroba(e: Escopo) -> specs.Grafico | None:
    if not e.ver_dinheiro:
        return None
    com = [
        lt
        for lt in linhas_de_lotes(e)
        if lt.resultado is not None and lt.resultado.margem_por_arroba is not None
    ]
    ordenadas = sorted(com, key=lambda lt: lt.resultado.margem_por_arroba)
    return specs.cartesiano(
        "lotes-margem-arroba",
        "Margem por @ de cada lote",
        [lt.lote.code for lt in ordenadas],
        [
            specs.serie(
                "Margem por @",
                [lt.resultado.margem_por_arroba for lt in ordenadas],
                cor="positivo",
                rotulo=True,
                por_sinal=True,
            )
        ],
        formato="brl",
        horizontal=True,
        nota="Valor por @ vendida − custo por @. Só lote com carcaça nas vendas e compra registrada.",
        largura="metade",
        altura=max(240, 70 + 30 * len(ordenadas)),
    )


def tabela_de_lotes(e: Escopo) -> Tabela:
    linhas_ = linhas_de_lotes(e)[:LIMITE_DE_LOTES_NA_TABELA]
    media = gmd_medio(linhas_de_lotes(e))
    dinheiro = e.ver_dinheiro
    custos = custos_por_cabeca(e)
    colunas = [
        "Lote",
        "Fazenda",
        "Situação",
        "Cabeças",
        "Dias",
        "Peso entrada",
        "Peso atual",
        "GMD",
    ]
    if dinheiro:
        colunas += ["Custo/cabeça", "Resultado", "Margem/@"]
    linhas, links, marcas = [], [], {}
    for i, lt in enumerate(linhas_):
        linha = [
            lt.lote.code,
            lt.lote.farm.name,
            "Encerrado" if lt.encerrado else "Aberto",
            specs.formatar(lt.cabecas) if not lt.encerrado else specs.TRAVESSAO,
            specs.formatar(lt.dias),
            specs.formatar(lt.peso_entrada, "kg"),
            specs.formatar(lt.peso_atual, "kg"),
            specs.formatar(lt.gmd, "kgdia"),
        ]
        if dinheiro:
            r = lt.resultado
            linha += [
                specs.formatar(custos.get(lt.lote.pk), "brl"),
                specs.formatar(r.resultado if r else None, "brl"),
                specs.formatar(r.margem_por_arroba if r else None, "brl"),
            ]
            if r is not None and r.resultado is not None:
                marcas[(i, 9)] = (
                    ("bom", "lucro") if r.resultado >= 0 else ("ruim", "prejuízo")
                )
        if media is not None and lt.gmd is not None and lt.gmd < media:
            marcas[(i, 7)] = ("atencao", "abaixo da média")
        linhas.append(linha)
        links.append(reverse("livestock:lote_detalhe", args=[lt.lote.pk]))
    t = Tabela(
        colunas,
        linhas,
        numericas=[3, 4, 5, 6, 7] + ([8, 9, 10] if dinheiro else []),
        titulo="Painel de lotes",
        links=links,
        marcas=marcas,
        codigo=0,
        vazio="Nenhum lote com animais ou com venda na safra.",
    )
    t.barra(7, [lt.gmd for lt in linhas_])
    return t


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis(e), kpis_titulo="Desempenho dos lotes")
    linhas = linhas_de_lotes(e)
    if not linhas:
        painel.vazio = (
            "Nenhum lote com animais ou com venda na safra e no recorte escolhidos."
        )
    sem_gmd = [lt for lt in linhas if lt.gmd is None]
    if sem_gmd:
        painel.avisos.append(
            f"{len(sem_gmd)} lote(s) sem GMD (menos de duas pesagens em datas diferentes): "
            + ", ".join(lt.lote.code for lt in sem_gmd[:6])
            + ("…" if len(sem_gmd) > 6 else "")
            + ". O GMD nunca é estimado."
        )
    if len(linhas) > LIMITE_DE_LOTES_NA_TABELA:
        painel.avisos.append(
            f"A tabela mostra {LIMITE_DE_LOTES_NA_TABELA} dos {len(linhas)} lotes; "
            "veja os demais na lista de lotes."
        )
    ganho = [g for g in (grafico_gmd_x_custo(e), grafico_margem_por_arroba(e)) if g]
    painel.secoes = [
        Secao(
            "Ganho de peso",
            [grafico_gmd(e), grafico_distribuicao_gmd(e), grafico_curvas_de_peso(e)],
        ),
        Secao("Custo e margem", ganho) if ganho else None,
        Secao("Lote a lote", [], tabelas=[tabela_de_lotes(e)]),
    ]
    painel.secoes = [s for s in painel.secoes if s]
    return painel
