"""Aba **Compras** — quanto se investiu, em quê, com quem e a que preço.

Custo de aquisição, custo/@ e custo/cabeça vêm de `calcular_custo_da_compra`
(o mesmo serviço da tela da compra): este módulo só soma e compara.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.urls import reverse

from apps.core.money import safe_div
from apps.purchases.services import calcular_custo_da_compra

from . import specs
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")

#: Um vendedor com mais disto das compras da safra é concentração de risco
#: (pendência #48 — limiar de leitura, não regra de bloqueio).
CONCENTRACAO_ALERTA_PERCENTUAL = Decimal("40")


@dataclass(frozen=True)
class Agregado:
    """Várias compras somadas. Os indicadores **por @ e por kg** só contam as
    compras que informaram peso: dividir o valor de todas pelo peso de algumas
    inflaria o preço (a mesma regra do agregado de vendas)."""

    compras: int
    cabecas: int
    animais: Decimal
    frete: Decimal
    comissao: Decimal
    impostos: Decimal
    cabecas_com_peso: int
    peso_kg: Decimal
    custo_com_peso: Decimal

    @property
    def custo(self) -> Decimal:
        return self.animais + self.frete + self.comissao + self.impostos

    def indicadores(self):
        """`CustoDaCompra` do conjunto — a divisão é do serviço."""
        total = calcular_custo_da_compra(
            head_count=self.cabecas,
            animal_value=self.animais,
            freight_value=self.frete,
            commission_value=self.comissao,
            tax_value=self.impostos,
        )
        com_peso = calcular_custo_da_compra(
            head_count=self.cabecas_com_peso,
            animal_value=self.custo_com_peso,
            total_weight_kg=self.peso_kg or None,
        )
        return total, com_peso

    @property
    def custo_por_cabeca(self):
        return self.indicadores()[0].custo_por_cabeca

    @property
    def custo_por_arroba(self):
        return self.indicadores()[1].custo_por_arroba

    @property
    def peso_medio_kg(self):
        return self.indicadores()[1].peso_medio_kg


def agregar(compras) -> Agregado:
    compras = list(compras)
    com_peso = [c for c in compras if c.total_weight_kg]
    return Agregado(
        compras=len(compras),
        cabecas=sum(c.head_count for c in compras),
        animais=sum((c.animal_value for c in compras), ZERO),
        frete=sum((c.freight_value or ZERO for c in compras), ZERO),
        comissao=sum((c.commission_value or ZERO for c in compras), ZERO),
        impostos=sum((c.tax_value or ZERO for c in compras), ZERO),
        cabecas_com_peso=sum(c.head_count for c in com_peso),
        peso_kg=sum((c.total_weight_kg for c in com_peso), ZERO),
        custo_com_peso=sum(
            (
                c.animal_value
                + (c.freight_value or ZERO)
                + (c.commission_value or ZERO)
                + (c.tax_value or ZERO)
                for c in com_peso
            ),
            ZERO,
        ),
    )


def lista_de_compras(e: Escopo) -> list:
    return e.memo(
        "compras",
        lambda: list(
            e.compras()
            .select_related("seller", "destination_farm", "category", "lot")
            .order_by("date", "id")
        ),
    )


def agregado_da_safra(e: Escopo) -> Agregado:
    return e.memo("compras_agregado", lambda: agregar(lista_de_compras(e)))


def por_mes(e: Escopo) -> dict[datetime.date, Agregado]:
    grupos = defaultdict(list)
    for c in lista_de_compras(e):
        grupos[c.date.replace(day=1)].append(c)
    return {m: agregar(grupos.get(m, [])) for m in e.meses}


def prazo_medio_de_pagamento(e: Escopo) -> Decimal | None:
    """Dias, ponderados pelo valor dos animais. Só compra com prazo informado."""
    com_prazo = [c for c in lista_de_compras(e) if c.payment_days is not None]
    base = sum((c.animal_value for c in com_prazo), ZERO)
    return safe_div(
        sum((c.animal_value * c.payment_days for c in com_prazo), ZERO), base
    )


def concentracao_de_vendedores(e: Escopo) -> list[tuple[str, Decimal, Decimal | None]]:
    """`[(vendedor, valor, % do total)]`, do maior para o menor."""
    soma = defaultdict(lambda: ZERO)
    for c in lista_de_compras(e):
        soma[c.seller.name] += c.animal_value
    total = sum(soma.values(), ZERO)
    return [
        (nome, valor, specs.pct(valor, total))
        for nome, valor in sorted(soma.items(), key=lambda kv: -kv[1])
    ]


# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------


def kpis(e: Escopo) -> list[Kpi]:
    atual = agregado_da_safra(e)
    anterior = agregar(e.anterior.compras()) if e.anterior else None
    meses = por_mes(e)
    top = concentracao_de_vendedores(e)
    top3 = sum((p for _, _, p in top[:3] if p is not None), ZERO) if top else None
    prazo = prazo_medio_de_pagamento(e)
    url = reverse("purchases:lista")
    return [
        Kpi(
            "Investimento em compras",
            # Sem nenhuma compra o investimento é "—", não "R$ 0,00" (regra 3).
            specs.brl_curto(atual.custo) if atual.compras else specs.TRAVESSAO,
            nota=f"{specs.formatar(atual.cabecas)} cabeças · {atual.compras} compra(s)",
            delta=specs.variacao(
                atual.custo, anterior.custo if anterior else None, bom_quando=None
            ),
            spark=specs.sparkline([m.custo for m in meses.values()]),
            url=url,
            ajuda="Custo de aquisição: animais + frete + comissão + impostos, das compras confirmadas da safra.",
            destaque=True,
        ),
        Kpi(
            "Cabeças compradas",
            specs.formatar(atual.cabecas),
            "cabeças",
            delta=specs.variacao(
                atual.cabecas, anterior.cabecas if anterior else None, bom_quando=None
            ),
            spark=specs.sparkline([m.cabecas for m in meses.values()]),
            url=url,
        ),
        Kpi(
            "Custo por cabeça",
            specs.formatar(atual.custo_por_cabeca, "brl"),
            nota="aquisição ÷ cabeças",
            delta=specs.variacao(
                atual.custo_por_cabeca,
                anterior.custo_por_cabeca if anterior else None,
                bom_quando=None,
            ),
            ajuda="Varia com o tipo de animal comprado: bezerro e boi gordo têm preços muito diferentes.",
        ),
        Kpi(
            "Custo por @ (peso vivo)",
            specs.formatar(atual.custo_por_arroba, "brl"),
            nota="só compras com peso informado",
            delta=specs.variacao(
                atual.custo_por_arroba,
                anterior.custo_por_arroba if anterior else None,
                bom_quando=None,
            ),
            ajuda="Custo de aquisição ÷ arrobas de peso vivo. Compra sem peso fica fora do cálculo.",
        ),
        Kpi(
            "Peso médio de entrada",
            specs.formatar(atual.peso_medio_kg, "kg"),
            nota=f"{specs.formatar(atual.cabecas_com_peso)} cb com peso informado",
        ),
        Kpi(
            "Prazo médio de pagamento",
            specs.formatar(prazo, "dias"),
            nota="ponderado pelo valor",
        ),
        Kpi(
            "Vendedores",
            specs.formatar(len(top)),
            nota=(
                f"3 maiores = {specs.formatar(top3, 'pct')} do valor"
                if top3 is not None
                else ""
            ),
        ),
    ]


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def grafico_por_mes(e: Escopo) -> specs.Grafico:
    meses = por_mes(e)
    return specs.cartesiano(
        "compras-mes",
        "Compras por mês",
        [specs.rotulo_do_mes(m) for m in meses],
        [
            specs.serie(
                "Custo de aquisição",
                [a.custo for a in meses.values()],
                cor=specs.COR_COMPRAS,
            )
        ],
        formato="brl",
        titulo_y="R$",
        largura="dois-tercos",
        url=reverse("purchases:lista"),
    )


def grafico_cabecas_por_mes(e: Escopo) -> specs.Grafico:
    meses = por_mes(e)
    return specs.cartesiano(
        "compras-cabecas",
        "Cabeças compradas por mês",
        [specs.rotulo_do_mes(m) for m in meses],
        [
            specs.serie(
                "Cabeças", [a.cabecas for a in meses.values()], cor=specs.COR_COMPRAS
            )
        ],
        formato="cb",
        largura="terco",
    )


def grafico_preco(e: Escopo) -> specs.Grafico:
    meses = por_mes(e)
    return specs.cartesiano(
        "compras-preco-arroba",
        "Custo por @ de peso vivo, mês a mês",
        [specs.rotulo_do_mes(m) for m in meses],
        [
            specs.serie(
                "Custo/@ (peso vivo)",
                [
                    a.custo_por_arroba if a.cabecas_com_peso else None
                    for a in meses.values()
                ],
                tipo="line",
                cor="marca",
            )
        ],
        formato="brl",
        titulo_y="R$ por @",
        nota="Mês sem compra com peso informado fica em branco: não se liga um ponto que não existe.",
        largura="metade",
    )


def grafico_preco_cabeca(e: Escopo) -> specs.Grafico:
    meses = por_mes(e)
    return specs.cartesiano(
        "compras-preco-cabeca",
        "Custo por cabeça, mês a mês",
        [specs.rotulo_do_mes(m) for m in meses],
        [
            specs.serie(
                "Custo/cabeça",
                [a.custo_por_cabeca if a.cabecas else None for a in meses.values()],
                tipo="line",
                cor="marca",
            )
        ],
        formato="brl",
        titulo_y="R$ por cabeça",
        largura="metade",
    )


def grafico_composicao_do_custo(e: Escopo) -> specs.Grafico:
    a = agregado_da_safra(e)
    return specs.rosca(
        "compras-composicao",
        "De que é feito o custo de aquisição",
        [
            ("Animais", a.animais, specs.COR_COMPRAS),
            ("Frete", a.frete, specs.COR_CUSTOS),
            ("Comissão", a.comissao, specs.COR_ALERTA),
            ("Impostos", a.impostos, 4),
        ],
        formato="brl",
        centro_rotulo="aquisição",
        largura="terco",
    )


def grafico_vendedores(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "compras-vendedores",
        "Quem vendeu mais",
        [(n, v) for n, v, _ in concentracao_de_vendedores(e)],
        formato="brl",
        nome_serie="Valor dos animais",
        largura="dois-tercos",
        nota="Valor dos animais por vendedor. A tabela traz a participação acumulada.",
        url=reverse("partners:lista"),
    )


def grafico_por_fazenda(e: Escopo) -> specs.Grafico:
    soma = defaultdict(lambda: ZERO)
    for c in lista_de_compras(e):
        soma[c.destination_farm.name] += c.animal_value
    return specs.ranking(
        "compras-fazenda",
        "Destino das compras",
        list(soma.items()),
        formato="brl",
        nome_serie="Valor dos animais",
        largura="terco",
    )


def grafico_por_categoria(e: Escopo) -> specs.Grafico:
    soma = defaultdict(int)
    for c in lista_de_compras(e):
        soma[c.category.name if c.category_id else "Sem categoria"] += c.head_count
    return specs.ranking(
        "compras-categoria",
        "O que se comprou",
        list(soma.items()),
        formato="cb",
        nome_serie="Cabeças",
        largura="terco",
    )


def grafico_acumulado_contra_safra_anterior(e: Escopo) -> specs.Grafico | None:
    """Mesmo ponto da safra anterior: o acumulado das duas, mês a mês."""
    if not e.anterior:
        return None

    def acumulado(escopo):
        agregados = por_mes(escopo)
        total, saida = ZERO, []
        for a in agregados.values():
            total += a.custo
            saida.append(total)
        return saida

    atual = acumulado(e)
    anterior = acumulado(e.anterior)
    n = max(len(atual), len(anterior))
    x = [f"Mês {i + 1}" for i in range(n)]
    pad = lambda s: s + [None] * (n - len(s))  # noqa: E731
    return specs.cartesiano(
        "compras-acumulado",
        "Investimento acumulado: safra atual × anterior",
        x,
        [
            specs.serie(f"Safra {e.season.name}", pad(atual), tipo="line", cor="marca"),
            specs.serie(
                f"Safra {e.anterior.season.name}",
                pad(anterior),
                tipo="line",
                cor="neutro",
            ),
        ],
        formato="brl",
        titulo_y="R$ acumulados",
        nota="Meses contados desde o início de cada safra, até o mesmo ponto.",
        largura="metade",
    )


def grafico_dispersao(e: Escopo) -> specs.Grafico:
    pontos = []
    for c in lista_de_compras(e):
        if not c.total_weight_kg:
            continue
        custo = calcular_custo_da_compra(
            head_count=c.head_count,
            animal_value=c.animal_value,
            freight_value=c.freight_value,
            commission_value=c.commission_value,
            tax_value=c.tax_value,
            total_weight_kg=c.total_weight_kg,
        )
        pontos.append(
            {
                "x": custo.peso_medio_kg,
                "y": custo.custo_por_arroba,
                "r": c.head_count,
                "nome": f"{c.code} · {c.seller.name}",
            }
        )
    return specs.dispersao(
        "compras-dispersao",
        "Peso de entrada × custo por @",
        [{"nome": "Compras", "cor": "marca", "pontos": pontos}],
        formato_x="kg",
        formato_y="brl",
        titulo_x="Peso médio de entrada (kg)",
        titulo_y="Custo por @ (R$)",
        nota="Cada bolha é uma compra; o tamanho é o número de cabeças.",
        colunas_tabela="Cabeças",
        largura="metade",
    )


def tabela_maiores_compras(e: Escopo) -> Tabela:
    maiores = sorted(
        lista_de_compras(e),
        key=lambda c: -calcular_custo_da_compra(
            head_count=c.head_count,
            animal_value=c.animal_value,
            freight_value=c.freight_value,
            commission_value=c.commission_value,
            tax_value=c.tax_value,
        ).custo_aquisicao,
    )[:10]
    linhas, links, totais = [], [], []
    for c in maiores:
        custo = calcular_custo_da_compra(
            head_count=c.head_count,
            animal_value=c.animal_value,
            freight_value=c.freight_value,
            commission_value=c.commission_value,
            tax_value=c.tax_value,
            total_weight_kg=c.total_weight_kg,
        )
        linhas.append(
            [
                c.code,
                f"{c.date:%d/%m/%Y}",
                c.seller.name,
                c.destination_farm.name,
                specs.formatar(c.head_count),
                specs.formatar(custo.peso_medio_kg, "kg"),
                specs.formatar(custo.custo_por_arroba, "brl"),
                specs.formatar(custo.custo_aquisicao, "brl"),
            ]
        )
        links.append(reverse("purchases:detalhe", args=[c.pk]))
        totais.append(custo.custo_aquisicao)
    t = Tabela(
        [
            "Compra",
            "Data",
            "Vendedor",
            "Fazenda",
            "Cabeças",
            "Peso médio",
            "Custo/@",
            "Aquisição",
        ],
        linhas,
        numericas=[4, 5, 6, 7],
        titulo="Dez maiores compras da safra",
        links=links,
        codigo=0,
        vazio="Nenhuma compra confirmada na safra.",
    )
    t.barra(7, totais)
    return t


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis(e), kpis_titulo="Compras da safra")
    if not lista_de_compras(e):
        painel.vazio = "Nenhuma compra confirmada na safra e no recorte escolhidos."
    sem_peso = [c for c in lista_de_compras(e) if not c.total_weight_kg]
    if sem_peso:
        painel.avisos.append(
            f"{len(sem_peso)} compra(s) sem peso informado: ficam fora do custo por @ e do peso médio."
        )
    graficos_ritmo = [grafico_por_mes(e), grafico_cabecas_por_mes(e)]
    comparacao = grafico_acumulado_contra_safra_anterior(e)
    painel.secoes = [
        Secao("Ritmo de compra", graficos_ritmo),
        Secao(
            "Preço",
            [grafico_preco(e), grafico_preco_cabeca(e)]
            + ([comparacao] if comparacao else [])
            + [grafico_dispersao(e)],
        ),
        Secao(
            "Com quem, para onde e o quê",
            [
                grafico_composicao_do_custo(e),
                grafico_vendedores(e),
                grafico_por_fazenda(e),
                grafico_por_categoria(e),
            ],
            tabelas=[tabela_maiores_compras(e)],
        ),
    ]
    return painel
