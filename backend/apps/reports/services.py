"""Monta os relatórios da Fase 2 — custos e compras.

Cada relatório é dado puro (`Relatorio`): colunas, linhas, totais. A mesma
estrutura alimenta a tela e a exportação CSV — se os dois mostrassem número
diferente, o usuário pararia de confiar nos dois (regra 6).

Os números vêm dos seletores de `costs` e `purchases`; nada é calculado aqui
nem no template.
"""

import csv
import datetime
import io
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import PermissionDenied

from apps.core.formatting import dinheiro_br, numero_br
from apps.core.money import safe_div
from apps.core.reversible import Status
from apps.costs import selectors as custos
from apps.finance import selectors as financeiro
from apps.finance.models import Direction
from apps.finance.permissions import pode_ver_dado_bancario, pode_ver_titulos
from apps.herd.models import Weighing
from apps.herd.weight_gain import desempenho_do_lote
from apps.livestock.models import Lot, LotStatus
from apps.procurement.permissions import pode_ver_o_ciclo
from apps.purchases import selectors as compras
from apps.sales import carcass
from apps.sales import selectors as vendas_selectors
from apps.sales.models import Sale
from apps.sales.result import resultado_do_lote

TEXTO, DINHEIRO, INTEIRO, PERCENTUAL, NUMERO = (
    "texto",
    "dinheiro",
    "inteiro",
    "percentual",
    "numero",
)


@dataclass
class Coluna:
    chave: str
    rotulo: str
    tipo: str = TEXTO


@dataclass
class Relatorio:
    titulo: str
    descricao: str
    colunas: list[Coluna]
    linhas: list[dict]
    totais: dict | None = None
    # Os filtros aplicados — safra, fazenda, período, lote. Vão impressos no
    # PDF e dentro dos arquivos exportados: papel na mesa sem filtro não diz a
    # que se refere (docs/relatorios/01#padrão-visual).
    filtros: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)
    secoes: list["Relatorio"] = field(default_factory=list)


#: Quem abre o arquivo no Excel executa o que começa com estes caracteres como
#: fórmula. Um parceiro, lote ou observação chamado `=HYPERLINK(...)` viraria
#: ataque (injeção de fórmula em CSV/XLSX). Texto digitado por gente é
#: neutralizado; número e dinheiro nunca passam por aqui.
INICIO_PERIGOSO = ("=", "+", "-", "@", "\t", "\r")


def neutralizar_formula(texto):
    if isinstance(texto, str) and texto.startswith(INICIO_PERIGOSO):
        return "'" + texto
    return texto


def formatar(valor, tipo: str) -> str:
    """Texto para a tela e para o CSV. `None` é "—", nunca zero."""
    if valor is None or valor == "":
        return "—"
    if tipo == DINHEIRO:
        return dinheiro_br(valor)
    if tipo == INTEIRO:
        return numero_br(Decimal(valor), 0)
    if tipo == PERCENTUAL:
        return numero_br(Decimal(valor), 2) + "%"
    if tipo == NUMERO:
        return numero_br(Decimal(valor), 2)
    return str(valor)


def tabela(relatorio: Relatorio) -> list[list[str]]:
    """Cabeçalho + linhas já formatadas (+ totais), para tela e CSV."""
    cabecalho = [c.rotulo for c in relatorio.colunas]
    corpo = [
        [formatar(lin.get(c.chave), c.tipo) for c in relatorio.colunas]
        for lin in relatorio.linhas
    ]
    if relatorio.totais is not None:
        corpo.append(
            [formatar(relatorio.totais.get(c.chave), c.tipo) for c in relatorio.colunas]
        )
    return [cabecalho, *corpo]


def para_tela(relatorio: Relatorio) -> dict:
    """A mesma tabela do CSV, com cada linha também como pares
    rótulo/valor — é o que vira cartão no celular."""
    linhas = tabela(relatorio)
    cabecalho, corpo = linhas[0], linhas[1:]
    numericas = [c.tipo != TEXTO for c in relatorio.colunas]
    return {
        "cabecalho": cabecalho,
        "linhas": corpo,
        "cartoes": [list(zip(cabecalho, linha)) for linha in corpo],
        # (texto, numérica?) por célula: número alinha à direita e não quebra.
        "celulas": [list(zip(linha, numericas)) for linha in corpo],
        "numericas": numericas,
        "indices_numericos": [i for i, n in enumerate(numericas) if n],
        "tem_totais": relatorio.totais is not None,
    }


