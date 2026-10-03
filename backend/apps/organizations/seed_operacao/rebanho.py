"""A vida dos lotes: pesagem, morte, evolução, transferência, venda e a cria.

Cada lote ganha um **plano** na hora em que nasce (por compra, nascimento,
transferência ou saldo inicial): o seed agenda os eventos futuros dele na fila
do `Contexto`, e o laço principal os executa em ordem de data. Cada evento
reconfere o saldo no razão antes de agir — o plano é intenção, o razão é a
verdade.

Todo lançamento passa pelos serviços reais (`herd`, `sales`, `livestock`).
"""

import datetime
import math
from decimal import Decimal

from apps.herd import services as herd
from apps.livestock import services as livestock_services
from apps.livestock.models import Lot, LotStatus
from apps.sales import services as vendas

from . import catalogo as cat
from .contexto import LoteSim
from .util import (
    D,
    arroba_em,
    decimal_entre,
    dias,
    fator_de_preco,
    fim_do_mes,
    inteiro_proporcional,
    q2,
)

CAUSAS = [
    ("DOENCA", "Doença respiratória", 25),
    ("PARASITOSE", "Verminose e carrapato", 12),
    ("TIMPANISMO", "Timpanismo", 12),
    ("INTOXICACAO", "Intoxicação por planta tóxica", 6),
    ("PICADA_DE_COBRA", "Picada de cobra", 12),
    ("ONCA", "Predação por onça", 4),
    ("ACIDENTE", "Acidente no manejo", 10),
    ("RAIO", "Descarga elétrica (raio)", 4),
    ("OUTRA", "Causa não identificada", 15),
]

#: Fazendas onde a mortalidade concentra (aparece no relatório por causa).
FAZENDAS_DE_RISCO = {"S3-CAB", "S3-IPE"}

FATOR_SAZONAL = {
    11: D("1.20"), 12: D("1.25"), 1: D("1.25"), 2: D("1.20"), 3: D("1.15"),
    4: D("1.00"), 5: D("0.75"), 6: D("0.55"), 7: D("0.40"), 8: D("0.35"),
    9: D("0.40"), 10: D("0.80"),
}  # fmt: skip


# --------------------------------------------------------------------------
# Peso, preço e sorteios
# --------------------------------------------------------------------------


def peso_em(sim: LoteSim, data: datetime.date) -> Decimal:
    """Peso médio (kg/cab) na data: peso de entrada + ganho com a sazonalidade
    do pasto (águas ganham, seca segura). Confinamento e cria não variam."""
    peso = sim.peso0
    d = sim.data0
    sazonal = sim.plano not in ("CONFINAMENTO", "BEZERROS")
    while d < data:
        fim = min(data, fim_do_mes(d) + dias(1))
        fator = FATOR_SAZONAL[d.month] if sazonal else D("1")
        peso += sim.gmd * fator * D((fim - d).days)
        d = fim
    return peso


def raca_sorteada(ctx):
    nomes = {r.name: r for r in ctx.racas}
    opcoes = ["Nelore", "Nelore PO", "Angus x Nelore", "Tabapuã", "Brahman"]
    pesos = [70, 5, 15, 5, 5]
    nome = ctx.rnd.choices(opcoes, weights=pesos)[0]
    return nomes.get(nome) or ctx.racas[0]


def escolher_fazenda(ctx, perfil):
    candidatas = [f for f in cat.FAZENDAS if f.perfil == perfil]
    escolhida = ctx.rnd.choices(
        candidatas, weights=[max(f.peso_de_compra, 1) for f in candidatas]
    )[0]
    return ctx.fazendas[escolhida.code]


def saldo_total(sim: LoteSim) -> int:
    return herd.saldo(lot=sim.lote)["head_count"]


# --------------------------------------------------------------------------
# Abrir lote
# --------------------------------------------------------------------------


