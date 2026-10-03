"""O ciclo de compra: compromisso → viagem → recebimento → romaneio → acerto.

Cada operação (`OP-…`) avança até onde a data permite, como na vida real:
as recentes ficam em negociação, programadas ou em viagem; as antigas fecham
o acerto, geram as compras (e com elas o lote, os custos e os títulos) e boa
parte é encerrada. Uma fração fica propositalmente parada em "acerto" (alguém
esqueceu de aprovar) e outra é cancelada, para as telas mostrarem esses estados.

O sistema **não rateia** nada sozinho: tributo, desconto, adiantamento e a
distribuição entre itens são digitados, como o usuário faria. A distribuição
entre itens usa a sugestão do sistema, que é o que o botão "sugerir" da tela faz.
"""

from apps.herd import services as herd
from apps.livestock import services as livestock_services
from apps.livestock.models import Lot
from apps.procurement import (
    closing,
    commitments,
    grading,
    receivings,
    settlement,
    trips,
)

from . import catalogo as cat
from .cadastros import sortear
from .rebanho import adotar_lote, planejar, raca_sorteada
from .util import D, arroba_em, decimal_entre, dias, inteiro_proporcional, mes_mais, q2

#: classe de carcaça, faixa de preço, fração dos animais, fator de peso de carcaça
CLASSES = [
    ("UNIFORME", 5, 22, D("1.04")),
    ("MEDIANA", 4, 50, D("1.00")),
    ("ESCASSA", 3, 17, D("0.95")),
    ("MAGRO", 2, 7, D("0.88")),
    ("LESAO", 1, 4, D("0.90")),
]
FAIXAS = [D("0.80"), D("0.88"), D("0.92"), D("1.00"), D("1.00")]
#: categoria → peso vivo médio previsto
PESO_PREVISTO = {
    cat.CAT_M25: D("488"),
    cat.CAT_M13: D("335"),
    cat.CAT_F25: D("395"),
    cat.CAT_F13: D("290"),
}


def agendar_ops(ctx):
    rnd = ctx.rnd
    for safra in ctx.safras:
        n = max(1, round(21 * ctx.escala))
        for _ in range(n):
            mes = rnd.choices(
                range(12), weights=[4, 4, 7, 10, 11, 11, 11, 9, 8, 6, 5, 4]
            )[0]
            ctx.agendar(
                mes_mais(safra.start_date, mes) + dias(rnd.randint(0, 27)), "op"
            )
    # Operações recentes, para as telas mostrarem todas as etapas do ciclo
    # (aprovada, programada, em viagem, recebida, em acerto).
    for atras in (2, 7, 12, 18, 27):
        ctx.agendar(ctx.cutoff - dias(atras), "op")


def _itens(ctx, data, n_itens):
    rnd = ctx.rnd
    topo = arroba_em(data) * decimal_entre(rnd, "0.97", "1.03")
    categorias = rnd.choices(
        [cat.CAT_M25, cat.CAT_M13, cat.CAT_F25], weights=[65, 25, 10], k=n_itens
    )
    itens = []
    for categoria in categorias:
        peso = PESO_PREVISTO[categoria]
        itens.append(
            {
                "category": ctx.categorias[categoria],
                "head_count": rnd.randint(35, 110),
                "avg_weight_kg": peso,
                "price_basis": "ARROBA",
                **{
                    f"price_band_{n}": q2(topo * f)
                    for n, f in enumerate(FAIXAS, start=1)
                },
                "expected_arrobas": q2(peso * D("0.52") / 15),
                "expected_band": 4,
            }
        )
    return itens


def _compradores(ctx, acerto_dia):
    rnd = ctx.rnd
    escolhidos = rnd.sample(ctx.parceiros["comissionado"], k=rnd.choice([1, 1, 2]))
    resultado = []
    for p in escolhidos:
        tipo = rnd.choices(["PERCENTUAL", "POR_CABECA", "VALOR"], weights=[60, 25, 15])[
            0
        ]
        valor = {
            "PERCENTUAL": decimal_entre(rnd, "1.0", "1.8", 10),
            "POR_CABECA": decimal_entre(rnd, "18", "28", 10),
            "VALOR": decimal_entre(rnd, "2500", "6000", 1),
        }[tipo]
        resultado.append(
            {
                "partner": p,
                "type": tipo,
                "value": valor,
                "extra_amount": 0,
                "due_date": acerto_dia + dias(rnd.randint(15, 35)),
            }
        )
    return resultado


