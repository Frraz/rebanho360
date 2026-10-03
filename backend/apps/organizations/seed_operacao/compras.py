"""Compras diretas de gado e de touros.

A compra direta é o caminho curto (rascunho → confirmada): gera o lote, a
entrada no rebanho, os custos e os títulos a pagar. O ciclo completo
(compromisso → viagem → recebimento → acerto) está em `ciclo.py`.

Frete, comissão e tributo são **digitados** — o sistema não presume alíquota.
"""

from apps.herd import services as herd
from apps.livestock import services as livestock_services
from apps.livestock.models import Lot
from apps.purchases import services as compras

from . import catalogo as cat
from .cadastros import sortear
from .rebanho import adotar_lote, planejar, raca_sorteada
from .util import D, decimal_entre, dias, fator_de_preco, q2

#: Pesos dos meses da safra (jul → jun) em que cada perfil mais compra.
MESES_PASTO = [3, 3, 6, 10, 12, 12, 12, 10, 8, 5, 4, 3]
MESES_CONFINAMENTO = [12, 12, 12, 8, 4, 2, 2, 3, 5, 8, 12, 12]

CATEGORIAS_POR_PERFIL = {
    cat.RECRIA: (
        [cat.CAT_DESM_M, cat.CAT_M13, cat.CAT_DESM_F, cat.CAT_F13],
        [55, 30, 10, 5],
    ),
    cat.ENGORDA: (
        [cat.CAT_M25, cat.CAT_M13, cat.CAT_F25, cat.CAT_F13],
        [55, 30, 10, 5],
    ),
    cat.CONFINAMENTO: ([cat.CAT_M25, cat.CAT_F25, cat.CAT_M13], [80, 10, 10]),
}
CABECAS_POR_PERFIL = {
    cat.RECRIA: (40, 140),
    cat.ENGORDA: (45, 150),
    cat.CONFINAMENTO: (80, 200),
}


def agendar_compras(ctx):
    """Sorteia as datas das compras de cada fazenda em cada safra."""
    rnd = ctx.rnd
    for safra in ctx.safras:
        for f in cat.FAZENDAS:
            if not f.peso_de_compra:
                continue
            n = max(1, round(f.peso_de_compra * D("0.42") * ctx.escala))
            pesos = MESES_CONFINAMENTO if f.perfil == cat.CONFINAMENTO else MESES_PASTO
            for _ in range(n):
                mes = rnd.choices(range(12), weights=pesos)[0]
                inicio_do_mes = _mes_da_safra(safra, mes)
                ctx.agendar(
                    inicio_do_mes + dias(rnd.randint(0, 27)), "compra", fazenda=f.code
                )
    # Reposição de touros: duas compras por ano em cada fazenda de cria.
    for f in cat.FAZENDAS:
        if f.perfil != cat.CRIA:
            continue
        for safra in ctx.safras:
            for _ in range(max(1, round(D("1.5") * ctx.escala))):
                ctx.agendar(
                    _mes_da_safra(safra, rnd.randint(0, 11)) + dias(rnd.randint(0, 24)),
                    "compra_touros",
                    fazenda=f.code,
                )


def _mes_da_safra(safra, indice):
    from .util import mes_mais

    return mes_mais(safra.start_date, indice)


def _condicao_de_compra(ctx):
    nomes = ["À vista", "15 dias", "30 dias", "Parcelado em 30, 60 e 90 dias"]
    nome = ctx.rnd.choices(nomes, weights=[25, 15, 35, 25])[0]
    return ctx.condicoes.get(nome)