def abrir_lote(
    ctx,
    fazenda,
    *,
    data,
    categoria,
    plano,
    peso0,
    gmd,
    origem=None,
    regime="PASTO",
    raca=None,
    notes="",
) -> LoteSim:
    lote = Lot(
        farm=fazenda,
        season=ctx.safra_da_data(data),
        entry_date=data,
        regime=regime,
        breed=raca,
        origin_partner=origem,
        notes=notes,
    )
    livestock_services.criar_lote(lote, usuario=ctx.admin)
    sim = LoteSim(
        lote=lote,
        fazenda=fazenda,
        categoria=categoria,
        perfil=ctx.perfil[fazenda.code],
        data0=data,
        peso0=peso0,
        gmd=gmd,
        plano=plano,
    )
    ctx.lotes[lote.pk] = sim
    ctx.stats["lotes"] += 1
    return sim


def adotar_lote(ctx, lote, *, categoria, plano, peso0, gmd) -> LoteSim:
    """Registra no seed um lote que o sistema já criou (o da compra)."""
    sim = LoteSim(
        lote=lote,
        fazenda=lote.farm,
        categoria=categoria,
        perfil=ctx.perfil[lote.farm.code],
        data0=lote.entry_date,
        peso0=peso0,
        gmd=gmd,
        plano=plano,
    )
    ctx.lotes[lote.pk] = sim
    ctx.stats["lotes"] += 1
    return sim


def encerrar_lote(ctx, sim: LoteSim, data):
    lote = Lot.objects.get(pk=sim.lote.pk)
    if lote.status != LotStatus.ABERTO:
        return
    lote.status = LotStatus.ENCERRADO
    lote.exit_date = data
    ctx.tentar(
        "lote_encerrado", livestock_services.editar_lote, lote, usuario=ctx.admin
    )


# --------------------------------------------------------------------------
# Planos: o que vai acontecer com o lote
# --------------------------------------------------------------------------


def planejar_mortes(ctx, sim, inicio, fim, percentual, cabecas):
    """Mortes esparsas de 1 a 3 cabeças em datas sorteadas dentro do período."""
    rnd = ctx.rnd
    risco = D("2.4") if sim.fazenda.code in FAZENDAS_DE_RISCO else D("1")
    esperadas = D(cabecas) * D(percentual) / 100 * risco
    eventos = int(esperadas / 2)
    if rnd.random() < float(esperadas / 2 - eventos):
        eventos += 1
    if fim <= inicio:
        return
    for _ in range(eventos):
        quando = inicio + dias(rnd.randint(0, (fim - inicio).days))
        ctx.agendar(quando, "morte", lote=sim.lote.pk, quantidade=rnd.randint(1, 3))


def planejar_pesagens(ctx, sim, primeira):
    if sim.sem_pesagem:
        return
    ctx.agendar(
        primeira + dias(ctx.rnd.randint(40, 60)),
        "pesar",
        lote=sim.lote.pk,
        motivo="CONFERENCIA",
        encadear=True,
    )


