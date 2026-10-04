"""O registro das abas do dashboard e quem vê cada uma.

Adicionar uma aba = um módulo com `montar(escopo) -> Painel` e uma linha aqui.
A barreira de verdade é a view (`403` para quem não pode); esconder a aba do
menu é só gentileza com quem não a veria de qualquer jeito.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from apps.finance.permissions import pode_ver_titulos
from apps.procurement.permissions import pode_ver_o_ciclo

from . import (
    ciclo,
    compras,
    custos,
    financeiro,
    lotes,
    mortes,
    rebanho,
    vendas,
    visao_geral,
)
from .escopo import Escopo, pode_ver_dinheiro
from .specs import Painel

PADRAO = "visao-geral"


@dataclass(frozen=True)
class Aba:
    slug: str
    rotulo: str
    icone: str
    resumo: str
    montar: Callable[[Escopo], Painel]
    visivel: Callable[[object], bool]


def _todos(user) -> bool:
    return user.is_authenticated


def _com_dinheiro(user) -> bool:
    return pode_ver_dinheiro(user)


def _financeiro(user) -> bool:
    return pode_ver_dinheiro(user) and pode_ver_titulos(user)


def _ciclo(user) -> bool:
    return pode_ver_dinheiro(user) and pode_ver_o_ciclo(user)


ABAS = (
    Aba(
        "visao-geral",
        "Visão geral",
        "layout-dashboard",
        "Os números que importam e o que merece atenção.",
        visao_geral.montar,
        _todos,
    ),
    Aba(
        "rebanho",
        "Rebanho",
        "beef",
        "Onde estão os animais, de onde vieram e para onde foram.",
        rebanho.montar,
        _todos,
    ),
    Aba(
        "mortes",
        "Mortes",
        "triangle-alert",
        "Quantas, quando, de quê e onde.",
        mortes.montar,
        _todos,
    ),
    Aba(
        "lotes",
        "Lotes",
        "layers",
        "Ganho de peso, custo e margem, lote a lote.",
        lotes.montar,
        _todos,
    ),
    Aba(
        "compras",
        "Compras",
        "shopping-cart",
        "Quanto se investiu, com quem e a que preço.",
        compras.montar,
        _com_dinheiro,
    ),
    Aba(
        "vendas",
        "Vendas e resultado",
        "trending-up",
        "O que entrou e se o boi pagou o que custou criar.",
        vendas.montar,
        _com_dinheiro,
    ),
    Aba(
        "custos",
        "Custos",
        "coins",
        "Para onde foi o dinheiro de operar.",
        custos.montar,
        _com_dinheiro,
    ),
    Aba(
        "financeiro",
        "Financeiro",
        "wallet",
        "O que se deve, o que se tem a receber e quando.",
        financeiro.montar,
        _financeiro,
    ),
    Aba(
        "ciclo",
        "Ciclo de compra",
        "truck",
        "Do compromisso ao acerto: viagens, quebra e frete.",
        ciclo.montar,
        _ciclo,
    ),
)

_POR_SLUG = {a.slug: a for a in ABAS}


def abas_visiveis(user) -> list[Aba]:
    return [a for a in ABAS if a.visivel(user)]


def aba_por_slug(slug: str) -> Aba | None:
    return _POR_SLUG.get(slug)
