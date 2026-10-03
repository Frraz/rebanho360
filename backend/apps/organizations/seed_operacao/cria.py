"""A cria: nascimentos, desmama, descarte de matrizes e o ciclo reprodutivo.

Segue o calendário real de uma fazenda de cria no Brasil Central: estação de
monta de novembro a fevereiro, parição de agosto a novembro, desmama de abril
a junho do ano seguinte. Os nascidos entram no razão como `NASCIMENTO` (e é do
razão que o relatório de reprodução lê os nascidos); o que o produtor digita no
ciclo reprodutivo são as fêmeas expostas, as prenhes e os desmamados.
"""

import datetime

from apps.herd import services as herd
from apps.reproduction import services as reproducao

from . import catalogo as cat
from .rebanho import abrir_lote, h_evoluir, h_vender, planejar, raca_sorteada
from .util import D, decimal_entre, dias, inteiro_proporcional, q2


def h_setup_nascimentos(ctx, data, *, fazenda):
    """1º de agosto: abre os lotes de bezerros da safra e agenda a parição,
    a desmama e o registro do ciclo reprodutivo."""
    rnd = ctx.rnd
    matrizes = ctx.matrizes.get(fazenda)
    if matrizes is None:
        return
    obj = ctx.fazendas[fazenda]
    total_matrizes = herd.saldo(
        lot=matrizes.lote, category=ctx.categorias[cat.CAT_MATRIZ]
    )["head_count"]
    nascer = int(D(total_matrizes) * decimal_entre(rnd, "0.78", "0.86"))
    if nascer <= 0:
        return

    desmama = datetime.date(data.year + 1, 4, 25) + dias(rnd.randint(0, 55))
    lotes = {}
    for sexo, categoria in (("M", cat.CAT_BEZ_M), ("F", cat.CAT_BEZ_F)):
        sim = abrir_lote(
            ctx,
            obj,
            data=data,
            categoria=categoria,
            plano="BEZERROS",
            peso0=D("33"),
            gmd=D("0.78"),
            raca=raca_sorteada(ctx),
            notes=f"Bezerros nascidos na safra {ctx.safra_da_data(data).name}.",
        )
        sim.saida_prevista = desmama
        lotes[sexo] = sim
        planejar(ctx, sim)
        ctx.agendar(
            data + dias(115),
            "pesar",
            lote=sim.lote.pk,
            motivo="CONFERENCIA",
            encadear=True,
        )
        ctx.agendar(desmama, "desmama", lote=sim.lote.pk, sexo=sexo)

    # Quatorze lançamentos de parição, mais concentrados em setembro e outubro.
    eventos = 14
    partes = inteiro_proporcional(nascer, [rnd.randint(1, 6) for _ in range(eventos)])
    abertura = data + dias(rnd.randint(3, 9))
    for i, quantidade in enumerate(partes):
        quando = abertura + dias(int(i * 112 / eventos) + rnd.randint(0, 5))
        machos = int(D(quantidade) * decimal_entre(rnd, "0.46", "0.54") + D("0.5"))
        ctx.agendar(
            quando,
            "nascimento",
            fazenda=fazenda,
            lote_m=lotes["M"].lote.pk,
            lote_f=lotes["F"].lote.pk,
            machos=machos,
            femeas=quantidade - machos,
        )

    # O ciclo reprodutivo da safra é registrado perto do fim dela.
    fim = next(s for s in ctx.safras if s.start_date <= data <= s.end_date)
    ctx.agendar(
        min(fim.end_date - dias(4), ctx.cutoff),
        "ciclo_reprodutivo",
        fazenda=fazenda,
        safra=fim.pk,
    )


def h_nascimento(ctx, data, *, fazenda, lote_m, lote_f, machos, femeas):
    for pk, quantidade, categoria in (
        (lote_m, machos, cat.CAT_BEZ_M),
        (lote_f, femeas, cat.CAT_BEZ_F),
    ):
        if quantidade <= 0:
            continue
        sim = ctx.lotes[pk]
        peso = decimal_entre(ctx.rnd, "31", "36", 10)
        movimento = ctx.tentar(
            "nascimento",
            herd.registrar_movimento,
            type="NASCIMENTO",
            date=data,
            quantity=quantidade,
            total_weight_kg=q2(peso * quantidade),
            usuario=ctx.admin,
            destination_farm=sim.fazenda,
            destination_lot=sim.lote,
            destination_category=ctx.categorias[categoria],
            notes="Parição registrada pelo vaqueiro.",
        )
        if movimento:
            ctx.nascidos[(sim.fazenda.pk, sim.lote.season_id)] += quantidade