def planejar(ctx, sim: LoteSim, *, destino=None, dias_saida=None, base=None):
    """Agenda a vida do lote conforme o plano.

    `destino` (só RECRIA): "ENGORDA" transfere os animais prontos para uma
    fazenda de engorda; "VENDA" vende vivos; "FICAR" mantém na fazenda.
    `base` recomeça a contagem dos prazos numa data (a desmama, por exemplo).
    """
    rnd = ctx.rnd
    d0 = base or sim.data0
    cabecas = max(saldo_total(sim), 1)

    if sim.plano in ("ENGORDA", "CONFINAMENTO"):
        ctx.stats["_planos_terminacao"] += 1
        n = ctx.stats["_planos_terminacao"]
        # Casos propositais para os alertas do painel e do relatório.
        if sim.plano == "ENGORDA" and n % 41 == 17:
            sim.sem_pesagem = True
        if n % 23 == 9:
            sim.sem_carcaca = True
        if n % 31 == 4:
            sim.gmd = min(sim.gmd, D("0.30"))  # lote que não rendeu: prejuízo
        confinamento = sim.plano == "CONFINAMENTO"
        if dias_saida is None:
            dias_saida = rnd.randint(88, 128) if confinamento else rnd.randint(190, 290)
        if sim.categoria in (cat.CAT_M13, cat.CAT_F13) and not confinamento:
            ctx.agendar(d0 + dias(int(dias_saida * 0.55)), "evoluir", lote=sim.lote.pk)
            dias_saida += 40
        saida = d0 + dias(dias_saida)
        sim.saida_prevista = saida
        planejar_pesagens(ctx, sim, d0)
        if not sim.sem_pesagem:
            ctx.agendar(
                saida - dias(2),
                "pesar",
                lote=sim.lote.pk,
                motivo="ABATE",
                encadear=False,
            )
        ctx.agendar(d0 + dias(2), "custo_de_entrada", lote=sim.lote.pk)
        if confinamento:
            ctx.agendar(d0 + dias(30), "nutricao_confinamento", lote=sim.lote.pk)
        partes = 1 if rnd.random() < 0.6 else 2
        for i in range(partes):
            ctx.agendar(
                saida + dias(18 * i),
                "vender",
                lote=sim.lote.pk,
                tipo="ABATE",
                fracao=100 if i == partes - 1 else 55,
            )
        planejar_mortes(ctx, sim, d0 + dias(5), saida, D("1.1"), cabecas)

    elif sim.plano == "RECRIA":
        planejar_pesagens(ctx, sim, d0)
        ctx.agendar(d0 + dias(2), "custo_de_entrada", lote=sim.lote.pk)
        t = d0
        categoria = sim.categoria
        destino = destino or "ENGORDA"
        while cat.PROXIMA.get(categoria):
            if categoria == cat.CAT_M25:
                break
            if categoria == cat.CAT_F25 and destino != "FICAR":
                break
            duracao = (
                rnd.randint(250, 330)
                if categoria in (cat.CAT_DESM_M, cat.CAT_DESM_F)
                else rnd.randint(230, 330)
            )
            if categoria == cat.CAT_M13 and dias_saida:
                duracao = dias_saida
            t = t + dias(duracao)
            ctx.agendar(t, "evoluir", lote=sim.lote.pk)
            categoria = cat.PROXIMA[categoria]
        fim = t + dias(rnd.randint(10, 40))
        if destino == "ENGORDA" and categoria in (cat.CAT_M25, cat.CAT_M13):
            ctx.agendar(fim, "transferir", lote=sim.lote.pk, destino="ENGORDA")
        elif destino == "VENDA":
            ctx.agendar(fim, "vender", lote=sim.lote.pk, tipo="VENDA", fracao=100)
        planejar_mortes(ctx, sim, d0 + dias(10), t, D("1.4"), cabecas)

    elif sim.plano == "BEZERROS":
        planejar_mortes(
            ctx,
            sim,
            d0 + dias(20),
            sim.saida_prevista or d0 + dias(240),
            D("2.6"),
            cabecas,
        )

    elif sim.plano == "MATRIZES":
        planejar_pesagens(ctx, sim, d0)
        ctx.agendar(
            d0 + dias(200),
            "pesar",
            lote=sim.lote.pk,
            motivo="CONFERENCIA",
            encadear=False,
        )


# --------------------------------------------------------------------------
# Eventos
# --------------------------------------------------------------------------


def h_pesar(ctx, data, *, lote, motivo, encadear=False):
    sim = ctx.lotes[lote]
    saldo = saldo_total(sim)
    if saldo <= 0:
        return
    media = peso_em(sim, data) * decimal_entre(ctx.rnd, "0.985", "1.015", 1000)
    ctx.tentar(
        "pesagem",
        herd.registrar_pesagem,
        date=data,
        farm=sim.fazenda,
        lot=sim.lote,
        reason=motivo,
        head_count=saldo,
        total_weight_kg=q2(media * saldo),
        usuario=ctx.admin,
    )
    limite = sim.saida_prevista
    if encadear and not (limite and data > limite):
        ctx.agendar(
            data + dias(ctx.rnd.randint(42, 63)),
            "pesar",
            lote=lote,
            motivo="CONFERENCIA",
            encadear=True,
        )


