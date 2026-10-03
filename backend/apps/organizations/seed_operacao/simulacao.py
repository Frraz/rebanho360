"""O laço principal: monta a agenda e executa os eventos em ordem de data.

O que fica na fila no começo são os eventos que não dependem de nada (saldo
inicial, custos do mês, compras, operações de compra, calendário da cria). Os
demais — pesagem, morte, evolução, transferência, venda — nascem do plano de
cada lote enquanto a simulação anda.
"""

import datetime

from . import catalogo as cat
from .ciclo import agendar_ops, h_op
from .compras import agendar_compras, h_compra, h_compra_touros
from .cria import (
    h_ciclo_reprodutivo,
    h_descarte,
    h_desmama,
    h_nascimento,
    h_setup_nascimentos,
)
from .custos import (
    agendar_meses,
    h_custo_de_entrada,
    h_custos_mes,
    h_nutricao_confinamento,
    h_uso_maquinas,
)
from .rebanho import (
    h_evoluir,
    h_morte,
    h_pesar,
    h_saldo_inicial,
    h_transferir,
    h_vender,
)

HANDLERS = {
    "saldo_inicial": h_saldo_inicial,
    "custos_mes": h_custos_mes,
    "uso_maquinas": h_uso_maquinas,
    "compra": h_compra,
    "compra_touros": h_compra_touros,
    "op": h_op,
    "setup_nascimentos": h_setup_nascimentos,
    "nascimento": h_nascimento,
    "desmama": h_desmama,
    "descarte": h_descarte,
    "ciclo_reprodutivo": h_ciclo_reprodutivo,
    "pesar": h_pesar,
    "morte": h_morte,
    "evoluir": h_evoluir,
    "transferir": h_transferir,
    "vender": h_vender,
    "custo_de_entrada": h_custo_de_entrada,
    "nutricao_confinamento": h_nutricao_confinamento,
}


def montar_agenda(ctx):
    # O saldo inicial entra primeiro: tudo mais depende de haver rebanho.
    for f in cat.FAZENDAS:
        ctx.agendar(ctx.inicio, "saldo_inicial", fazenda=f.code)
    agendar_meses(ctx)
    agendar_compras(ctx)
    agendar_ops(ctx)

    rnd = ctx.rnd
    for f in cat.FAZENDAS:
        if f.perfil != cat.CRIA:
            continue
        for safra in ctx.safras:
            ano = safra.start_date.year
            ctx.agendar(datetime.date(ano, 8, 1), "setup_nascimentos", fazenda=f.code)
            # Descarte de matrizes: depois da desmama (agosto) e antes da monta (março).
            ctx.agendar(
                datetime.date(ano, 8, rnd.randint(10, 25)), "descarte", fazenda=f.code
            )
            ctx.agendar(
                datetime.date(ano + 1, 3, rnd.randint(10, 25)),
                "descarte",
                fazenda=f.code,
            )


def rodar(ctx):
    """Executa a fila até esvaziar. Imprime uma linha por mês simulado."""
    mes_atual = None
    while (evento := ctx.proximo()) is not None:
        if evento.data > ctx.cutoff:
            continue
        chave = (evento.data.year, evento.data.month)
        if chave != mes_atual:
            if mes_atual is not None:
                ctx.log(_linha_do_mes(ctx, mes_atual))
            mes_atual = chave
        HANDLERS[evento.tipo](ctx, evento.data, **evento.dados)
    if mes_atual is not None:
        ctx.log(_linha_do_mes(ctx, mes_atual))


def _linha_do_mes(ctx, chave):
    return (
        f"  {chave[1]:02d}/{chave[0]}: {ctx.stats['lotes']} lotes · "
        f"{ctx.stats['cabecas_compradas']} cab. compradas · "
        f"{ctx.stats['cabecas_vendidas']} cab. vendidas · "
        f"{ctx.pendentes} eventos na fila"
    )