def montar_dados_da_compra(ctx, data, categoria, cabecas):
    """Valores digitados de uma compra: peso, preço, frete, comissão, tributo."""
    rnd = ctx.rnd
    peso_base, preco_kg = cat.PRECOS[categoria]
    peso_medio = peso_base * decimal_entre(rnd, "0.93", "1.07")
    peso_total = q2(peso_medio * cabecas)
    valor = q2(
        peso_total
        * preco_kg
        * fator_de_preco(data)
        * D("0.95")
        * decimal_entre(rnd, "0.95", "1.06")
    )
    dados = {
        "date": data,
        "head_count": cabecas,
        "total_weight_kg": peso_total,
        "animal_value": valor,
        "freight_value": q2(valor * decimal_entre(rnd, "0.008", "0.020", 1000)),
        "commission_value": q2(valor * D("0.01")) if rnd.random() < 0.45 else 0,
        "tax_value": q2(valor * D("0.0035")) if rnd.random() < 0.20 else 0,
        "payment_condition": _condicao_de_compra(ctx),
    }
    if rnd.random() < 0.75:
        dados["entry_yield_percent"] = decimal_entre(rnd, "48", "53", 10)
    if rnd.random() < 0.08:
        dados["partnership"] = (
            "Parceria 50/50 com " + sortear(ctx, "produtor").name[:60]
        )
    return dados, peso_medio


def h_compra(ctx, data, *, fazenda):
    rnd = ctx.rnd
    obj = ctx.fazendas[fazenda]
    perfil = ctx.perfil[fazenda]
    nomes, pesos = CATEGORIAS_POR_PERFIL[perfil]
    categoria = rnd.choices(nomes, weights=pesos)[0]
    minimo, maximo = CABECAS_POR_PERFIL[perfil]
    cabecas = rnd.randint(minimo, maximo)
    dados, peso_medio = montar_dados_da_compra(ctx, data, categoria, cabecas)

    compra = ctx.tentar(
        "compra_criada",
        compras.criar_compra,
        usuario=ctx.admin,
        seller=sortear(ctx, "produtor"),
        destination_farm=obj,
        category=ctx.categorias[categoria],
        notes="Compra negociada por telefone e confirmada no escritório.",
        **dados,
    )
    if compra is None:
        return
    compra = ctx.tentar("compra", compras.confirmar_compra, compra, usuario=ctx.admin)
    if compra is None or compra.lot is None:
        return
    ctx.stats["cabecas_compradas"] += cabecas

    lote = Lot.objects.get(pk=compra.lot_id)
    lote.breed = raca_sorteada(ctx)
    if perfil == cat.CONFINAMENTO:
        lote.regime = "CONFINAMENTO"
    livestock_services.editar_lote(lote, usuario=ctx.admin)

    plano, destino, gmd = {
        cat.RECRIA: (
            "RECRIA",
            "VENDA" if "Fêmeas" in categoria else "ENGORDA",
            decimal_entre(rnd, "0.60", "0.95"),
        ),
        cat.ENGORDA: ("ENGORDA", None, decimal_entre(rnd, "0.80", "1.15")),
        cat.CONFINAMENTO: ("CONFINAMENTO", None, decimal_entre(rnd, "1.30", "1.75")),
    }[perfil]
    sim = adotar_lote(
        ctx, lote, categoria=categoria, plano=plano, peso0=peso_medio, gmd=gmd
    )
    ctx.tentar(
        "pesagem",
        herd.registrar_pesagem,
        date=data,
        farm=obj,
        lot=lote,
        reason="COMPRA",
        head_count=cabecas,
        total_weight_kg=dados["total_weight_kg"],
        usuario=ctx.admin,
    )
    planejar(ctx, sim, destino=destino)


def h_compra_touros(ctx, data, *, fazenda):
    sim = ctx.touros.get(fazenda)
    if sim is None:
        return
    rnd = ctx.rnd
    cabecas = rnd.randint(2, 6)
    dados, _ = montar_dados_da_compra(ctx, data, cat.CAT_TOURO, cabecas)
    dados["entry_yield_percent"] = None
    ctx.stats["_touros"] += 1
    compra = ctx.tentar(
        "compra_criada",
        compras.criar_compra,
        usuario=ctx.admin,
        seller=sortear(ctx, "produtor"),
        destination_farm=ctx.fazendas[fazenda],
        category=ctx.categorias[cat.CAT_TOURO],
        lot=sim.lote,
        notes="Touros PO para reposição, com exame andrológico.",
        **dados,
    )
    if compra is not None:
        ctx.tentar("compra", compras.confirmar_compra, compra, usuario=ctx.admin)