def h_morte(ctx, data, *, lote, quantidade):
    sim = ctx.lotes[lote]
    disponivel = herd.saldo(lot=sim.lote, category=ctx.categorias[sim.categoria])[
        "head_count"
    ]
    quantidade = min(quantidade, disponivel)
    if quantidade <= 0:
        return
    pesos = [p for _, _, p in CAUSAS]
    causa, motivo, _ = ctx.rnd.choices(CAUSAS, weights=pesos)[0]
    if sim.plano == "MATRIZES" and ctx.rnd.random() < 0.25:
        causa, motivo = "PARTO", "Complicação no parto"
    ctx.tentar(
        "morte",
        herd.registrar_movimento,
        type="MORTE",
        date=data,
        quantity=quantidade,
        total_weight_kg=q2(peso_em(sim, data) * quantidade),
        usuario=ctx.admin,
        origin_farm=sim.fazenda,
        origin_lot=sim.lote,
        origin_category=ctx.categorias[sim.categoria],
        reason=motivo,
        death_cause=causa,
    )


def h_evoluir(ctx, data, *, lote):
    sim = ctx.lotes[lote]
    novo = cat.PROXIMA.get(sim.categoria)
    atual = ctx.categorias[sim.categoria]
    quantidade = herd.saldo(lot=sim.lote, category=atual)["head_count"]
    if not novo or quantidade <= 0:
        return
    movimento = ctx.tentar(
        "evolucao",
        herd.registrar_movimento,
        type="EVOLUCAO",
        date=data,
        quantity=quantidade,
        total_weight_kg=q2(peso_em(sim, data) * quantidade),
        usuario=ctx.admin,
        origin_farm=sim.fazenda,
        origin_lot=sim.lote,
        origin_category=atual,
        destination_farm=sim.fazenda,
        destination_lot=sim.lote,
        destination_category=ctx.categorias[novo],
    )
    if movimento:
        sim.categoria = novo
        return quantidade
    return None


def h_transferir(ctx, data, *, lote, destino):
    sim = ctx.lotes[lote]
    atual = ctx.categorias[sim.categoria]
    quantidade = herd.saldo(lot=sim.lote, category=atual)["head_count"]
    if quantidade <= 0:
        return
    perfil_destino = destino
    fazenda_destino = escolher_fazenda(ctx, perfil_destino)
    peso = peso_em(sim, data)
    plano = "ENGORDA" if perfil_destino == cat.ENGORDA else "RECRIA"
    novo = abrir_lote(
        ctx,
        fazenda_destino,
        data=data,
        categoria=sim.categoria,
        plano=plano,
        peso0=peso,
        gmd=decimal_entre(ctx.rnd, "0.80", "1.15"),
        raca=sim.lote.breed,
        notes=f"Transferido do lote {sim.lote.code} ({sim.fazenda.name}).",
    )
    movimento = ctx.tentar(
        "transferencia",
        herd.registrar_movimento,
        type="TRANSFERENCIA",
        date=data,
        quantity=quantidade,
        total_weight_kg=q2(peso * quantidade),
        usuario=ctx.admin,
        origin_farm=sim.fazenda,
        origin_lot=sim.lote,
        origin_category=atual,
        destination_farm=fazenda_destino,
        destination_lot=novo.lote,
        destination_category=atual,
        notes="Transferência entre fazendas do grupo.",
    )
    if not movimento:
        return
    if saldo_total(sim) == 0:
        encerrar_lote(ctx, sim, data)
    if plano == "ENGORDA":
        planejar(ctx, novo, dias_saida=ctx.rnd.randint(140, 230))
    else:
        planejar(ctx, novo, destino="ENGORDA")


def _condicao_de_venda(ctx, tipo):
    if tipo == "ABATE":
        nomes = ["7 dias", "15 dias", "30 dias", "4 dias", "À vista"]
        pesos = [40, 25, 20, 10, 5]
    else:
        nomes = ["À vista", "30 dias", "Parcelado em 30, 60 e 90 dias"]
        pesos = [40, 40, 20]
    return ctx.condicoes.get(ctx.rnd.choices(nomes, weights=pesos)[0])