def h_desmama(ctx, data, *, lote, sexo):
    sim = ctx.lotes[lote]
    quantidade = h_evoluir(ctx, data, lote=lote)
    if not quantidade:
        return
    ctx.desmamados[(sim.fazenda.pk, sim.lote.season_id)] += quantidade
    rnd = ctx.rnd
    # A partir daqui o lote deixa de ser "bezerros": pesa e engorda como recria.
    sim.peso0 = sim.peso0 + (data - sim.data0).days * sim.gmd
    sim.data0 = data
    sim.plano = "RECRIA"
    sim.gmd = decimal_entre(rnd, "0.62", "0.92")
    sim.saida_prevista = None
    if sexo == "M":
        if rnd.random() < 0.9:
            ctx.agendar(
                data + dias(rnd.randint(15, 60)),
                "transferir",
                lote=lote,
                destino=cat.RECRIA,
            )
        else:
            ctx.agendar(
                data + dias(rnd.randint(20, 45)),
                "vender",
                lote=lote,
                tipo="VENDA",
                fracao=100,
            )
    else:
        # Metade das bezerras segue como reposição; o resto é vendido.
        ctx.agendar(
            data + dias(rnd.randint(20, 50)),
            "vender",
            lote=lote,
            tipo="VENDA",
            fracao=55,
        )
        planejar(ctx, sim, destino="FICAR", base=data)


def h_descarte(ctx, data, *, fazenda):
    """Descarte de matrizes velhas ou vazias: venda de animal vivo."""
    sim = ctx.matrizes.get(fazenda)
    if sim is None:
        return
    disponivel = herd.saldo(lot=sim.lote, category=ctx.categorias[cat.CAT_MATRIZ])[
        "head_count"
    ]
    quantidade = int(D(disponivel) * decimal_entre(ctx.rnd, "0.035", "0.06"))
    if quantidade > 0:
        h_vender(ctx, data, lote=sim.lote.pk, tipo="VENDA", cabecas=quantidade)


def h_ciclo_reprodutivo(ctx, data, *, fazenda, safra):
    rnd = ctx.rnd
    obj = ctx.fazendas[fazenda]
    season = next(s for s in ctx.safras if s.pk == safra)
    matrizes = herd.saldo(
        farm=obj, category=ctx.categorias[cat.CAT_MATRIZ], until=data
    )["head_count"]
    novilhas = (
        herd.saldo(farm=obj, category=ctx.categorias[cat.CAT_F25], until=data)[
            "head_count"
        ]
        + herd.saldo(farm=obj, category=ctx.categorias[cat.CAT_F13], until=data)[
            "head_count"
        ]
    )
    if matrizes <= 0:
        return

    def parte(total, minimo, maximo):
        return int(D(total) * decimal_entre(rnd, minimo, maximo))

    primiparas = parte(matrizes, "0.15", "0.20")
    vacas = matrizes - primiparas - parte(matrizes, "0.02", "0.04")
    desafio = parte(novilhas, "0.10", "0.20")
    novilhas_exp = parte(novilhas, "0.55", "0.80") - desafio
    novilhas_exp = max(novilhas_exp, 0)
    grupos = {
        "heifers": (novilhas_exp, parte(novilhas_exp, "0.70", "0.80")),
        "challenge_heifers": (desafio, parte(desafio, "0.55", "0.68")),
        "primiparous": (primiparas, parte(primiparas, "0.74", "0.84")),
        "cows": (vacas, parte(vacas, "0.82", "0.90")),
    }
    expostas = sum(e for e, _ in grupos.values())
    prenhes = sum(p for _, p in grupos.values())
    inseminadas = parte(expostas, "0.55", "0.72")
    por_ia = min(parte(inseminadas, "0.52", "0.60"), prenhes)
    por_touro = min(parte(prenhes, "0.40", "0.55"), prenhes - por_ia)
    dados = {
        "breeding_months": rnd.randint(3, 5),
        "females_total": matrizes + novilhas,
        "females_over_18m": matrizes,
        "inseminated": inseminadas,
        "pregnant_by_ai": por_ia,
        "pregnant_by_bull": por_touro,
        "weaned_calves": ctx.desmamados.get((obj.pk, safra), 0),
        "notes": "Estação de monta de novembro a fevereiro, com IATF no início.",
    }
    for prefixo, (exp, pre) in grupos.items():
        dados[f"{prefixo}_exposed"] = exp
        dados[f"{prefixo}_pregnant"] = pre
    ctx.tentar(
        "ciclo_reprodutivo",
        reproducao.registrar_ciclo,
        usuario=ctx.admin,
        farm=obj,
        season=season,
        **dados,
    )