def h_op(ctx, data):
    """Uma operação de compra, levada até onde a data permite."""
    rnd = ctx.rnd
    perfil = rnd.choices(
        [cat.ENGORDA, cat.CONFINAMENTO, cat.RECRIA], weights=[60, 25, 15]
    )[0]
    from .rebanho import escolher_fazenda

    fazenda = escolher_fazenda(ctx, perfil)
    n_itens = rnd.choices([1, 2, 3], weights=[55, 33, 12])[0]
    itens = _itens(ctx, data, n_itens)

    # Calendário da operação, definido de antemão (vencimentos dependem dele).
    retirada = data + dias(rnd.randint(3, 9))
    recebimento = retirada + dias(rnd.randint(1, 3))
    acerto_dia = recebimento + dias(rnd.randint(4, 14))
    idade = (ctx.cutoff - data).days
    condicao = ctx.condicoes.get(
        rnd.choices(
            ["15 dias", "30 dias", "Parcelado em 30, 60 e 90 dias"],
            weights=[30, 45, 25],
        )[0]
    )

    compradores = _compradores(ctx, acerto_dia)
    comp = ctx.tentar(
        "op_criada",
        commitments.criar_compromisso,
        usuario=ctx.admin,
        itens=itens,
        compradores=compradores,
        date=data,
        seller=sortear(ctx, "produtor"),
        destination_farm=fazenda,
        payment_condition=condicao,
        pickup_date=retirada,
        slaughter_date=retirada + dias(rnd.randint(8, 16)),
        trucks=max(1, sum(i["head_count"] for i in itens) // 45),
        distance_km=rnd.randint(90, 520),
        origin_property=sortear(ctx, "produtor").name[:80],
        origin_city="Região de "
        + rnd.choice(["Araguaína", "Redenção", "Água Boa", "Barra do Garças"]),
        notes="Negociado pelo comprador de gado e aprovado pela gestão.",
    )
    if comp is None:
        return
    comp = ctx.tentar(
        "op_aprovada", commitments.aprovar_compromisso, comp, usuario=ctx.gestor
    )
    if comp is None:
        return
    ctx.stats["ops"] += 1

    if idade > 30 and rnd.random() < 0.04:
        ctx.tentar(
            "op_cancelada",
            commitments.excluir_compromisso,
            comp,
            usuario=ctx.gestor,
            motivo="Negociação desfeita: o vendedor vendeu o lote para outro comprador.",
        )
        return
    if retirada > ctx.cutoff:
        return  # programada, ainda sem viagem
    if idade > 120 and rnd.random() < 0.03:
        return  # aprovada e esquecida

    lista = list(comp.items.order_by("number"))
    # Uma viagem leva todos os itens; as grandes dividem em duas.
    grupos = [lista]
    if (
        len(lista) >= 2
        and sum(i.head_count for i in lista) > 130
        and rnd.random() < 0.6
    ):
        grupos = [lista[:1], lista[1:]]
    viagens = []
    for k, grupo in enumerate(grupos):
        viagem = _viagem(ctx, comp, grupo, retirada + dias(k), acerto_dia)
        if viagem is None:
            return
        viagens.append(viagem)
    if recebimento > ctx.cutoff:
        return  # em viagem

    for k, viagem in enumerate(viagens):
        quando = recebimento + dias(k)
        if quando > ctx.cutoff:
            return
        if not _recebimento(ctx, viagem, quando):
            return
    if acerto_dia > ctx.cutoff:
        return  # recebido, ainda sem acerto

    for item in lista:
        _romaneio(ctx, item)
    acerto = ctx.tentar(
        "acerto_criado",
        closing.criar_acerto,
        usuario=ctx.admin,
        compromisso=comp,
        date=acerto_dia,
        notes="Acerto conferido com o romaneio do frigorífico.",
    )
    if acerto is None:
        return
    _linhas_do_acerto(ctx, comp, acerto, acerto_dia)
    _distribuir(ctx, comp, acerto)
    if idade > 20 and rnd.random() < 0.10:
        return  # acerto em andamento: falta alguém aprovar
    aprovado = ctx.tentar(
        "acerto_aprovado", closing.aprovar_acerto, acerto, usuario=ctx.gestor
    )
    if aprovado is None:
        return
    if rnd.random() < 0.6:
        calculo = settlement.calcular_acerto(comp)
        ctx.tentar(
            "notas_fiscais",
            closing.registrar_notas,
            aprovado,
            [
                {
                    "number": f"{rnd.randint(1000, 999999)}",
                    "series": "1",
                    "issue_date": acerto_dia,
                    "amount": calculo.valor_dos_animais,
                }
            ],
            usuario=ctx.admin,
        )
    if idade > 40 and rnd.random() < 0.7:
        ctx.tentar(
            "op_encerrada",
            commitments.encerrar_operacao,
            comp,
            usuario=ctx.gestor,
            observacao="Operação conferida e paga.",
        )
    _adotar_lotes(ctx, lista, perfil)


# --------------------------------------------------------------------------
# Etapas
# --------------------------------------------------------------------------


def _viagem(ctx, comp, itens, retirada, acerto_dia):
    rnd = ctx.rnd
    cargas = []
    for item in itens:
        embarcadas = item.head_count - (rnd.randint(0, 2) if rnd.random() < 0.3 else 0)
        cargas.append(
            {
                "item": item,
                "planned_qty": item.head_count,
                "shipped_qty": embarcadas,
                "origin_weight_kg": q2(
                    D(embarcadas)
                    * item.avg_weight_kg
                    * decimal_entre(rnd, "0.99", "1.01", 1000)
                ),
            }
        )
    cabecas = sum(c["shipped_qty"] for c in cargas)
    por_viagem = rnd.random() < 0.25
    tarifa = (
        decimal_entre(rnd, "3200", "6800", 1)
        if por_viagem
        else decimal_entre(rnd, "55", "78", 10)
    )
    previsto = tarifa if por_viagem else tarifa * cabecas
    return ctx.tentar(
        "viagem",
        trips.criar_viagem,
        usuario=ctx.admin,
        compromisso=comp,
        pickup_date=retirada,
        carrier=sortear_transportador(ctx),
        driver_name=rnd.choice(
            ["Raimundo Alves", "Jonas Pereira", "Valdir Sousa", "Edmilson Costa"]
        ),
        vehicle="Carreta boiadeira 3 eixos",
        vehicle_plate=f"{rnd.choice(['QKD', 'OLP', 'MXS', 'PQR'])}{rnd.randint(1, 9)}{rnd.choice('ABCDEFGH')}{rnd.randint(10, 99)}",
        adf_number=f"{rnd.randint(100000, 999999)}",
        freight_criterion="POR_VIAGEM" if por_viagem else "POR_CABECA",
        freight_rate=tarifa,
        freight_actual=q2(previsto * decimal_entre(rnd, "0.94", "1.08")),
        freight_due_date=acerto_dia + dias(rnd.randint(8, 25)),
        cargas=cargas,
    )


def sortear_transportador(ctx):
    return ctx.rnd.choice(ctx.parceiros["transportador"])


def _recebimento(ctx, viagem, quando):
    rnd = ctx.rnd
    quebra = decimal_entre(rnd, "1.2", "6.2", 10)
    linhas = []
    for carga in viagem.loads.all():
        recebidas = carga.shipped_qty - (1 if rnd.random() < 0.08 else 0)
        linha = {
            "load": carga,
            "received_qty": recebidas,
            "received_weight_kg": q2(
                carga.origin_weight_kg
                * (1 - quebra / 100)
                * recebidas
                / carga.shipped_qty
            ),
        }
        if recebidas != carga.shipped_qty:
            linha["occurrence"] = (
                "1 animal morto durante o transporte; laudo do veterinário anexado."
            )
        linhas.append(linha)
    return ctx.tentar(
        "recebimento",
        receivings.criar_recebimento,
        usuario=ctx.admin,
        viagem=viagem,
        date=quando,
        linhas=linhas,
        trip_loss_percent=quebra,
        notes="Quebra de viagem digitada pelo conferente.",
    )


def _romaneio(ctx, item):
    rnd = ctx.rnd
    recebidas = sum(
        linha.received_qty
        for carga in item.loads.all()
        for linha in carga.received_lines.all()
    )
    if recebidas <= 0:
        return
    pesos = [max(1, p + rnd.randint(-4, 4)) for _, _, p, _ in CLASSES]
    cabecas = inteiro_proporcional(recebidas, pesos)
    rendimento = decimal_entre(rnd, "0.50", "0.54")
    linhas = []
    for (classe, faixa, _, fator), n in zip(CLASSES, cabecas, strict=False):
        if n <= 0:
            continue
        linha = {
            "carcass_class": ctx.carcass[classe],
            "band": faixa,
            "head_count": n,
            "carcass_weight_kg": q2(D(n) * item.avg_weight_kg * rendimento * fator),
        }
        if classe == "LESAO":
            linha["discount_percent"] = D("10")
        linhas.append(linha)
    ctx.tentar("romaneio", grading.registrar_romaneio, item, linhas, usuario=ctx.admin)


def _linhas_do_acerto(ctx, comp, acerto, acerto_dia):
    """Tributos, taxas, descontos e adiantamentos — todos com valor digitado."""
    rnd = ctx.rnd
    calculo = settlement.calcular_acerto(comp)
    valor = calculo.valor_dos_itens
    cabecas = calculo.cabecas_recebidas
    if not valor or valor <= 0 or cabecas <= 0:
        return
    tributos = ctx.tributos
    receita = next(p for p in ctx.parceiros["favorecido"] if "Receita" in p.name)
    fundepec = next(p for p in ctx.parceiros["favorecido"] if "Fundepec" in p.name)
    adapec = next(p for p in ctx.parceiros["favorecido"] if "Agência" in p.name)
    sefaz = next(p for p in ctx.parceiros["favorecido"] if "Secretaria" in p.name)

    def linha(nome, valor_linha, favorecido=None, **extra):
        tipo = tributos.get(nome)
        if tipo is None or valor_linha <= 0:
            return None
        return {
            "tax_type": tipo,
            "amount": q2(valor_linha),
            "payee": favorecido,
            "due_date": acerto_dia + dias(rnd.randint(12, 30)) if favorecido else None,
            **extra,
        }

    taxa = D("1.5")
    linhas = [
        linha(
            "Funrural",
            valor * taxa / 100,
            receita,
            rate_percent=taxa,
            base_amount=q2(valor),
        ),
        linha("Fundepec", D("7.50") * cabecas, fundepec),
        linha("GTA", D("5.20") * cabecas, adapec),
    ]
    if rnd.random() < 0.25:
        linhas.append(
            linha("ICMS", valor * decimal_entre(rnd, "0.8", "1.5", 10) / 100, sefaz)
        )
    if rnd.random() < 0.15:
        linhas.append(
            linha("Desconto", valor * decimal_entre(rnd, "0.5", "1.5", 10) / 100)
        )
    if rnd.random() < 0.20:
        linhas.append(
            linha(
                "Adiantamento",
                valor * decimal_entre(rnd, "10", "25", 10) / 100,
                reference="Adiantamento no pedido",
            )
        )
    if rnd.random() < 0.15:
        linhas.append(
            linha(
                rnd.choice(["Crédito GR-3", "Incentivo Precoce"]),
                valor * decimal_entre(rnd, "0.3", "1.0", 10) / 100,
            )
        )
    linhas = [x for x in linhas if x]
    ctx.tentar(
        "acerto_linhas", closing.registrar_linhas, acerto, linhas, usuario=ctx.admin
    )


def _distribuir(ctx, comp, acerto):
    """Com mais de um item recebido o usuário reparte frete, comissão, tributo
    e desconto entre eles. O seed usa a sugestão do sistema, como o botão da tela."""
    calculo = settlement.calcular_acerto(comp)
    recebidos = [i for i in calculo.itens if i.recebido]
    if len(recebidos) < 2:
        return
    sugestao = settlement.sugerir_distribuicao(
        recebidos,
        frete=calculo.frete,
        comissao=calculo.comissao_total,
        tributos=calculo.tributos,
        descontos=calculo.descontos,
        abatimentos=calculo.adiantamentos + calculo.creditos,
    )
    ctx.tentar(
        "acerto_distribuicao",
        closing.registrar_distribuicao,
        acerto,
        [{"item": i.item.pk, **sugestao[i.item.pk]} for i in recebidos],
        usuario=ctx.admin,
    )


def _adotar_lotes(ctx, itens, perfil):
    """O acerto aprovado cria as compras e os lotes: o seed passa a conduzi-los."""
    rnd = ctx.rnd
    for item in itens:
        item.refresh_from_db()
        compra = getattr(item, "purchase", None)
        if compra is None or compra.lot_id is None:
            continue
        lote = Lot.objects.get(pk=compra.lot_id)
        lote.breed = raca_sorteada(ctx)
        if perfil == cat.CONFINAMENTO:
            lote.regime = "CONFINAMENTO"
        livestock_services.editar_lote(lote, usuario=ctx.admin)
        peso = (
            compra.total_weight_kg / compra.head_count
            if compra.total_weight_kg
            else item.avg_weight_kg
        )
        categoria = item.category.name
        # Gado já pesado para abate: sai mais cedo do que o de recria.
        plano = "CONFINAMENTO" if perfil == cat.CONFINAMENTO else "ENGORDA"
        gmd = (
            decimal_entre(rnd, "1.30", "1.75")
            if perfil == cat.CONFINAMENTO
            else decimal_entre(rnd, "0.80", "1.15")
        )
        sim = adotar_lote(
            ctx, lote, categoria=categoria, plano=plano, peso0=peso, gmd=gmd
        )
        sim.data0 = compra.date
        if compra.total_weight_kg:
            ctx.tentar(
                "pesagem",
                herd.registrar_pesagem,
                date=compra.date,
                farm=lote.farm,
                lot=lote,
                reason="COMPRA",
                head_count=compra.head_count,
                total_weight_kg=compra.total_weight_kg,
                usuario=ctx.admin,
            )
        planejar(
            ctx,
            sim,
            dias_saida=(
                rnd.randint(70, 150)
                if categoria == cat.CAT_M25 and perfil != cat.CONFINAMENTO
                else None
            ),
        )