def h_vender(ctx, data, *, lote, tipo, fracao=100, cabecas=None):
    """Venda de abate (com carcaça e rendimento) ou de animal vivo."""
    sim = ctx.lotes[lote]
    rnd = ctx.rnd
    categoria = ctx.categorias[sim.categoria]
    disponivel = herd.saldo(lot=sim.lote, category=categoria)["head_count"]
    if disponivel <= 0:
        return
    quantidade = cabecas or max(1, math.ceil(disponivel * fracao / 100))
    quantidade = min(quantidade, disponivel)
    vivo = peso_em(sim, data) * quantidade
    comprador = _comprador(ctx, tipo)
    confinamento = sim.perfil == cat.CONFINAMENTO
    dados = dict(
        usuario=ctx.admin,
        date=data,
        type=tipo,
        buyer=comprador,
        farm=sim.fazenda,
        lot=sim.lote,
        category=categoria,
        head_count=quantidade,
        total_weight_kg=q2(vivo),
        sale_form="CONFINAMENTO" if confinamento else "PASTO",
        payment_condition=_condicao_de_venda(ctx, tipo),
    )
    if tipo == "ABATE":
        if rnd.random() < 0.03:
            rendimento = D("44.5")  # fora da faixa de referência: gera alerta
        elif rnd.random() < 0.015:
            rendimento = D("68.5")
        elif confinamento:
            rendimento = decimal_entre(rnd, "52.5", "56.5")
        else:
            rendimento = decimal_entre(rnd, "50.0", "54.0")
        carcaca = vivo * rendimento / 100
        arroba = arroba_em(data) * decimal_entre(rnd, "0.97", "1.04")
        dados["carcass_weight_kg"] = None if sim.sem_carcaca else q2(carcaca)
        dados["total_value"] = q2(carcaca / 15 * arroba)
        if rnd.random() < 0.25 and not sim.sem_carcaca:
            dados["reported_yield_percent"] = q2(rendimento)
        sim.sem_carcaca = False
    else:
        preco_kg = cat.PRECOS.get(sim.categoria, (None, D("11")))[1]
        dados["total_value"] = q2(
            vivo * preco_kg * fator_de_preco(data) * decimal_entre(rnd, "0.97", "1.04")
        )
    venda = ctx.tentar("venda_criada", vendas.criar_venda, **dados)
    if venda is None:
        return
    confirmada = ctx.tentar("venda", vendas.confirmar_venda, venda, usuario=ctx.admin)
    if confirmada is None:
        return
    ctx.stats["cabecas_vendidas"] += quantidade
    if saldo_total(sim) == 0:
        encerrar_lote(ctx, sim, data)


def _comprador(ctx, tipo):
    from .cadastros import sortear

    return sortear(ctx, "frigorifico" if tipo == "ABATE" else "comprador")


# --------------------------------------------------------------------------
# Saldo inicial (1º de julho de 2024)
# --------------------------------------------------------------------------


def _entrada(ctx, sim, tipo, data, quantidade, observacao=""):
    return ctx.tentar(
        "entrada_" + tipo.lower(),
        herd.registrar_movimento,
        type=tipo,
        date=data,
        quantity=quantidade,
        total_weight_kg=q2(sim.peso0 * quantidade),
        usuario=ctx.admin,
        destination_farm=sim.fazenda,
        destination_lot=sim.lote,
        destination_category=ctx.categorias[sim.categoria],
        notes=observacao,
    )


def _lote_inicial(
    ctx, fazenda, categoria, quantidade, *, plano, peso0, gmd, regime="PASTO"
):
    if quantidade <= 0:
        return None
    sim = abrir_lote(
        ctx,
        fazenda,
        data=ctx.inicio,
        categoria=categoria,
        plano=plano,
        peso0=peso0,
        gmd=gmd,
        raca=raca_sorteada(ctx),
        regime=regime,
        notes="Saldo inicial do sistema (inventário de 01/07/2024).",
    )
    if not _entrada(
        ctx, sim, "SALDO_INICIAL", ctx.inicio, quantidade, "Inventário inicial"
    ):
        return None
    return sim


