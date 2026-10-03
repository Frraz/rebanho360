from django.template import Library
from django.utils.html import format_html

from apps.procurement.selectors import Etapa

register = Library()

#: Cor **e** texto **e** marcador (docs/ux/02-design-system.md): o selo nunca fala só por cor.
_CLASSE_DA_ETAPA = {
    Etapa.EM_NEGOCIACAO: "badge-rascunho",
    Etapa.APROVADO: "badge-editada",
    Etapa.PROGRAMADO: "badge-editada",
    Etapa.EM_VIAGEM: "badge-editada",
    Etapa.RECEBIDO: "badge-editada",
    Etapa.EM_ACERTO: "badge-pendencia",
    Etapa.ACERTO_APROVADO: "badge-confirmada",
    Etapa.EXCLUIDO: "badge-excluida",
}

#: Ordem do ciclo, para o indicador de progresso da tela.
ETAPAS_DO_CICLO = (
    Etapa.EM_NEGOCIACAO,
    Etapa.APROVADO,
    Etapa.EM_VIAGEM,
    Etapa.RECEBIDO,
    Etapa.EM_ACERTO,
    Etapa.ACERTO_APROVADO,
)


_CLASSE_DA_SITUACAO = {
    "AGUARDANDO_FINANCEIRO": "badge-pendencia",
    "PAGAMENTO_PROGRAMADO": "badge-editada",
    "PAGO": "badge-confirmada",
    "ENCERRADA": "badge-excluida",
}


@register.simple_tag
def situacao_financeira_selo(situacao):
    """Passo depois do acerto (aguardando financeiro, programado, pago,
    encerrada). Texto e classe: nunca só cor."""
    from apps.procurement.selectors import SituacaoFinanceira

    if not situacao:
        return ""
    return format_html(
        '<span class="{}">{}</span>',
        _CLASSE_DA_SITUACAO[situacao],
        SituacaoFinanceira(situacao).label,
    )


@register.simple_tag
def etapa_selo(etapa):
    etapa = Etapa(etapa)
    return format_html(
        '<span class="{}">{}</span>', _CLASSE_DA_ETAPA[etapa], etapa.label
    )


@register.simple_tag
def progresso_do_ciclo(etapa):
    """Os seis passos do ciclo, com o atual marcado. `PROGRAMADO` é uma volta do
    "aprovado"; `EXCLUIDO` não tem posição."""
    etapa = Etapa(etapa)
    if etapa == Etapa.PROGRAMADO:
        etapa = Etapa.APROVADO
    posicao = ETAPAS_DO_CICLO.index(etapa) if etapa in ETAPAS_DO_CICLO else -1
    return [
        {
            "rotulo": passo.label,
            "feito": i < posicao,
            "atual": i == posicao,
        }
        for i, passo in enumerate(ETAPAS_DO_CICLO)
    ]


@register.filter
def quebra_percentual(valor):
    """`Decimal` em pontos percentuais → "2,00%". `None` → "—"."""
    from decimal import Decimal

    from apps.core.formatting import numero_br

    if valor is None:
        return "—"
    return f"{numero_br(Decimal(valor), 2)}%"


@register.filter
def comparado(valor, tipo):
    """Formata uma célula do previsto × realizado. Sem dado, "—" (regra 3)."""
    from decimal import Decimal

    from apps.core.formatting import dinheiro_br, numero_br

    if valor is None or valor == "":
        return "—"
    if tipo == "dinheiro":
        return dinheiro_br(valor)
    if tipo == "kg":
        return f"{numero_br(Decimal(valor), 0)} kg"
    if tipo == "numero":
        return str(valor)
    if tipo == "data":
        return valor.strftime("%d/%m/%Y")
    return str(valor)
