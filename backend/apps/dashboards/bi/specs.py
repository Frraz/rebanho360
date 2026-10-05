"""O contrato entre o servidor e o navegador.

O servidor decide **o que** mostrar (dados já calculados pelos serviços do
sistema, rótulos em português, tabela equivalente já formatada) e o navegador
só **desenha** (`static/js/dashboard.js`, sobre o ECharts). O template não
calcula e o JavaScript não recalcula indicador nenhum: se um número aparece num
gráfico, ele veio daqui.

`Decimal` vira `float` **uma única vez, em `num()`**, na fronteira de
serialização — o desenho de um gráfico não é conta, e o JSON não tem
`Decimal`. Tudo antes disso é `Decimal` (regra 2).

Contrato de `opcoes` por tipo de gráfico (lido por dashboard.js):

- `cartesiano`  x, series[{nome,tipo(bar|line|area),dados,cor,pilha,rotulo}],
                formato, horizontal, zoom, linhas_ref[{valor,rotulo}],
                faixa{de,ate,rotulo}, x_tipo(categoria|valor), titulo_x, titulo_y
- `rosca`       itens[{nome,valor,cor}], formato, centro{valor,rotulo}
- `treemap`     nos[{nome,valor,filhos}], formato
- `calor`       x[], y[], celulas[[xi,yi,valor]], formato
- `cascata`     passos[{nome,valor,tipo(total|delta)}], formato
- `dispersao`   series[{nome,cor,pontos[{x,y,r,nome}]}], formato_x, formato_y,
                titulo_x, titulo_y, linhas_ref, faixa
- `sankey`      nos[{nome,cor}], ligacoes[{de,para,valor}], formato
- `calendario`  inicio, fim, dias[[data,valor]], formato
- `funil`       etapas[{nome,valor,rotulo}], formato

Cor de série: inteiro = posição na paleta categórica (ordem fixa, nunca
ciclada), ou um token (`marca`, `positivo`, `negativo`, `neutro`, `alerta`).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from apps.core.formatting import dinheiro_br, numero_br
from apps.core.money import safe_div

CEM = Decimal("100")
TRAVESSAO = "—"

# Papéis semânticos de cor (posição na paleta categórica de dashboard.js).
# A cor segue a **entidade**, não a posição na lista: "Compras" é a mesma cor em
# todo gráfico em que aparece, e filtrar não repinta o que sobrou.
COR_COMPRAS = 0
COR_CUSTOS = 1
COR_VENDAS = 2
COR_ALERTA = 3
COR_RESULTADO = "marca"
COR_ENTRADA = 2
COR_SAIDA = 1


def num(valor) -> float | None:
    """Única fronteira `Decimal → float` do dashboard (ver docstring do módulo)."""
    if valor is None:
        return None
    return float(Decimal(valor).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def pct(parte, todo) -> Decimal | None:
    """`parte ÷ todo` em %, ou `None` sem base (regra 3)."""
    razao = safe_div(Decimal(parte or 0), Decimal(todo or 0)) if todo else None
    return razao * CEM if razao is not None else None


# --------------------------------------------------------------------------
# Formatação (a tabela equivalente e os KPIs já saem formatados)
# --------------------------------------------------------------------------


def formatar(valor, formato: str = "num0") -> str:
    if valor is None:
        return TRAVESSAO
    # `str`: um float já arredondado em `num()` não pode reabrir a cauda binária.
    valor = Decimal(str(valor)) if isinstance(valor, float) else Decimal(valor)
    if formato == "brl":
        return dinheiro_br(valor)
    if formato == "pct":
        return f"{numero_br(valor, 1)}%"
    if formato == "pct2":
        return f"{numero_br(valor, 2)}%"
    if formato == "kg":
        return f"{numero_br(valor, 0)} kg"
    if formato == "kg2":
        return f"{numero_br(valor, 2)} kg"
    if formato == "kgdia":
        return f"{numero_br(valor, 3)} kg/dia"
    if formato == "arroba":
        return f"{numero_br(valor, 2)} @"
    if formato == "dias":
        return f"{numero_br(valor, 0)} dias"
    if formato == "cb":
        return f"{numero_br(valor, 0)} cb"
    if formato == "ha":
        return f"{numero_br(valor, 2)} cb/ha"
    if formato == "num1":
        return numero_br(valor, 1)
    if formato == "num2":
        return numero_br(valor, 2)
    return numero_br(valor, 0)


def brl_curto(valor) -> str:
    """ "R$ 1,2 mi", "R$ 840 mil", "−R$ 583,7 mil" — para KPI, onde o número cheio
    não cabe. O sinal vem antes do R$ (leitura natural de saldo)."""
    if valor is None:
        return TRAVESSAO
    valor = Decimal(valor)
    sinal = "−" if valor < 0 else ""
    absoluto = abs(valor)
    if absoluto >= Decimal("1000000"):
        corpo = f"R$ {numero_br(absoluto / Decimal('1000000'), 2)} mi"
    elif absoluto >= Decimal("10000"):
        corpo = f"R$ {numero_br(absoluto / Decimal('1000'), 1)} mil"
    else:
        corpo = dinheiro_br(absoluto)
    return sinal + corpo


# --------------------------------------------------------------------------
# Tabela equivalente (todo gráfico tem uma: o tooltip enriquece, nunca é a
# única via — WCAG e o relevo das cores abaixo de 3:1)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Celula:
    texto: str
    numerica: bool = False
    barra: float | None = None
    estado: str = ""
    estado_texto: str = ""
    codigo: bool = False

    @property
    def icone(self) -> str:
        return {
            "bom": "circle-check",
            "atencao": "triangle-alert",
            "ruim": "circle-x",
        }.get(self.estado, "info")


@dataclass(frozen=True)
class LinhaPronta:
    url: str
    celulas: list


@dataclass
class Tabela:
    colunas: list[str]
    linhas: list[list[str]]
    # Colunas numéricas: alinhadas à direita.
    numericas: list[int] = field(default_factory=list)
    legenda: str = ""
    # Só nas tabelas de análise (não nas gêmeas de gráfico):
    titulo: str = ""
    # URL de cada linha (a linha toda leva ao registro).
    links: list[str] = field(default_factory=list)
    # `{coluna: [0..100 | None por linha]}` — barra de dados dentro da célula.
    barras: dict = field(default_factory=dict)
    # `{(linha, coluna): (estado, texto)}` — formatação condicional. O estado
    # (`bom`/`atencao`/`ruim`) vem **sempre com texto**: cor nunca sozinha.
    marcas: dict = field(default_factory=dict)
    vazio: str = "Sem dados para mostrar."
    # Coluna de código de registro (fonte mono).
    codigo: int | None = None
    # Quantas linhas mostrar. `None` = todas. A tabela gêmea de um gráfico tem
    # teto (`LIMITE_DA_TABELA_GEMEA`): o gráfico segue com todos os pontos, mas
    # 600 linhas escondidas por gráfico faziam a aba passar de 1 MB — no celular
    # com sinal ruim isso é a aba que não abre.
    limite: int | None = None

    @property
    def omitidas(self) -> int:
        """Linhas que existem e não foram mostradas por causa do `limite`."""
        if self.limite is None:
            return 0
        return max(len(self.linhas) - self.limite, 0)

    @property
    def linhas_prontas(self) -> list[LinhaPronta]:
        """As linhas já com barra, marca e link resolvidos por célula: o template
        só percorre, não indexa dicionário por tupla nem calcula."""
        prontas = []
        mostradas = self.linhas if self.limite is None else self.linhas[: self.limite]
        for i, linha in enumerate(mostradas):
            celulas = []
            for j, texto in enumerate(linha):
                barras = self.barras.get(j)
                estado, estado_texto = self.marcas.get((i, j), ("", ""))
                celulas.append(
                    Celula(
                        texto,
                        numerica=j in self.numericas,
                        barra=barras[i] if barras else None,
                        estado=estado,
                        estado_texto=estado_texto,
                        codigo=j == self.codigo,
                    )
                )
            prontas.append(
                LinhaPronta(self.links[i] if i < len(self.links) else "", celulas)
            )
        return prontas

    def barra(self, coluna: int, valores) -> None:
        """Preenche `barras[coluna]` com a escala 0–100 de `valores`
        (`Decimal`/`None`), pelo maior valor absoluto."""
        absolutos = [abs(Decimal(v)) for v in valores if v is not None]
        maximo = max(absolutos) if absolutos else Decimal("0")
        self.barras[coluna] = [
            (
                float((abs(Decimal(v)) / maximo * 100).quantize(Decimal("0.1")))
                if v is not None and maximo
                else None
            )
            for v in valores
        ]


# --------------------------------------------------------------------------
# Gráfico
# --------------------------------------------------------------------------

#: Teto de linhas da tabela gêmea de cada gráfico (ver `Tabela.limite`).
LIMITE_DA_TABELA_GEMEA = 100

#: Teto da altura do canvas de um gráfico, em px. Um gráfico horizontal com uma
#: barra por lote chegava a 17.000 px com 585 lotes — acima do limite de canvas
#: dos navegadores (o card saía em branco) e inútil de ler. O ECharts omite os
#: rótulos que se sobrepõem; o detalhe está na tabela gêmea e na tabela de lotes.
ALTURA_MAXIMA_DO_GRAFICO = 1400

LARGURAS = {
    "quarto": "dash-col-3",
    "terco": "dash-col-4",
    "metade": "dash-col-6",
    "dois-tercos": "dash-col-8",
    "cheia": "dash-col-12",
}


@dataclass
class Grafico:
    id: str
    titulo: str
    tipo: str
    opcoes: dict
    tabela: Tabela | None = None
    nota: str = ""
    altura: int = 300
    largura: str = "metade"
    # Para onde o título leva (o relatório ou a lista que detalha o gráfico).
    url: str = ""
    rotulo_url: str = "Ver detalhe"
    # Gráfico com um elemento só (um bloco no mapa de calor, uma fatia de 100%,
    # uma barra) não compara nada: em vez de desenhá-lo, o cartão diz o que há.
    aviso_vazio: str = ""

    def __post_init__(self):
        self.altura = min(self.altura, ALTURA_MAXIMA_DO_GRAFICO)
        self.com_tabela(self.tabela)

    def com_tabela(self, tabela: Tabela | None) -> None:
        """Define a tabela gêmea já com o teto de linhas. Quem monta a tabela
        depois de criar o gráfico (ex.: curvas, onde o `x` não a descreve) usa
        isto: atribuir `g.tabela = ...` direto deixa a tabela sem limite."""
        self.tabela = tabela
        if tabela is not None and tabela.limite is None:
            tabela.limite = LIMITE_DA_TABELA_GEMEA

    @property
    def mensagem_vazia(self) -> str:
        return self.aviso_vazio or "Sem dados neste recorte."

    @property
    def classe_largura(self) -> str:
        return LARGURAS[self.largura]

    @property
    def vazio(self) -> bool:
        return bool(self.aviso_vazio) or not _tem_dado(self.tipo, self.opcoes)

    def para_json(self) -> dict:
        return {
            "id": self.id,
            "titulo": self.titulo,
            "tipo": self.tipo,
            "altura": self.altura,
            "opcoes": self.opcoes,
        }


def _tem_dado(tipo: str, o: dict) -> bool:
    """Gráfico sem nenhum ponto vira estado vazio, não eixo em branco."""
    if tipo == "cartesiano":
        return any(
            any(
                (d is not None and (d != 0 if not isinstance(d, list) else True))
                for d in s["dados"]
            )
            for s in o["series"]
        )
    if tipo == "rosca":
        return any(i["valor"] for i in o["itens"])
    if tipo == "treemap":
        return bool(o["nos"])
    if tipo == "calor":
        return any(c[2] for c in o["celulas"])
    if tipo == "cascata":
        return any(p["valor"] for p in o["passos"])
    if tipo == "dispersao":
        return any(s["pontos"] for s in o["series"])
    if tipo == "sankey":
        return bool(o["ligacoes"])
    if tipo == "calendario":
        return bool(o["dias"])
    if tipo == "funil":
        return any(e["valor"] for e in o["etapas"])
    return True


def _so_um(nome: str, valor: str, o_que: str) -> str:
    return f"Só há um item: {nome} ({valor}). {o_que} aparece quando houver mais de um para comparar."


def serie(nome, dados, *, tipo="bar", cor=None, pilha=None, rotulo=False, **extra):
    """Uma série de gráfico cartesiano. `dados` em `Decimal`/`int`/`None`;
    pares `[x, y]` quando o eixo X é numérico."""
    convertidos = [
        [num(d[0]), num(d[1])] if isinstance(d, list | tuple) else num(d) for d in dados
    ]
    return {
        "nome": nome,
        "tipo": tipo,
        "dados": convertidos,
        "cor": cor,
        "pilha": pilha,
        "rotulo": rotulo,
        **extra,
    }


def cartesiano(
    id,
    titulo,
    x,
    series,
    *,
    formato="num0",
    horizontal=False,
    zoom=False,
    linhas_ref=None,
    faixa=None,
    titulo_x="",
    titulo_y="",
    x_tipo="categoria",
    nota="",
    altura=300,
    largura="metade",
    url="",
    legenda_tabela="",
    formatos_series=None,
    **extra,
) -> Grafico:
    """Barras, linhas e áreas num **único** eixo de valor. Dois eixos Y nunca:
    a escala do segundo é arbitrária e inventa correlação. Duas grandezas →
    dois gráficos."""
    linhas = []
    nomes = [s["nome"] for s in series]
    formatos = formatos_series or {}
    for i, rotulo in enumerate(x):
        linha = [str(rotulo)]
        for s in series:
            bruto = s["dados"][i]
            valor = bruto[1] if isinstance(bruto, list) else bruto
            linha.append(formatar(valor, formatos.get(s["nome"], formato)))
        linhas.append(linha)
    return Grafico(
        id=id,
        titulo=titulo,
        tipo="cartesiano",
        opcoes={
            "x": [str(r) for r in x],
            "series": series,
            "formato": formato,
            "horizontal": horizontal,
            "zoom": zoom,
            "linhas_ref": linhas_ref or [],
            "faixa": faixa,
            "titulo_x": titulo_x,
            "titulo_y": titulo_y,
            "x_tipo": x_tipo,
            "formatos_series": formatos,
            **extra,
        },
        tabela=Tabela(
            [titulo_x or "Período", *nomes],
            linhas,
            numericas=list(range(1, len(nomes) + 1)),
            legenda=legenda_tabela,
        ),
        nota=nota,
        altura=altura,
        largura=largura,
        url=url,
    )


def ranking(
    id,
    titulo,
    itens,
    *,
    formato="brl",
    nome_serie="Valor",
    cor=None,
    mostrar_participacao=True,
    limite=10,
    nota="",
    largura="metade",
    url="",
    altura=None,
    aditivo=None,
) -> Grafico:
    """Barras horizontais ordenadas — o "Pareto" sem eixo duplo: o valor vai no
    rótulo e a participação acumulada na tabela e no tooltip.

    `itens`: `[(nome, valor Decimal)]` já em qualquer ordem."""
    ordenados = sorted(itens, key=lambda i: -(i[1] or 0))
    total = sum((Decimal(v or 0) for _, v in ordenados), Decimal("0"))
    ficam = ordenados[:limite]
    resto = ordenados[limite:]
    # "Outros (n)" só faz sentido para o que se soma (R$, cabeças): a soma de
    # taxas, médias e preços não significa nada — nesses, o corte só trunca.
    if aditivo is None:
        aditivo = formato in ("brl", "cb", "num0")
    if resto and not aditivo:
        resto = []
        nota = (
            nota + " " if nota else ""
        ) + f"Mostra os {limite} primeiros; o restante está na tabela do cartão."
    if resto:
        ficam.append(
            (
                f"Outros ({len(resto)})",
                sum((Decimal(v or 0) for _, v in resto), Decimal("0")),
            )
        )
    acumulado = Decimal("0")
    participacoes, acumulados = [], []
    for _, valor in ficam:
        acumulado += Decimal(valor or 0)
        participacoes.append(pct(valor, total))
        acumulados.append(pct(acumulado, total))
    nomes = [n for n, _ in ficam]
    valores = [v for _, v in ficam]
    s = serie(nome_serie, valores, cor=cor if cor is not None else "marca", rotulo=True)
    s["participacao"] = [num(p) for p in participacoes]
    s["acumulado"] = [num(a) for a in acumulados]
    tabela_cols = ["Item", nome_serie]
    linhas = []
    for nome, valor, p, a in zip(
        nomes, valores, participacoes, acumulados, strict=True
    ):
        linha = [nome, formatar(valor, formato)]
        if mostrar_participacao:
            linha += [formatar(p, "pct"), formatar(a, "pct")]
        linhas.append(linha)
    if mostrar_participacao:
        tabela_cols += ["% do total", "% acumulado"]
    aviso = (
        _so_um(nomes[0], formatar(valores[0], formato), "O ranking")
        if len(nomes) == 1
        else ""
    )
    return Grafico(
        id=id,
        titulo=titulo,
        aviso_vazio=aviso,
        tipo="cartesiano",
        opcoes={
            "x": nomes,
            "series": [s],
            "formato": formato,
            "horizontal": True,
            "zoom": False,
            "linhas_ref": [],
            "faixa": None,
            "titulo_x": "",
            "titulo_y": "",
            "x_tipo": "categoria",
            "formatos_series": {},
            "ranking": True,
        },
        tabela=Tabela(tabela_cols, linhas, numericas=list(range(1, len(tabela_cols)))),
        nota=nota,
        altura=altura or max(220, 44 + 34 * len(nomes)),
        largura=largura,
        url=url,
    )


def rosca(
    id,
    titulo,
    itens,
    *,
    formato="num0",
    centro_rotulo="Total",
    nota="",
    largura="terco",
    altura=300,
    url="",
) -> Grafico:
    """Parte do todo, até 6 fatias: além disso, ranking. `itens`:
    `[(nome, valor, cor|None)]`."""
    total = sum((Decimal(v or 0) for _, v, _ in itens), Decimal("0"))
    linhas = [
        [n, formatar(v, formato), formatar(pct(v, total), "pct")] for n, v, _ in itens
    ]
    com_valor = [(n, v) for n, v, _ in itens if v]
    aviso = (
        _so_um(
            com_valor[0][0], formatar(com_valor[0][1], formato) + ", 100%", "A divisão"
        )
        if len(com_valor) == 1
        else ""
    )
    return Grafico(
        id=id,
        titulo=titulo,
        aviso_vazio=aviso,
        tipo="rosca",
        opcoes={
            "itens": [{"nome": n, "valor": num(v), "cor": c} for n, v, c in itens],
            "formato": formato,
            "centro": {"valor": formatar(total, formato), "rotulo": centro_rotulo},
        },
        tabela=Tabela(["Item", "Valor", "% do total"], linhas, numericas=[1, 2]),
        nota=nota,
        altura=altura,
        largura=largura,
        url=url,
    )


def treemap(
    id, titulo, nos, *, formato="brl", nota="", largura="metade", altura=340, url=""
) -> Grafico:
    """`nos`: `[{"nome", "valor", "filhos": [{"nome","valor"}]}]`."""

    def converte(no):
        saida = {"nome": no["nome"], "valor": num(no["valor"])}
        if no.get("filhos"):
            saida["filhos"] = [converte(f) for f in no["filhos"]]
        return saida

    total = sum((Decimal(n["valor"] or 0) for n in nos), Decimal("0"))
    folhas = [
        (n["nome"] if not f else f"{n['nome']} › {f['nome']}", (f or n)["valor"])
        for n in nos
        for f in (n.get("filhos") or [None])
    ]
    aviso = (
        _so_um(folhas[0][0], formatar(folhas[0][1], formato), "O mapa em árvore")
        if len(folhas) == 1
        else ""
    )
    linhas = []
    for n in nos:
        linhas.append(
            [
                n["nome"],
                formatar(n["valor"], formato),
                formatar(pct(n["valor"], total), "pct"),
            ]
        )
        for f in n.get("filhos") or []:
            linhas.append(
                [
                    f"   {f['nome']}",
                    formatar(f["valor"], formato),
                    formatar(pct(f["valor"], total), "pct"),
                ]
            )
    return Grafico(
        id=id,
        titulo=titulo,
        aviso_vazio=aviso,
        tipo="treemap",
        opcoes={"nos": [converte(n) for n in nos], "formato": formato},
        tabela=Tabela(["Item", "Valor", "% do total"], linhas, numericas=[1, 2]),
        nota=nota,
        altura=altura,
        largura=largura,
        url=url,
    )


def calor(
    id,
    titulo,
    x,
    y,
    valores,
    *,
    formato="num0",
    nota="",
    largura="metade",
    altura=None,
    titulo_x="",
    titulo_y="",
    url="",
) -> Grafico:
    """Grade `y × x`. `valores`: `{(xi, yi): valor}`."""
    celulas = [[xi, yi, num(v)] for (xi, yi), v in valores.items()]
    com_valor = [(k, v) for k, v in valores.items() if v]
    aviso = ""
    if len(com_valor) == 1:
        (xi, yi), unico = com_valor[0]
        aviso = _so_um(
            f"{y[yi]} · {x[xi]}", formatar(unico, formato), "O mapa de calor"
        )
    linhas = []
    for yi, rotulo_y in enumerate(y):
        linhas.append(
            [str(rotulo_y)]
            + [formatar(valores.get((xi, yi)), formato) for xi in range(len(x))]
        )
    return Grafico(
        id=id,
        titulo=titulo,
        aviso_vazio=aviso,
        tipo="calor",
        opcoes={
            "x": [str(r) for r in x],
            "y": [str(r) for r in y],
            "celulas": celulas,
            "formato": formato,
            "titulo_x": titulo_x,
            "titulo_y": titulo_y,
        },
        tabela=Tabela(
            [titulo_y or ""] + [str(r) for r in x],
            linhas,
            numericas=list(range(1, len(x) + 1)),
        ),
        nota=nota,
        altura=altura or max(240, 90 + 34 * len(y)),
        largura=largura,
        url=url,
    )


def cascata(
    id, titulo, passos, *, formato="brl", nota="", largura="metade", altura=320, url=""
) -> Grafico:
    """`passos`: `[(nome, valor, "total"|"delta")]`. O valor de um `delta` tem
    sinal; um `total` mostra o acumulado até ali."""
    linhas = [[n, formatar(v, formato)] for n, v, _ in passos]
    return Grafico(
        id=id,
        titulo=titulo,
        tipo="cascata",
        opcoes={
            "passos": [{"nome": n, "valor": num(v), "tipo": t} for n, v, t in passos],
            "formato": formato,
        },
        tabela=Tabela(["Etapa", "Valor"], linhas, numericas=[1]),
        nota=nota,
        altura=altura,
        largura=largura,
        url=url,
    )


def dispersao(
    id,
    titulo,
    series,
    *,
    formato_x="num0",
    formato_y="num0",
    titulo_x="",
    titulo_y="",
    linhas_ref=None,
    faixa=None,
    nota="",
    largura="metade",
    altura=340,
    url="",
    colunas_tabela=None,
) -> Grafico:
    """`series`: `[{"nome", "cor", "pontos": [{"x","y","r","nome"}]}]` — até 3
    séries (a partir de 4 cores, pares de pontos vizinhos deixam de se
    distinguir). Cada ponto tem área de toque ampla."""
    convertidas, linhas = [], []
    for s in series:
        pontos = []
        for p in s["pontos"]:
            pontos.append(
                {
                    "x": num(p["x"]),
                    "y": num(p["y"]),
                    "r": num(p.get("r")),
                    "nome": p.get("nome", ""),
                }
            )
            linhas.append(
                [
                    p.get("nome", ""),
                    s["nome"],
                    formatar(p["x"], formato_x),
                    formatar(p["y"], formato_y),
                ]
                + ([formatar(p.get("r"), "num0")] if colunas_tabela else [])
            )
        convertidas.append({"nome": s["nome"], "cor": s.get("cor"), "pontos": pontos})
    colunas = ["Item", "Grupo", titulo_x or "X", titulo_y or "Y"]
    if colunas_tabela:
        colunas.append(colunas_tabela)
    return Grafico(
        id=id,
        titulo=titulo,
        tipo="dispersao",
        opcoes={
            "series": convertidas,
            "formato_x": formato_x,
            "formato_y": formato_y,
            "titulo_x": titulo_x,
            "titulo_y": titulo_y,
            "linhas_ref": linhas_ref or [],
            "faixa": faixa,
        },
        tabela=Tabela(
            colunas, linhas, numericas=[2, 3] + ([4] if colunas_tabela else [])
        ),
        nota=nota,
        altura=altura,
        largura=largura,
        url=url,
    )


def sankey(
    id,
    titulo,
    nos,
    ligacoes,
    *,
    formato="cb",
    nota="",
    largura="cheia",
    altura=360,
    url="",
) -> Grafico:
    """`nos`: `[(nome, cor)]`; `ligacoes`: `[(de, para, valor)]`."""
    return Grafico(
        id=id,
        titulo=titulo,
        tipo="sankey",
        opcoes={
            "nos": [{"nome": n, "cor": c} for n, c in nos],
            "ligacoes": [
                {"de": a, "para": b, "valor": num(v)} for a, b, v in ligacoes if v
            ],
            "formato": formato,
        },
        tabela=Tabela(
            ["De", "Para", "Quantidade"],
            [[a, b, formatar(v, formato)] for a, b, v in ligacoes if v],
            numericas=[2],
        ),
        nota=nota,
        altura=altura,
        largura=largura,
        url=url,
    )


def calendario(
    id,
    titulo,
    inicio,
    fim,
    dias,
    *,
    formato="brl",
    nota="",
    largura="cheia",
    altura=210,
    url="",
) -> Grafico:
    """`dias`: `{data: valor}`."""
    itens = sorted(dias.items())
    return Grafico(
        id=id,
        titulo=titulo,
        tipo="calendario",
        opcoes={
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "dias": [[d.isoformat(), num(v)] for d, v in itens],
            "formato": formato,
        },
        tabela=Tabela(
            ["Data", "Valor"],
            [[f"{d:%d/%m/%Y}", formatar(v, formato)] for d, v in itens],
            numericas=[1],
        ),
        nota=nota,
        altura=altura,
        largura=largura,
        url=url,
    )


def funil(
    id, titulo, etapas, *, formato="num0", nota="", largura="metade", altura=300, url=""
) -> Grafico:
    """Etapas **ordenadas** (ordinal, uma matiz clara→escura). `etapas`:
    `[(nome, valor, rotulo_extra)]`."""
    return Grafico(
        id=id,
        titulo=titulo,
        tipo="funil",
        opcoes={
            "etapas": [{"nome": n, "valor": num(v), "rotulo": r} for n, v, r in etapas],
            "formato": formato,
        },
        tabela=Tabela(
            ["Etapa", "Quantidade", "Detalhe"],
            [[n, formatar(v, formato), r] for n, v, r in etapas],
            numericas=[1],
        ),
        nota=nota,
        altura=altura,
        largura=largura,
        url=url,
    )


# --------------------------------------------------------------------------
# KPI
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Delta:
    texto: str  # "+12,4%" · "−0,8 p.p."
    sentido: str  # alta | baixa | estavel
    avaliacao: str  # bom | ruim | neutro
    base: str  # "vs. safra anterior no mesmo ponto"

    @property
    def icone(self) -> str:
        return {
            "alta": "arrow-up-right",
            "baixa": "arrow-down-right",
        }.get(self.sentido, "minus")

    @property
    def leitura(self) -> str:
        """Texto para leitor de tela: cor e seta nunca falam sozinhas."""
        verbo = {"alta": "subiu", "baixa": "caiu", "estavel": "ficou estável"}[
            self.sentido
        ]
        juizo = {"bom": "(favorável)", "ruim": "(desfavorável)", "neutro": ""}[
            self.avaliacao
        ]
        return f"{verbo} {self.texto} {self.base} {juizo}".strip()


def _avaliar(sentido: str, bom_quando: str | None) -> str:
    if sentido == "estavel" or bom_quando is None:
        return "neutro"
    return "bom" if sentido == bom_quando else "ruim"


def variacao(
    atual,
    anterior,
    *,
    bom_quando: str | None = "alta",
    base: str = "vs. safra anterior no mesmo ponto",
) -> Delta | None:
    """Variação percentual. `None` sem base (anterior ausente ou zero): falta de
    dado é "—", nunca +∞ nem 0%."""
    if atual is None or anterior is None:
        return None
    anterior = Decimal(anterior)
    razao = safe_div(Decimal(atual) - anterior, abs(anterior))
    if razao is None:
        return None
    p = razao * CEM
    sentido = "estavel" if abs(p) < Decimal("0.05") else ("alta" if p > 0 else "baixa")
    sinal = "+" if p > 0 else ("−" if p < 0 else "")
    return Delta(
        f"{sinal}{numero_br(abs(p), 1)}%", sentido, _avaliar(sentido, bom_quando), base
    )


def variacao_pp(
    atual,
    anterior,
    *,
    bom_quando: str | None = "alta",
    base: str = "vs. safra anterior no mesmo ponto",
) -> Delta | None:
    """Diferença em pontos percentuais — para indicador que já é %."""
    if atual is None or anterior is None:
        return None
    d = Decimal(atual) - Decimal(anterior)
    sentido = "estavel" if abs(d) < Decimal("0.05") else ("alta" if d > 0 else "baixa")
    sinal = "+" if d > 0 else ("−" if d < 0 else "")
    return Delta(
        f"{sinal}{numero_br(abs(d), 1)} p.p.",
        sentido,
        _avaliar(sentido, bom_quando),
        base,
    )


@dataclass(frozen=True)
class Spark:
    pontos: str
    # Texto, não número: o Django localiza `float` em pt-BR ("93,0") e o atributo
    # SVG exige ponto decimal.
    ultimo_x: str
    ultimo_y: str
    area: str


def sparkline(
    valores, *, largura: int = 160, altura: int = 28, margem: int = 3
) -> Spark | None:
    """Pontos do `<polyline>` SVG de uma série curta. Desenhado no servidor: o
    cartão aparece com o gráfico mesmo antes (ou sem) o JavaScript. Menos de 2
    pontos válidos → `None` (uma linha de um ponto não conta nada)."""
    validos = [Decimal(v) for v in valores if v is not None]
    if len(validos) < 2:
        return None
    menor, maior = min(validos), max(validos)
    amplitude = maior - menor
    passo = (largura - 2 * margem) / (len(validos) - 1)
    util = altura - 2 * margem
    coords = []
    for i, v in enumerate(validos):
        y_rel = safe_div(v - menor, amplitude) if amplitude else Decimal("0.5")
        x = margem + i * passo
        y = margem + util * (1 - float(y_rel))
        coords.append((round(x, 1), round(y, 1)))
    pontos = " ".join(f"{x},{y}" for x, y in coords)
    base_y = altura - margem
    area = f"{coords[0][0]},{base_y} {pontos} {coords[-1][0]},{base_y}"
    return Spark(pontos, f"{coords[-1][0]:.1f}", f"{coords[-1][1]:.1f}", area)


@dataclass(frozen=True)
class Kpi:
    rotulo: str
    valor: str
    unidade: str = ""
    nota: str = ""
    delta: Delta | None = None
    spark: Spark | None = None
    url: str = ""
    ajuda: str = ""
    # `bom`/`atencao`/`ruim` pinta a borda esquerda E ganha ícone e texto
    # (cor nunca sozinha).
    estado: str = ""
    estado_texto: str = ""
    destaque: bool = False
    # Medidor de 0 a 100 (cartão de ocupação, p. ex.): a barra preenche até aqui.
    medidor: Decimal | None = None


@dataclass
class Secao:
    titulo: str
    graficos: list[Grafico] = field(default_factory=list)
    descricao: str = ""
    id: str = ""
    tabelas: list[Tabela] = field(default_factory=list)


@dataclass
class Insight:
    nivel: str  # alerta | atencao | info | positivo
    titulo: str
    texto: str
    url: str = ""
    rotulo_url: str = "Ver"

    @property
    def icone(self) -> str:
        return {
            "alerta": "triangle-alert",
            "atencao": "triangle-alert",
            "positivo": "circle-check",
        }.get(self.nivel, "lightbulb")


LARGURA_EM_COLUNAS = {
    "quarto": 3,
    "terco": 4,
    "metade": 6,
    "dois-tercos": 8,
    "cheia": 12,
}
_DE_COLUNAS = {v: k for k, v in LARGURA_EM_COLUNAS.items()}


def reorganizar(graficos: list[Grafico]) -> None:
    """Fecha as linhas da grade: as larguras pedidas são só uma dica. Empacota os
    cartões em linhas de 12 colunas e redistribui a sobra, para nunca sobrar um
    buraco ao lado de um cartão (a ordem é preservada)."""
    linha: list[Grafico] = []

    def fechar():
        if not linha:
            return
        soma = sum(LARGURA_EM_COLUNAS[g.largura] for g in linha)
        if soma < 12:
            n = len(linha)
            if n == 1:
                alvo = [12]
            elif n == 2:
                maior = max(LARGURA_EM_COLUNAS[g.largura] for g in linha)
                alvo = (
                    [8, 4]
                    if maior == 8 and LARGURA_EM_COLUNAS[linha[0].largura] == 8
                    else ([4, 8] if maior == 8 else [6, 6])
                )
            elif n == 3:
                alvo = [4, 4, 4]
            else:
                alvo = [3] * 4
            for g, cols in zip(linha, alvo, strict=False):
                g.largura = _DE_COLUNAS[cols]
        linha.clear()

    acumulado = 0
    for g in graficos:
        cols = LARGURA_EM_COLUNAS[g.largura]
        if acumulado + cols > 12:
            fechar()
            acumulado = 0
        linha.append(g)
        acumulado += cols
        if acumulado == 12:
            fechar()
            acumulado = 0
    fechar()


@dataclass
class Painel:
    """O que uma aba entrega ao template."""

    kpis: list[Kpi] = field(default_factory=list)
    secoes: list[Secao] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    # Por que um bloco está incompleto ("2 lotes sem pesagem") — falta de dado
    # é estado normal, mas nunca silenciosa.
    avisos: list[str] = field(default_factory=list)
    vazio: str = ""
    kpis_titulo: str = ""

    def graficos(self) -> list[Grafico]:
        return [g for s in self.secoes for g in s.graficos]

    def finalizar(self) -> Painel:
        """Ajustes de apresentação, depois que a aba montou tudo."""
        for secao in self.secoes:
            reorganizar(secao.graficos)
        return self

    def json_dos_graficos(self) -> dict:
        return {g.id: g.para_json() for g in self.graficos() if not g.vazio}


def rotulo_do_mes(mes: datetime.date) -> str:
    """ "jul/25": curto para caber 12 meses sem girar o texto do eixo."""
    from apps.finance.selectors import NOMES_DOS_MESES

    return f"{NOMES_DOS_MESES[mes.month - 1]}/{mes.year % 100:02d}"
