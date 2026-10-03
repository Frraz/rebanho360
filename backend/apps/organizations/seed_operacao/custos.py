"""Custos da fazenda e uso de máquinas.

Custo **indireto** (sem lote) mensal, por fazenda e centro, proporcional ao
rebanho que a fazenda tinha — é o que o sistema rateia entre os lotes. Custo
**direto** no lote: sanidade de entrada e dieta de confinamento.
"""

from apps.costs.services import registrar_custo
from apps.herd import services as herd
from apps.infrastructure import services as infra

from . import catalogo as cat
from .rebanho import saldo_total
from .util import D, decimal_entre, dias, fim_do_mes, mes_mais, q2


def agendar_meses(ctx):
    """Um evento de custo e um de máquinas por mês, no último dia do mês."""
    mes = ctx.inicio.replace(day=1)
    while mes <= ctx.cutoff:
        quando = min(fim_do_mes(mes), ctx.cutoff)
        ctx.agendar(quando, "custos_mes", mes=mes)
        ctx.agendar(quando, "uso_maquinas", mes=mes)
        mes = mes_mais(mes, 1)


def h_custos_mes(ctx, data, *, mes):
    rnd = ctx.rnd
    meio = mes + dias(14)
    meses_desde_o_inicio = (
        (mes.year - ctx.inicio.year) * 12 + mes.month - ctx.inicio.month
    )
    inflacao = 1 + D("0.0035") * meses_desde_o_inicio
    for codigo, fazenda in ctx.fazendas.items():
        cabecas = herd.saldo(farm=fazenda, until=meio)["head_count"]
        if cabecas <= 0:
            continue
        for nome, (por_mil, classe, descricao) in cat.CENTROS.items():
            if rnd.random() < 0.10:
                continue  # mês sem lançamento neste centro
            valor = q2(
                por_mil
                * D(cabecas)
                / 1000
                * inflacao
                * decimal_entre(rnd, "0.8", "1.25")
            )
            lancamento = mes + dias(rnd.randint(1, 26))
            if valor <= 0 or lancamento > ctx.cutoff:
                continue
            ctx.tentar(
                "custo",
                registrar_custo,
                date=lancamento,
                farm=fazenda,
                cost_center=ctx.centros[nome],
                cost_class=ctx.classes[classe],
                amount=valor,
                description=f"{descricao} — {lancamento:%m/%Y}",
                usuario=ctx.admin,
            )


def h_custo_de_entrada(ctx, data, *, lote):
    """Vacina, vermífugo e brinco: custo direto no lote, por cabeça."""
    sim = ctx.lotes[lote]
    cabecas = saldo_total(sim)
    if cabecas <= 0:
        return
    for nome, por_cabeca, descricao in cat.CUSTOS_DE_ENTRADA:
        ctx.tentar(
            "custo_direto",
            registrar_custo,
            date=data,
            farm=sim.fazenda,
            cost_center=ctx.centros[nome],
            cost_class=ctx.classes["CUSTEIO"],
            amount=q2(por_cabeca * cabecas * decimal_entre(ctx.rnd, "0.9", "1.15")),
            description=f"{descricao} — lote {sim.lote.code}",
            lot=sim.lote,
            usuario=ctx.admin,
        )


def h_nutricao_confinamento(ctx, data, *, lote):
    """Dieta de confinamento, lançada a cada 30 dias como custo direto do lote."""
    sim = ctx.lotes[lote]
    cabecas = saldo_total(sim)
    if cabecas <= 0:
        return
    limite = sim.saida_prevista
    periodo = 30
    if limite and data > limite:
        return
    valor = q2(D(cabecas) * periodo * decimal_entre(ctx.rnd, "10.5", "13.8"))
    ctx.tentar(
        "custo_direto",
        registrar_custo,
        date=data,
        farm=sim.fazenda,
        cost_center=ctx.centros["NUTRIÇÃO"],
        cost_class=ctx.classes["CUSTEIO"],
        amount=valor,
        description=f"Dieta de confinamento — lote {sim.lote.code} ({data:%m/%Y})",
        lot=sim.lote,
        usuario=ctx.admin,
    )
    ctx.agendar(data + dias(periodo), "nutricao_confinamento", lote=lote)


def h_uso_maquinas(ctx, data, *, mes):
    rnd = ctx.rnd
    for maquina in ctx.maquinas:
        for _ in range(rnd.randint(1, 3)):
            quando = mes + dias(rnd.randint(0, 27))
            if quando > ctx.cutoff:
                continue
            horas = decimal_entre(rnd, "2.5", "11", 10)
            usa_diesel = maquina.kind != "IMPLEMENTO"
            litros = (
                q2(horas * decimal_entre(rnd, "8", "14", 10)) if usa_diesel else None
            )
            ctx.tentar(
                "uso_maquina",
                infra.registrar_uso,
                usuario=ctx.admin,
                machine=maquina,
                date=quando,
                hours=horas,
                fuel_liters=litros,
                fuel_cost=(
                    q2(litros * decimal_entre(rnd, "5.9", "6.6", 100))
                    if litros
                    else None
                ),
                maintenance_cost=(
                    q2(decimal_entre(rnd, "180", "4800", 1))
                    if rnd.random() < 0.12
                    else None
                ),
                notes="",
            )