def h_saldo_inicial(ctx, data, *, fazenda):
    f = next(x for x in cat.FAZENDAS if x.code == fazenda)
    obj = ctx.fazendas[fazenda]
    rnd = ctx.rnd
    e = {k: max(1, round(v * ctx.escala)) for k, v in f.estoque.items()}

    if f.perfil == cat.CRIA:
        matrizes = _lote_inicial(
            ctx,
            obj,
            cat.CAT_MATRIZ,
            e["matrizes"],
            plano="MATRIZES",
            peso0=D("455"),
            gmd=D("0.05"),
        )
        touros = _lote_inicial(
            ctx,
            obj,
            cat.CAT_TOURO,
            e["touros"],
            plano="MATRIZES",
            peso0=D("780"),
            gmd=D("0.02"),
        )
        if matrizes:
            ctx.matrizes[fazenda] = matrizes
            ctx.touros[fazenda] = touros
            planejar(ctx, matrizes)
            horizonte = ctx.cutoff
            planejar_mortes(
                ctx,
                matrizes,
                ctx.inicio,
                horizonte,
                D("6.0") * D((horizonte - ctx.inicio).days) / 365,
                e["matrizes"],
            )
        if touros:
            planejar(ctx, touros)
            planejar_mortes(
                ctx,
                touros,
                ctx.inicio,
                ctx.cutoff,
                D("5.0") * D((ctx.cutoff - ctx.inicio).days) / 365,
                e["touros"],
            )
        desm_m = _lote_inicial(
            ctx,
            obj,
            cat.CAT_DESM_M,
            e["desm_m"],
            plano="RECRIA",
            peso0=D("212"),
            gmd=D("0.70"),
        )
        if desm_m:
            ctx.agendar(
                ctx.inicio + dias(rnd.randint(12, 55)),
                "transferir",
                lote=desm_m.lote.pk,
                destino=cat.RECRIA,
            )
            planejar_pesagens(ctx, desm_m, ctx.inicio)
        desm_f = _lote_inicial(
            ctx,
            obj,
            cat.CAT_DESM_F,
            e["desm_f"],
            plano="RECRIA",
            peso0=D("196"),
            gmd=D("0.65"),
        )
        if desm_f:
            ctx.agendar(
                ctx.inicio + dias(rnd.randint(20, 50)),
                "vender",
                lote=desm_f.lote.pk,
                tipo="VENDA",
                fracao=50,
            )
            planejar(ctx, desm_f, destino="FICAR")
        novilhas = _lote_inicial(
            ctx,
            obj,
            cat.CAT_F13,
            e["novilhas"],
            plano="RECRIA",
            peso0=D("292"),
            gmd=D("0.55"),
        )
        if novilhas:
            planejar(ctx, novilhas, destino="FICAR")

    elif f.perfil == cat.RECRIA:
        total = e["cabecas"]
        partes = inteiro_proporcional(total, [4, 4, 2])
        categorias = [cat.CAT_DESM_M, cat.CAT_M13, cat.CAT_M13]
        pesos = [D("225"), D("335"), D("352")]
        for qtd, categoria, peso in zip(partes, categorias, pesos, strict=False):
            sim = _lote_inicial(
                ctx,
                obj,
                categoria,
                qtd,
                plano="RECRIA",
                peso0=peso,
                gmd=decimal_entre(rnd, "0.60", "0.95"),
            )
            if sim:
                planejar(
                    ctx,
                    sim,
                    destino="ENGORDA",
                    dias_saida=(
                        rnd.randint(60, 190) if categoria == cat.CAT_M13 else None
                    ),
                )

    elif f.perfil == cat.ENGORDA:
        total = e["cabecas"]
        partes = inteiro_proporcional(total, [4, 3, 3])
        categorias = [cat.CAT_M25, cat.CAT_M25, cat.CAT_M13]
        pesos = [D("472"), D("455"), D("352")]
        for qtd, categoria, peso in zip(partes, categorias, pesos, strict=False):
            sim = _lote_inicial(
                ctx,
                obj,
                categoria,
                qtd,
                plano="ENGORDA",
                peso0=peso,
                gmd=decimal_entre(rnd, "0.75", "1.15"),
            )
            if sim:
                planejar(
                    ctx,
                    sim,
                    dias_saida=(
                        rnd.randint(35, 190)
                        if categoria == cat.CAT_M25
                        else rnd.randint(110, 240)
                    ),
                )
