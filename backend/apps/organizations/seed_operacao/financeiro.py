"""Financeiro: programar, aprovar e baixar os títulos que as compras e as
vendas geraram — pelas mesmas regras de produção.

- A programação usa a data de **hoje** (o sistema recusa data no passado); a
  baixa leva a data histórica do pagamento.
- Quem aprova (o gestor) **não** é quem paga (o administrador).
- Frete, comissão e tributo nascem sem favorecido: informa-se pelo serviço
  de edição do título, com motivo, como o usuário faria.
- O que venceu há pouco fica em aberto, uma parte do resto fica vencida e
  algumas baixas são parciais — o dashboard financeiro precisa disso.
"""

from apps.core.reversible import Status
from apps.finance import services as financeiro
from apps.finance.models import Invoice, PaymentMethod, PaymentStatus

from . import catalogo as cat
from .util import D, dias, q2

METODOS = [
    PaymentMethod.PIX,
    PaymentMethod.TED,
    PaymentMethod.BOLETO,
    PaymentMethod.CHEQUE,
]
PESO_DOS_METODOS = [45, 30, 20, 5]


def _favorecido(ctx, titulo):
    rnd = ctx.rnd
    componente = titulo.component
    if componente == "FRETE":
        return rnd.choice(ctx.parceiros["transportador"])
    if componente == "COMISSAO":
        return rnd.choice(ctx.parceiros["comissionado"])
    return rnd.choice(ctx.parceiros["favorecido"])


def pagar_e_receber(ctx):
    rnd = ctx.rnd
    hoje = ctx.hoje
    titulos = (
        Invoice.objects.filter(
            farm__code__startswith=cat.PREFIXO, status=Status.CONFIRMADA
        )
        .select_related("farm")
        .order_by("due_date", "id")
    )
    for titulo in list(titulos):
        if titulo.payment_status not in (PaymentStatus.A_PAGAR, PaymentStatus.PARCIAL):
            continue
        idade = (hoje - titulo.due_date).days
        pagar = titulo.direction == "PAGAR"

        if pagar and titulo.payee_id is None:
            editado = ctx.tentar(
                "titulo_favorecido",
                financeiro.editar_titulo,
                titulo,
                {"payee": _favorecido(ctx, titulo)},
                usuario=ctx.admin,
                motivo="Favorecido informado pelo financeiro.",
            )
            if editado is None:
                continue
            titulo = editado

        if idade < 12:
            # Vence em breve: parte já está programada ou aprovada, o resto aberto.
            if pagar and rnd.random() < 0.5:
                _programar(ctx, titulo, aprovar=rnd.random() < 0.5)
            continue
        if rnd.random() < 0.07:
            continue  # ficou vencido de propósito

        if pagar:
            titulo = _programar(ctx, titulo, aprovar=True)
            if titulo is None:
                continue
        _baixar(ctx, titulo)


def _programar(ctx, titulo, *, aprovar):
    programado = ctx.tentar(
        "titulo_programado",
        financeiro.programar_titulo,
        titulo,
        usuario=ctx.admin,
        data=ctx.hoje,
    )
    if programado is None or not aprovar:
        return programado
    return ctx.tentar(
        "titulo_aprovado", financeiro.aprovar_titulo, programado, usuario=ctx.gestor
    )


def _baixar(ctx, titulo):
    rnd = ctx.rnd
    parcial = rnd.random() < 0.12
    valor = q2(titulo.amount * D("0.6")) if parcial else titulo.amount
    data = max(
        titulo.issue_date,
        min(titulo.due_date + dias(rnd.randint(-2, 6)), ctx.hoje),
    )
    metodo = rnd.choices(METODOS, weights=PESO_DOS_METODOS)[0]
    baixa = ctx.tentar(
        "baixa",
        financeiro.baixar_titulo,
        titulo,
        usuario=ctx.admin,
        date=data,
        amount=valor,
        method=metodo,
        document=f"DOC-{titulo.pk:06d}",
    )
    # Uma parte das baixas parciais é completada depois.
    if baixa is not None and parcial and rnd.random() < 0.4:
        titulo.refresh_from_db()
        ctx.tentar(
            "baixa",
            financeiro.baixar_titulo,
            titulo,
            usuario=ctx.admin,
            date=min(data + dias(rnd.randint(5, 20)), ctx.hoje),
            amount=q2(titulo.amount - valor),
            method=metodo,
            document=f"DOC-{titulo.pk:06d}-B",
        )