def csv_do_relatorio(relatorio: Relatorio) -> str:
    """CSV para Excel brasileiro: `;` como separador, vírgula decimal,
    BOM UTF-8 (sem ele o Excel desfigura os acentos)."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow([relatorio.titulo])
    # Os filtros viajam dentro do arquivo: planilha solta, sem eles, não diz
    # a que se refere.
    if relatorio.filtros:
        escritor.writerow(["Filtros aplicados: " + " · ".join(relatorio.filtros)])
    for nota in relatorio.notas:
        escritor.writerow([nota])
    for rel in (relatorio, *relatorio.secoes):
        if rel is not relatorio:
            escritor.writerow([])
            escritor.writerow([rel.titulo])
        textos = [c.tipo == TEXTO for c in rel.colunas]
        for numero, linha in enumerate(tabela(rel)):
            # Cabeçalho (linha 0) é nosso; células de TEXTO vêm de gente.
            escritor.writerow(
                [
                    neutralizar_formula(v) if numero and eh_texto else v
                    for v, eh_texto in zip(linha, textos, strict=False)
                ]
            )
    return "﻿" + saida.getvalue()


FORMATOS_DO_EXCEL = {
    DINHEIRO: '"R$" #,##0.00',
    INTEIRO: "#,##0",
    PERCENTUAL: '0.00"%"',
    NUMERO: "#,##0.00",
}


def xlsx_do_relatorio(
    relatorio: Relatorio, *, emitido_por="", emitido_em=None
) -> bytes:
    """Planilha para quem analisa por fora. **Os números são números** (com
    formato de moeda, %, milhar), não texto — dá para somar e filtrar. Dado
    ausente vai como "—", não como célula vazia: vazio parece zero numa
    tabela dinâmica. Os filtros aplicados vão dentro do arquivo."""
    import openpyxl
    from openpyxl.styles import Alignment, Font

    wb = openpyxl.Workbook()
    nomes_usados: set[str] = set()

    def nome_da_aba(titulo: str) -> str:
        base = "".join(c for c in titulo if c not in "[]:*?/\\")[:31] or "Relatório"
        nome, i = base, 2
        while nome in nomes_usados:
            sufixo = f" ({i})"
            nome, i = base[: 31 - len(sufixo)] + sufixo, i + 1
        nomes_usados.add(nome)
        return nome

    def escrever(ws, rel: Relatorio, *, cabecalho_do_documento: bool):
        linha = 1
        ws.cell(linha, 1, rel.titulo).font = Font(bold=True, size=14)
        linha += 1
        if cabecalho_do_documento:
            if rel.filtros:
                ws.cell(linha, 1, "Filtros aplicados: " + " · ".join(rel.filtros))
                linha += 1
            for nota in rel.notas:
                ws.cell(linha, 1, nota)
                linha += 1
            quando = (emitido_em or datetime.datetime.now()).strftime("%d/%m/%Y %H:%M")
            ws.cell(
                linha,
                1,
                f"Emitido em {quando}" + (f" por {emitido_por}" if emitido_por else ""),
            )
            linha += 1
        linha += 1
        for c, coluna in enumerate(rel.colunas, start=1):
            celula = ws.cell(linha, c, coluna.rotulo)
            celula.font = Font(bold=True)
            celula.alignment = Alignment(
                horizontal="left" if c == 1 else "right", wrap_text=True
            )
        ws.freeze_panes = ws.cell(linha + 1, 1)
        linha += 1

        def gravar(valores: dict, negrito=False):
            nonlocal linha
            for c, coluna in enumerate(rel.colunas, start=1):
                valor = valores.get(coluna.chave)
                if valor is None or valor == "":
                    celula = ws.cell(linha, c, "—")
                    celula.alignment = Alignment(horizontal="right")
                elif coluna.tipo in FORMATOS_DO_EXCEL and isinstance(
                    valor, int | Decimal
                ):
                    celula = ws.cell(linha, c, valor)
                    celula.number_format = FORMATOS_DO_EXCEL[coluna.tipo]
                else:
                    celula = ws.cell(linha, c, formatar(valor, coluna.tipo))
                    if coluna.tipo == TEXTO:
                        # openpyxl trata "=..." como fórmula: força texto.
                        celula.value = neutralizar_formula(celula.value)
                        celula.data_type = "s"
                if negrito:
                    celula.font = Font(bold=True)
            linha += 1

        for valores in rel.linhas:
            gravar(valores)
        if rel.totais is not None:
            gravar(rel.totais, negrito=True)
        for c, coluna in enumerate(rel.colunas, start=1):
            maior = max(
                [len(coluna.rotulo)]
                + [len(formatar(v.get(coluna.chave), coluna.tipo)) for v in rel.linhas]
            )
            ws.column_dimensions[ws.cell(1, c).column_letter].width = min(
                max(maior + 2, 10), 42
            )

    escrever(wb.active, relatorio, cabecalho_do_documento=True)
    wb.active.title = nome_da_aba(relatorio.titulo)
    for secao in relatorio.secoes:
        escrever(
            wb.create_sheet(nome_da_aba(secao.titulo)),
            secao,
            cabecalho_do_documento=False,
        )
    wb.properties.title = relatorio.titulo
    wb.properties.creator = "Rebanho360"

    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def _contexto(season, farm) -> list[str]:
    partes = [f"Safra {season.name}" if season else "Todas as safras"]
    partes.append(f"Fazenda {farm.name}" if farm else "Todas as fazendas")
    return partes


def _filtro_de_periodo(start, end) -> list[str]:
    if start and end:
        return [f"Período: {start:%d/%m/%Y} a {end:%d/%m/%Y}"]
    if start:
        return [f"Período: a partir de {start:%d/%m/%Y}"]
    if end:
        return [f"Período: até {end:%d/%m/%Y}"]
    return []


# --------------------------------------------------------------------------
# Custos
# --------------------------------------------------------------------------

COLUNAS_DE_CUSTO = [
    Coluna("nome", "Nome"),
    Coluna("lancamentos", "Lançamentos", INTEIRO),
    Coluna("total", "Total", DINHEIRO),
    Coluna("participacao", "% do total", PERCENTUAL),
]


def _de_custo(titulo, descricao, rotulo_nome, dados, notas) -> Relatorio:
    linhas, total = dados
    colunas = [Coluna("nome", rotulo_nome), *COLUNAS_DE_CUSTO[1:]]
    return Relatorio(
        titulo=titulo,
        descricao=descricao,
        colunas=colunas,
        linhas=linhas,
        totais={
            "nome": "Total",
            "lancamentos": sum(lin["lancamentos"] for lin in linhas),
            "total": total,
            "participacao": Decimal("100") if linhas else None,
        },
        filtros=notas,
    )


def custos_por_centro(user, *, season, farm) -> Relatorio:
    """Substitui o `DASH FINANCEIRO`: onde o dinheiro foi."""
    return _de_custo(
        "Custos por centro de custo",
        "Onde o dinheiro foi. Substitui o DASH FINANCEIRO.",
        "Centro de custo",
        custos.custos_por_centro(user, season=season, farm=farm),
        _contexto(season, farm),
    )


def custos_por_fazenda(user, *, season, farm=None) -> Relatorio:
    return _de_custo(
        "Custos por fazenda",
        "Qual fazenda consome mais.",
        "Fazenda",
        custos.custos_por_fazenda(user, season=season),
        _contexto(season, None),
    )


def custeio_x_investimento(user, *, season, farm) -> Relatorio:
    return _de_custo(
        "Custeio × investimento",
        "Quanto é gasto na safra e quanto é imobilizado.",
        "Classe",
        custos.custos_por_classe(user, season=season, farm=farm),
        _contexto(season, farm),
    )


# --------------------------------------------------------------------------
# Compras
# --------------------------------------------------------------------------


def compras_do_periodo(user, *, season, farm, start=None, end=None) -> Relatorio:
    """Substitui `COMPRA DE GADO` + `DASH COMPRAS`."""
    linhas_brutas, totais = compras.compras_do_periodo(
        user, season=season, farm=farm, start=start, end=end
    )
    linhas = [
        {
            "codigo": lin["compra"].code,
            "data": f"{lin['compra'].date:%d/%m/%Y}",
            "fazenda": lin["compra"].destination_farm.name,
            "categoria": lin["compra"].category.name,
            "cabecas": lin["compra"].head_count,
            "valor_animais": lin["compra"].animal_value,
            "custo_aquisicao": lin["custo"].custo_aquisicao,
            "media_cabeca": lin["custo"].media_por_cabeca,
            "custo_arroba": lin["custo"].custo_por_arroba,
        }
        for lin in linhas_brutas
    ]
    colunas = [
        Coluna("codigo", "Compra"),
        Coluna("data", "Data"),
        Coluna("fazenda", "Fazenda"),
        Coluna("categoria", "Categoria"),
        Coluna("cabecas", "Cabeças", INTEIRO),
        Coluna("valor_animais", "Valor dos animais", DINHEIRO),
        Coluna("custo_aquisicao", "Custo de aquisição", DINHEIRO),
        Coluna("media_cabeca", "Média/cabeça", DINHEIRO),
        Coluna("custo_arroba", "Custo/@", DINHEIRO),
    ]
    por_mes = [
        {
            "mes": f"{m['mes']:%m/%Y}",
            "compras": m["compras"],
            "cabecas": m["cabecas"],
            "valor": m["valor"],
        }
        for m in compras.compras_por_mes(user, season=season, farm=farm)
    ]
    secao = Relatorio(
        titulo="Compras por mês",
        descricao="",
        colunas=[
            Coluna("mes", "Mês"),
            Coluna("compras", "Compras", INTEIRO),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("valor", "Valor dos animais", DINHEIRO),
        ],
        linhas=por_mes,
    )
    filtros = _contexto(season, farm) + _filtro_de_periodo(start, end)
    custo = totais["custo"]
    return Relatorio(
        titulo="Compras do período",
        descricao="O que foi comprado, de quem, por quanto. Só compras confirmadas.",
        colunas=colunas,
        linhas=linhas,
        totais={
            "codigo": "Total",
            "cabecas": totais["cabecas"],
            "valor_animais": totais["valor_animais"],
            "custo_aquisicao": custo.custo_aquisicao,
            "media_cabeca": custo.media_por_cabeca,
            "custo_arroba": custo.custo_por_arroba,
        },
        filtros=filtros,
        notas=["Custo/@ aparece como — quando a compra não tem peso."],
        secoes=[secao],
    )


def aquisicao_por_lote(user, *, season, farm) -> Relatorio:
    """Quanto custou formar cada lote: o que a planilha não tem."""
    linhas = [
        {
            "lote": lin["lote"].code,
            "fazenda": lin["fazenda"].name,
            "compras": lin["compras"],
            "cabecas": lin["cabecas"],
            "custo_aquisicao": lin["custo"].custo_aquisicao,
            "custo_cabeca": lin["custo"].custo_por_cabeca,
            "custo_arroba": lin["custo"].custo_por_arroba,
        }
        for lin in compras.custo_de_aquisicao_por_lote(user, season=season, farm=farm)
    ]
    return Relatorio(
        titulo="Custo de aquisição por lote",
        descricao="Quanto custou formar o lote: animais + frete + comissão + impostos.",
        colunas=[
            Coluna("lote", "Lote"),
            Coluna("fazenda", "Fazenda"),
            Coluna("compras", "Compras", INTEIRO),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("custo_aquisicao", "Custo de aquisição", DINHEIRO),
            Coluna("custo_cabeca", "Custo/cabeça", DINHEIRO),
            Coluna("custo_arroba", "Custo/@", DINHEIRO),
        ],
        linhas=linhas,
        filtros=_contexto(season, farm),
        notas=["Custo/@ aparece como — quando falta o peso da compra."],
    )


# --------------------------------------------------------------------------
# Vendas e desempenho (Fase 3)
# --------------------------------------------------------------------------


def vendas_e_abates(user, *, season, farm, start=None, end=None) -> Relatorio:
    """Quanto saiu, para quem, a que preço. Substitui `VENDAS` e `DASH VENDAS`.
    Rendimento e valor/@ vêm do `CarcassService` — o relatório não calcula."""
    vendas = list(
        vendas_selectors.vendas_confirmadas_para(
            user, season=season, farm=farm, start=start, end=end
        ).select_related("farm", "lot", "category", "buyer")
    )
    linhas = []
    for v in vendas:
        ind = carcass.indicadores_da_venda(v)
        linhas.append(
            {
                "codigo": v.code,
                "data": f"{v.date:%d/%m/%Y}",
                "tipo": v.get_type_display(),
                "comprador": v.buyer.name,
                "fazenda": v.farm.name,
                "lote": v.lot.code,
                "categoria": v.category.name,
                "cabecas": v.head_count,
                "peso_vivo": v.total_weight_kg,
                "carcaca": v.carcass_weight_kg,
                "rendimento": ind.rendimento,
                "valor": v.total_value,
                "valor_cabeca": ind.valor_por_cabeca,
                "valor_arroba": ind.valor_por_arroba,
            }
        )
    agregado = carcass.agregar(vendas)
    ind = agregado.indicadores
    totais = {
        "codigo": "Total",
        "cabecas": agregado.cabecas,
        "peso_vivo": agregado.peso_vivo_kg,
        "carcaca": sum(
            (v.carcass_weight_kg for v in vendas if v.carcass_weight_kg), Decimal("0")
        )
        or None,
        "rendimento": ind.rendimento,
        "valor": agregado.valor_total,
        "valor_cabeca": ind.valor_por_cabeca,
        "valor_arroba": ind.valor_por_arroba,
    }

    def agrupar(chave, rotulo):
        grupos = defaultdict(list)
        for v in vendas:
            grupos[chave(v)].append(v)
        saida = []
        for nome, itens in sorted(grupos.items()):
            a = carcass.agregar(itens)
            saida.append(
                {
                    "nome": nome,
                    "vendas": a.vendas,
                    "cabecas": a.cabecas,
                    "valor": a.valor_total,
                    "rendimento": a.indicadores.rendimento,
                    "valor_arroba": a.indicadores.valor_por_arroba,
                }
            )
        return Relatorio(
            titulo=rotulo[0],
            descricao="",
            colunas=[
                Coluna("nome", rotulo[1]),
                Coluna("vendas", "Vendas", INTEIRO),
                Coluna("cabecas", "Cabeças", INTEIRO),
                Coluna("valor", "Valor", DINHEIRO),
                Coluna("rendimento", "Rendimento", PERCENTUAL),
                Coluna("valor_arroba", "Valor/@", DINHEIRO),
            ],
            linhas=saida,
        )

    notas = [
        "Rendimento e valor/@ do total consideram só as vendas que têm peso de carcaça."
    ]
    if agregado.sem_carcaca:
        notas.append(
            f"{agregado.sem_carcaca} venda(s) sem peso de carcaça: aparecem com — "
            "no rendimento e no valor/@."
        )
    return Relatorio(
        titulo="Vendas e abates",
        descricao="Quanto saiu, para quem e a que preço. Substitui VENDAS e DASH VENDAS.",
        colunas=[
            Coluna("codigo", "Venda"),
            Coluna("data", "Data"),
            Coluna("tipo", "Tipo"),
            Coluna("comprador", "Comprador"),
            Coluna("fazenda", "Fazenda"),
            Coluna("lote", "Lote"),
            Coluna("categoria", "Categoria"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("peso_vivo", "Peso vivo (kg)", INTEIRO),
            Coluna("carcaca", "Carcaça (kg)", INTEIRO),
            Coluna("rendimento", "Rendimento", PERCENTUAL),
            Coluna("valor", "Valor total", DINHEIRO),
            Coluna("valor_cabeca", "Valor/cabeça", DINHEIRO),
            Coluna("valor_arroba", "Valor/@", DINHEIRO),
        ],
        linhas=linhas,
        totais=totais,
        filtros=_contexto(season, farm) + _filtro_de_periodo(start, end),
        notas=notas,
        secoes=[
            agrupar(lambda v: f"{v.date:%Y-%m}", ("Vendas por mês", "Mês")),
            agrupar(lambda v: v.buyer.name, ("Vendas por comprador", "Comprador")),
        ],
    )


def _lotes_do_escopo(user, *, season, farm):
    qs = Lot.objects.for_user(user).exclude(status=LotStatus.EXCLUIDO)
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(farm=farm)
    return qs.select_related("farm").order_by("farm__name", "code")


def desempenho_dos_lotes(
    user, *, season, farm, rendimento_entrada=None, hoje=None
) -> Relatorio:
    """GMD, @ produzida, dias e rendimento por lote. Lote sem dado aparece
    com "—" e o motivo — nunca com um GMD inventado."""
    hoje = hoje or datetime.date.today()
    linhas = []
    for lote in _lotes_do_escopo(user, season=season, farm=farm):
        d = desempenho_do_lote(lote, rendimento_entrada=rendimento_entrada)
        vendas = list(Sale.objects.filter(lot=lote, status=Status.CONFIRMADA))
        agregado = carcass.agregar(vendas) if vendas else None
        fim = lote.exit_date or hoje
        linhas.append(
            {
                "lote": lote.code,
                "fazenda": lote.farm.name,
                "situacao": lote.get_status_display(),
                "dias": (fim - lote.entry_date).days,
                "peso_inicial": d.primeiro.peso_medio_kg if d.primeiro else None,
                "peso_final": d.ultimo.peso_medio_kg if d.ultimo else None,
                "gmd": d.gmd,
                "desde_entrada": (
                    None
                    if d.gmd is None
                    else ("Sim" if d.gmd_desde_a_entrada else "Não")
                ),
                "arrobas": d.arrobas_produzidas,
                "rendimento": agregado.indicadores.rendimento if agregado else None,
                "observacao": d.motivos[0] if d.motivos else "",
            }
        )
    notas = [
        "GMD = (peso médio final − inicial) ÷ dias, de pesagens do mesmo lote. "
        "Sem duas pesagens em datas diferentes é —; o peso de entrada nunca é estimado.",
    ]
    filtros = _contexto(season, farm)
    if rendimento_entrada is not None:
        filtros.append(
            f"Rendimento de entrada estimado: {numero_br(Decimal(rendimento_entrada), 2)}% "
            "(a @ produzida é ESTIMATIVA)"
        )
    else:
        notas.append(
            "@ produzida é — sem um rendimento de entrada estimado: informe um no filtro."
        )
    return Relatorio(
        titulo="Desempenho do lote",
        descricao="GMD, @ produzida, dias e rendimento de cada lote.",
        colunas=[
            Coluna("lote", "Lote"),
            Coluna("fazenda", "Fazenda"),
            Coluna("situacao", "Situação"),
            Coluna("dias", "Dias", INTEIRO),
            Coluna("peso_inicial", "Peso inicial (kg)", NUMERO),
            Coluna("peso_final", "Peso final (kg)", NUMERO),
            Coluna("gmd", "GMD (kg/dia)", NUMERO),
            Coluna("desde_entrada", "GMD desde a entrada?"),
            Coluna("arrobas", "@ produzida", NUMERO),
            Coluna("rendimento", "Rendimento", PERCENTUAL),
            Coluna("observacao", "Por que há —"),
        ],
        linhas=linhas,
        filtros=filtros,
        notas=notas,
    )


def resultado_dos_lotes(user, *, season, farm) -> Relatorio:
    """Receita − custos = resultado, e margem por @: *o boi pagou o que
    custou criar?* Bloco final no formato do legado
    `06_Historico_de_Abate_por_Pecuarista` (`R$ @`, `Custo @`)."""
    lotes = (
        _lotes_do_escopo(user, season=season, farm=farm)
        .filter(sales__status=Status.CONFIRMADA)
        .distinct()
    )
    linhas, fora_do_total = [], []
    soma = defaultdict(lambda: Decimal("0"))
    for lote in lotes:
        r = resultado_do_lote(lote)
        situacao = "Parcial" if r.parcial else "Encerrado" if r.encerrado else "Aberto"
        linhas.append(
            {
                "lote": lote.code,
                "fazenda": lote.farm.name,
                "situacao": situacao,
                "cabecas": r.cabecas_vendidas,
                "arrobas": r.arrobas_vendidas,
                "receita": r.receita,
                "custo": r.custo_considerado,
                "resultado": r.resultado,
                "valor_arroba": r.valor_por_arroba,
                "custo_arroba": r.custo_por_arroba,
                "margem_arroba": r.margem_por_arroba,
                "observacao": r.motivos[0] if r.motivos else "",
            }
        )
        if r.resultado is None:
            fora_do_total.append(f"{lote.code} (receita {dinheiro_br(r.receita)})")
            continue
        soma["cabecas"] += r.cabecas_vendidas
        soma["receita"] += r.receita
        soma["custo"] += r.custo_considerado
        soma["resultado"] += r.resultado
        if r.arrobas_vendidas:
            soma["arrobas"] += r.arrobas_vendidas
        else:
            soma["sem_arroba"] += 1

    # Valor/@, custo/@ e margem/@ do total só valem se TODOS os lotes do total
    # têm @ vendida — senão misturam bases.
    fecha_em_arroba = linhas and not soma["sem_arroba"] and soma["arrobas"]
    valor_arroba = (
        safe_div(soma["receita"], soma["arrobas"]) if fecha_em_arroba else None
    )
    custo_arroba = safe_div(soma["custo"], soma["arrobas"]) if fecha_em_arroba else None
    totais = {
        "lote": "Total",
        "cabecas": soma["cabecas"],
        "arrobas": soma["arrobas"] if fecha_em_arroba else None,
        "receita": soma["receita"],
        "custo": soma["custo"],
        "resultado": soma["resultado"],
        "valor_arroba": valor_arroba,
        "custo_arroba": custo_arroba,
        "margem_arroba": (
            valor_arroba - custo_arroba
            if valor_arroba is not None and custo_arroba is not None
            else None
        ),
    }
    notas = [
        "Custo/@ = custo do lote ÷ @ de carcaça vendida (pendência #14). Lote ainda "
        "com animais mostra resultado parcial, com o custo rateado pela fração vendida."
    ]
    if fora_do_total:
        notas.append(
            "Fora do total, por não terem custo de aquisição (o resultado seria inventado): "
            + "; ".join(fora_do_total)
            + "."
        )
    return Relatorio(
        titulo="Resultado do lote",
        descricao="Receita − aquisição − custos diretos − custos rateados, e a margem por @.",
        colunas=[
            Coluna("lote", "Lote"),
            Coluna("fazenda", "Fazenda"),
            Coluna("situacao", "Situação"),
            Coluna("cabecas", "Cab. vendidas", INTEIRO),
            Coluna("arrobas", "@ vendidas", NUMERO),
            Coluna("receita", "Receita", DINHEIRO),
            Coluna("custo", "Custo", DINHEIRO),
            Coluna("resultado", "Resultado", DINHEIRO),
            Coluna("valor_arroba", "R$/@ recebido", DINHEIRO),
            Coluna("custo_arroba", "Custo/@", DINHEIRO),
            Coluna("margem_arroba", "Margem/@", DINHEIRO),
            Coluna("observacao", "Por que há —"),
        ],
        linhas=linhas,
        totais=totais if linhas else None,
        filtros=_contexto(season, farm),
        notas=notas,
    )


def pesagens_do_periodo(
    user, *, season, farm, start=None, end=None, lote=None
) -> Relatorio:
    """Histórico de pesagens por lote, com a evolução do peso médio."""
    qs = Weighing.objects.for_user(user).filter(status=Status.CONFIRMADA)
    if farm is not None:
        qs = qs.filter(farm=farm)
    if season is not None:
        qs = qs.filter(lot__season=season)
    if lote is not None:
        qs = qs.filter(lot=lote)
    if start is not None:
        qs = qs.filter(date__gte=start)
    if end is not None:
        qs = qs.filter(date__lte=end)
    pesagens = list(
        qs.select_related("lot", "farm").order_by("lot__code", "date", "id")
    )

    # A evolução (ganho e GMD do trecho) vem do `WeightGainService`.
    trechos = {}
    for lot in {p.lot for p in pesagens}:
        for t in desempenho_do_lote(lot).trechos:
            trechos[(lot.pk, t.ate.date)] = t

    linhas = []
    for p in pesagens:
        t = trechos.get((p.lot_id, p.date))
        linhas.append(
            {
                "lote": p.lot.code,
                "fazenda": p.farm.name,
                "data": f"{p.date:%d/%m/%Y}",
                "motivo": p.get_reason_display(),
                "cabecas": p.head_count,
                "peso_total": p.total_weight_kg,
                "peso_medio": p.average_weight_kg,
                "ganho": t.ganho_por_cabeca_kg if t else None,
                "gmd": t.gmd if t else None,
            }
        )
    filtros = _contexto(season, farm) + _filtro_de_periodo(start, end)
    if lote is not None:
        filtros.append(f"Lote {lote.code}")
    return Relatorio(
        titulo="Pesagens",
        descricao="Histórico de pesagens por lote, com a evolução do peso médio.",
        colunas=[
            Coluna("lote", "Lote"),
            Coluna("fazenda", "Fazenda"),
            Coluna("data", "Data"),
            Coluna("motivo", "Motivo"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("peso_total", "Peso total (kg)", INTEIRO),
            Coluna("peso_medio", "Peso médio (kg)", NUMERO),
            Coluna("ganho", "Ganho/cab. (kg)", NUMERO),
            Coluna("gmd", "GMD do trecho", NUMERO),
        ],
        linhas=linhas,
        filtros=filtros,
        notas=[
            "Ganho e GMD só existem a partir da segunda pesagem do lote — a primeira mostra —."
        ],
    )


# --------------------------------------------------------------------------
# Financeiro (Fase 4) — substituem a `DASH CAIXA`, que nunca foi usada
# --------------------------------------------------------------------------


def _escopo_financeiro(farm) -> list[str]:
    return [f"Fazenda {farm.name}" if farm else "Todas as fazendas"]


def _contas(user, *, farm, direction, start, end) -> Relatorio:
    a_receber = direction == Direction.RECEBER
    titulos = list(
        financeiro.listar_titulos_para(
            user,
            farm=farm,
            direction=direction,
            situacao="abertos",
            de=start,
            ate=end,
        )
    )
    hoje = datetime.date.today()
    linhas = [
        {
            "vencimento": f"{t.due_date:%d/%m/%Y}",
            "titulo": t.code,
            "parceiro": t.payee.name if t.payee_id else "A definir",
            "origem": t.get_component_display()
            + (f" · {t.origem}" if t.origem is not None else ""),
            "valor": t.amount,
            "pago": t.paid_total,
            "saldo": t.balance,
            "situacao": "Vencido" if t.vencido(hoje) else t.situacao_rotulo,
        }
        for t in titulos
    ]
    rotulo = "Cliente" if a_receber else "Favorecido"
    return Relatorio(
        titulo="Contas a receber" if a_receber else "Contas a pagar",
        descricao=(
            "O que os compradores ainda devem, por vencimento."
            if a_receber
            else "O que vence e quanto, por vencimento."
        ),
        colunas=[
            Coluna("vencimento", "Vencimento"),
            Coluna("titulo", "Título"),
            Coluna("parceiro", rotulo),
            Coluna("origem", "Origem"),
            Coluna("valor", "Valor", DINHEIRO),
            Coluna("pago", "Já baixado", DINHEIRO),
            Coluna("saldo", "Saldo", DINHEIRO),
            Coluna("situacao", "Situação"),
        ],
        linhas=linhas,
        totais={
            "vencimento": "Total em aberto",
            "valor": sum((lin["valor"] for lin in linhas), start=Decimal("0")),
            "pago": sum((lin["pago"] for lin in linhas), start=Decimal("0")),
            "saldo": sum((lin["saldo"] for lin in linhas), start=Decimal("0")),
        },
        filtros=[
            "Títulos em aberto, de todas as safras",
            *_escopo_financeiro(farm),
            *_filtro_de_periodo(start, end),
        ],
        notas=[
            "O período filtra o vencimento. Título cancelado não entra.",
        ],
    )


def contas_a_pagar(user, *, season, farm, start=None, end=None) -> Relatorio:
    return _contas(user, farm=farm, direction=Direction.PAGAR, start=start, end=end)


def _atencao_do_pagamento(titulo) -> str:
    """O que impede de programar ou pagar. Título sem favorecido existe, mas
    não é programado (finance/models.py); sem conta, o pagamento não tem para
    onde ir."""
    if titulo.payee_id is None:
        return "Sem favorecido"
    if titulo.bank_account_id is None:
        return "Sem conta bancária"
    return ""


def programacao_de_pagamentos(user, *, season, farm, start=None, end=None) -> Relatorio:
    """Tudo o que há a pagar, na ordem em que o dinheiro precisa sair: o que já
    tem data de pagamento primeiro, depois pelo vencimento. Reúne o que o
    documento funcional pede (seção 10): compra, favorecido, documento,
    vencimento, valor, banco, agência, conta e situação.

    Banco, agência e conta só saem para quem pode ver dado bancário — na tela,
    no CSV/XLSX e no PDF, que passam todos por aqui."""
    com_conta = pode_ver_dado_bancario(user)
    titulos = list(
        financeiro.listar_titulos_para(
            user,
            farm=farm,
            direction=Direction.PAGAR,
            situacao="abertos",
            de=start,
            ate=end,
        )
    )
    # Programados antes, sem data por último; dentro de cada grupo, o vencimento.
    titulos.sort(
        key=lambda t: (
            t.scheduled_date is None,
            t.scheduled_date or t.due_date,
            t.due_date,
            t.pk,
        )
    )
    hoje = datetime.date.today()
    linhas = []
    for t in titulos:
        conta = t.bank_account if t.bank_account_id else None
        linhas.append(
            {
                "compra": t.origem.code if t.origem is not None else "—",
                "favorecido": t.payee.name if t.payee_id else "A definir",
                "titulo": t.code,
                "documento": t.document,
                "origem": t.get_component_display(),
                "vencimento": f"{t.due_date:%d/%m/%Y}",
                "programado": (
                    f"{t.scheduled_date:%d/%m/%Y}" if t.scheduled_date else None
                ),
                "valor": t.amount,
                "saldo": t.balance,
                "banco": (conta.bank_name or conta.bank_code) if conta else None,
                "agencia": conta.branch if conta else None,
                "conta": conta.account if conta else None,
                "situacao": "Vencido" if t.vencido(hoje) else t.situacao_rotulo,
                "atencao": _atencao_do_pagamento(t),
            }
        )

    colunas = [
        Coluna("compra", "Compra"),
        Coluna("favorecido", "Favorecido"),
        Coluna("titulo", "Título"),
        Coluna("documento", "Documento"),
        Coluna("origem", "Origem"),
        Coluna("vencimento", "Vencimento"),
        Coluna("programado", "Pagar em"),
        Coluna("valor", "Valor", DINHEIRO),
        Coluna("saldo", "Saldo", DINHEIRO),
    ]
    if com_conta:
        colunas += [
            Coluna("banco", "Banco"),
            Coluna("agencia", "Agência"),
            Coluna("conta", "Conta"),
        ]
    colunas += [Coluna("situacao", "Situação"), Coluna("atencao", "Atenção")]

    notas = [
        "O período filtra o vencimento. Título cancelado não entra.",
        "Para programar, aprovar ou dar baixa, abra o título em Contas a pagar.",
    ]
    if not com_conta:
        notas.append("Banco, agência e conta aparecem só para quem vê dado bancário.")
    sem_destino = sum(1 for lin in linhas if lin["atencao"])
    if sem_destino:
        notas.append(
            f"{sem_destino} título(s) sem favorecido ou sem conta bancária: "
            "complete o cadastro antes de programar."
        )
    return Relatorio(
        titulo="Programação de pagamentos",
        descricao="O que há a pagar: favorecido, vencimento, valor e para onde vai o dinheiro.",
        colunas=colunas,
        linhas=linhas,
        totais={
            "compra": "Total a pagar",
            "valor": sum((lin["valor"] for lin in linhas), start=Decimal("0")),
            "saldo": sum((lin["saldo"] for lin in linhas), start=Decimal("0")),
        },
        filtros=[
            "Títulos a pagar em aberto, de todas as safras",
            *_escopo_financeiro(farm),
            *_filtro_de_periodo(start, end),
        ],
        notas=notas,
    )


def contas_a_receber(user, *, season, farm, start=None, end=None) -> Relatorio:
    return _contas(user, farm=farm, direction=Direction.RECEBER, start=start, end=end)


def pagamentos_realizados(user, *, season, farm, start=None, end=None) -> Relatorio:
    """As baixas: dinheiro que saiu e que entrou de verdade."""
    inicio = start or (season.start_date if season else None)
    fim = end or (season.end_date if season else None)
    baixas = list(financeiro.pagamentos_para(user, farm=farm, de=inicio, ate=fim))
    linhas = [
        {
            "data": f"{p.date:%d/%m/%Y}",
            "baixa": p.code,
            "titulo": p.invoice.code,
            "parceiro": p.invoice.payee.name if p.invoice.payee_id else "—",
            "tipo": "Recebimento" if p.a_receber else "Pagamento",
            "forma": p.get_method_display(),
            "documento": p.document,
            "valor": p.amount,
        }
        for p in baixas
    ]
    pagos = sum((p.amount for p in baixas if not p.a_receber), start=Decimal("0"))
    recebidos = sum((p.amount for p in baixas if p.a_receber), start=Decimal("0"))
    return Relatorio(
        titulo="Pagamentos realizados",
        descricao="O dinheiro que saiu e o que entrou, baixa a baixa.",
        colunas=[
            Coluna("data", "Data"),
            Coluna("baixa", "Baixa"),
            Coluna("titulo", "Título"),
            Coluna("parceiro", "Favorecido / cliente"),
            Coluna("tipo", "Tipo"),
            Coluna("forma", "Forma"),
            Coluna("documento", "Documento"),
            Coluna("valor", "Valor", DINHEIRO),
        ],
        linhas=linhas,
        totais={"data": "Total pago", "valor": pagos},
        filtros=[
            *_escopo_financeiro(farm),
            *(_filtro_de_periodo(inicio, fim) or ["Período: sem limite"]),
        ],
        notas=[
            f"Recebido no período: {dinheiro_br(recebidos)} (fora do total acima, que é só o que saiu).",
            "Baixa desfeita não entra.",
        ],
    )


def fluxo_de_caixa_projetado(user, *, season, farm) -> Relatorio:
    """Entradas previstas de venda contra saídas previstas de título, mês a
    mês da safra, com o realizado separado do previsto."""
    if season is None:
        return Relatorio(
            titulo="Fluxo de caixa projetado",
            descricao="Escolha uma safra no topo da tela.",
            colunas=[Coluna("rotulo", "Mês")],
            linhas=[],
            filtros=_escopo_financeiro(farm),
        )
    fluxo = financeiro.fluxo_de_caixa(user, season=season, farm=farm)
    chaves = (
        "rotulo",
        "entradas_realizadas",
        "entradas_previstas",
        "saidas_realizadas",
        "saidas_previstas",
        "saldo_do_mes",
        "saldo_acumulado",
    )
    linhas = [{c: getattr(lin, c) for c in chaves} for lin in fluxo.linhas]
    totais = {c: getattr(fluxo.total, c) for c in chaves[1:]} | {"rotulo": "Total"}
    notas = [
        "Previsto = o que ainda falta nos títulos em aberto, no mês do vencimento. "
        "Realizado = as baixas, no mês do pagamento.",
        "Não há saldo bancário no sistema: o saldo acumulado parte de zero.",
    ]
    for valor, rotulo in (
        (fluxo.vencido_nao_pago, "a pagar"),
        (fluxo.vencido_a_receber, "a receber"),
    ):
        if valor:
            notas.append(
                f"{dinheiro_br(valor)} {rotulo} já venceram e não foram baixados — "
                "continuam no mês em que venceram."
            )
    return Relatorio(
        titulo="Fluxo de caixa projetado",
        descricao="Entradas previstas de venda contra saídas previstas de título, mês a mês.",
        colunas=[
            Coluna("rotulo", "Mês"),
            Coluna("entradas_realizadas", "Entradas realizadas", DINHEIRO),
            Coluna("entradas_previstas", "Entradas previstas", DINHEIRO),
            Coluna("saidas_realizadas", "Saídas realizadas", DINHEIRO),
            Coluna("saidas_previstas", "Saídas previstas", DINHEIRO),
            Coluna("saldo_do_mes", "Saldo do mês", DINHEIRO),
            Coluna("saldo_acumulado", "Saldo acumulado", DINHEIRO),
        ],
        linhas=linhas,
        totais=totais,
        filtros=[f"Safra {season.name}", *_escopo_financeiro(farm)],
        notas=notas,
    )


COLUNAS_DO_MAPA = [
    Coluna("rotulo", "Nome"),
    Coluna("titulos", "Títulos", INTEIRO),
    Coluna("total", "Total", DINHEIRO),
    Coluna("pago", "Pago", DINHEIRO),
    Coluna("a_pagar", "A pagar", DINHEIRO),
    Coluna("vencido", "Vencido", DINHEIRO),
]


def _secao_do_mapa(titulo, rotulo, linhas) -> Relatorio:
    chaves = ("rotulo", "titulos", "total", "pago", "a_pagar", "vencido")
    corpo = [{c: getattr(lin, c) for c in chaves} for lin in linhas]
    return Relatorio(
        titulo=titulo,
        descricao="",
        colunas=[Coluna("rotulo", rotulo), *COLUNAS_DO_MAPA[1:]],
        linhas=corpo,
        totais={"rotulo": "Total"}
        | {c: sum((lin[c] for lin in corpo), start=0) for c in chaves[1:]},
    )


def mapa_financeiro(user, *, season, farm) -> Relatorio:
    """Consolidado por favorecido, por tipo e por safra: pago, a pagar e
    vencido. O que hoje exige cruzar três abas."""
    a_pagar = financeiro.mapa_financeiro(user, farm=farm, direction=Direction.PAGAR)
    a_receber = financeiro.mapa_financeiro(user, farm=farm, direction=Direction.RECEBER)
    secoes = [
        _secao_do_mapa("A pagar · por favorecido", "Favorecido", a_pagar["favorecido"]),
        _secao_do_mapa("A pagar · por tipo", "Tipo", a_pagar["tipo"]),
        _secao_do_mapa("A pagar · por safra", "Safra", a_pagar["safra"]),
        _secao_do_mapa("A receber · por cliente", "Cliente", a_receber["favorecido"]),
    ]
    principal, resto = secoes[0], secoes[1:]
    principal.descricao = (
        "Pago, a pagar e vencido, por favorecido, por tipo e por safra."
    )
    return Relatorio(
        titulo="Mapa financeiro",
        descricao=principal.descricao,
        colunas=principal.colunas,
        linhas=principal.linhas,
        totais=principal.totais,
        filtros=["Todas as safras", *_escopo_financeiro(farm)],
        notas=[
            "A primeira tabela é o total a pagar por favorecido; as seguintes "
            "reagrupam os mesmos títulos. Título cancelado não entra.",
            "Em 'A receber', a coluna 'A pagar' é o que ainda falta receber.",
        ],
        secoes=resto,
    )


RELATORIOS = {
    "custos-por-centro": custos_por_centro,
    "custos-por-fazenda": custos_por_fazenda,
    "custeio-x-investimento": custeio_x_investimento,
    "compras-do-periodo": compras_do_periodo,
    "aquisicao-por-lote": aquisicao_por_lote,
    "vendas-e-abates": vendas_e_abates,
    "desempenho-do-lote": desempenho_dos_lotes,
    "resultado-do-lote": resultado_dos_lotes,
    "pesagens": pesagens_do_periodo,
    "contas-a-pagar": contas_a_pagar,
    "contas-a-receber": contas_a_receber,
    "programacao-de-pagamentos": programacao_de_pagamentos,
    "pagamentos-realizados": pagamentos_realizados,
    "fluxo-de-caixa": fluxo_de_caixa_projetado,
    "mapa-financeiro": mapa_financeiro,
}


def _do_ciclo(funcao: str):
    """Os relatórios do ciclo de compra moram em `ciclo.py`, que importa daqui
    `Relatorio` e `Coluna`: a importação é feita na hora de montar, para não
    ser circular."""

    def montar(user, **kwargs):
        from apps.reports import ciclo

        return getattr(ciclo, funcao)(user, **kwargs)

    return montar


RELATORIOS.update(
    {
        "programacao-de-embarque": _do_ciclo("programacao_de_embarque"),
        "programacao-de-abate": _do_ciclo("programacao_de_abate"),
        "conferencia-do-acerto": _do_ciclo("conferencia_do_acerto"),
        "comissao-por-comprador": _do_ciclo("comissao_por_comprador"),
        "fretes-e-quebra": _do_ciclo("fretes_e_quebra"),
        "historico-por-pecuarista": _do_ciclo("historico_por_pecuarista"),
        "programado-x-realizado": _do_ciclo("programado_x_realizado"),
    }
)

#: Preço, comissão e frete são dado comercial: quem não vê o ciclo (o `CAMPO`)
#: não abre estes relatórios — na tela, no CSV/XLSX nem no PDF.
RELATORIOS_DO_CICLO = frozenset(
    {
        "programacao-de-embarque",
        "programacao-de-abate",
        "conferencia-do-acerto",
        "comissao-por-comprador",
        "fretes-e-quebra",
        "historico-por-pecuarista",
        "programado-x-realizado",
    }
)

#: Dado financeiro: só quem pode ver títulos (e, mesmo assim, só das fazendas
#: do escopo dele). Vale para a tela, para o CSV/XLSX e para o PDF — todos
#: passam por `montar_relatorio`.
RELATORIOS_FINANCEIROS = frozenset(
    {
        "contas-a-pagar",
        "contas-a-receber",
        "programacao-de-pagamentos",
        "pagamentos-realizados",
        "fluxo-de-caixa",
        "mapa-financeiro",
    }
)


def montar_relatorio(user, slug, *, season, farm, extras=None) -> Relatorio:
    """O relatório pelo slug, dentro do escopo do usuário. `KeyError` se não
    existir — quem chama decide virar 404, tela de erro ou documento com erro."""
    if slug in RELATORIOS_FINANCEIROS and not pode_ver_titulos(user):
        raise PermissionDenied
    if slug in RELATORIOS_DO_CICLO and not pode_ver_o_ciclo(user):
        raise PermissionDenied
    return RELATORIOS[slug](user, season=season, farm=farm, **(extras or {}))


def catalogo_para(user):
    """O índice só lista o que o papel pode abrir."""
    pode_financeiro = pode_ver_titulos(user)
    pode_ciclo = pode_ver_o_ciclo(user)
    return [
        item
        for item in CATALOGO
        if (pode_financeiro or item[0] not in RELATORIOS_FINANCEIROS)
        and (pode_ciclo or item[0] not in RELATORIOS_DO_CICLO)
    ]


#: Parâmetros que cada relatório aceita, além de safra e fazenda (que vêm do
#: contexto fixo no topo). O view só repassa o que o relatório declara.
PARAMETROS = {
    "compras-do-periodo": ("de", "ate"),
    "vendas-e-abates": ("de", "ate"),
    "pesagens": ("de", "ate", "lote"),
    "desempenho-do-lote": ("rendimento_entrada",),
    "contas-a-pagar": ("de", "ate"),
    "contas-a-receber": ("de", "ate"),
    "programacao-de-pagamentos": ("de", "ate"),
    "pagamentos-realizados": ("de", "ate"),
    "programacao-de-embarque": ("de", "ate"),
    "programacao-de-abate": ("de", "ate"),
    "conferencia-do-acerto": ("acerto",),
    "comissao-por-comprador": ("de", "ate"),
    "fretes-e-quebra": ("de", "ate"),
    "historico-por-pecuarista": ("de", "ate"),
    "programado-x-realizado": ("de", "ate"),
}

CATALOGO = [
    (
        "custos-por-centro",
        "Custos por centro de custo",
        "Onde o dinheiro foi. Substitui o DASH FINANCEIRO.",
    ),
    ("custos-por-fazenda", "Custos por fazenda", "Qual fazenda consome mais."),
    (
        "custeio-x-investimento",
        "Custeio × investimento",
        "Quanto é gasto, quanto é imobilizado.",
    ),
    (
        "compras-do-periodo",
        "Compras do período",
        "O que foi comprado, de quem, por quanto. Substitui COMPRA DE GADO e DASH COMPRAS.",
    ),
    (
        "aquisicao-por-lote",
        "Custo de aquisição por lote",
        "Quanto custou formar cada lote.",
    ),
    (
        "vendas-e-abates",
        "Vendas e abates",
        "Quanto saiu, para quem e a que preço. Substitui VENDAS e DASH VENDAS.",
    ),
    (
        "desempenho-do-lote",
        "Desempenho do lote",
        "GMD, @ produzida, dias e rendimento de cada lote.",
    ),
    (
        "resultado-do-lote",
        "Resultado do lote",
        "Receita − custos = resultado, e a margem por @: o boi pagou o que custou criar?",
    ),
    (
        "pesagens",
        "Pesagens",
        "Histórico de pesagens por lote, com a evolução do peso médio.",
    ),
    (
        "contas-a-pagar",
        "Contas a pagar",
        "O que vence e quanto, por vencimento.",
    ),
    (
        "contas-a-receber",
        "Contas a receber",
        "O que os compradores ainda devem, por vencimento.",
    ),
    (
        "programacao-de-pagamentos",
        "Programação de pagamentos",
        "O que há a pagar, na ordem em que o dinheiro sai: favorecido, vencimento, valor, banco, agência e conta.",
    ),
    (
        "pagamentos-realizados",
        "Pagamentos realizados",
        "O dinheiro que saiu e o que entrou, baixa a baixa.",
    ),
    (
        "fluxo-de-caixa",
        "Fluxo de caixa projetado",
        "Entradas previstas de venda contra saídas previstas de título, mês a mês. Substitui a DASH CAIXA.",
    ),
    (
        "mapa-financeiro",
        "Mapa financeiro",
        "Pago, a pagar e vencido por favorecido, por tipo e por safra.",
    ),
    (
        "programacao-de-embarque",
        "Programação de embarque",
        "Os caminhões programados: quando saem, quem leva e quanto custa o frete previsto.",
    ),
    (
        "programacao-de-abate",
        "Programação de abate",
        "Por compromisso: produtor, datas, caminhões, comissão e o preço de cada faixa.",
    ),
    (
        "conferencia-do-acerto",
        "Conferência do acerto",
        "Resumo financeiro e tributário, títulos e romaneio valorizado de um acerto. Abra pelo acerto.",
    ),
    (
        "comissao-por-comprador",
        "Comissão por comprador",
        "O que cada compromisso rende de comissão, pela regra gravada nele.",
    ),
    (
        "fretes-e-quebra",
        "Fretes e quebra de viagem",
        "Frete previsto × realizado e a quebra de peso, viagem a viagem.",
    ),
    (
        "historico-por-pecuarista",
        "Histórico por pecuarista",
        "Cada acerto aprovado: cabeças, @, valor, comissão, frete, R$/@ e custo/@.",
    ),
    (
        "programado-x-realizado",
        "Programado × realizado",
        "Onde a operação divergiu do compromisso: cabeças, peso, preço, valor e datas.",
    ),
]
