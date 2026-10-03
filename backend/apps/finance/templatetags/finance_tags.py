from django.template import Library
from django.utils.html import format_html, format_html_join

from apps.core.reversible import Status
from apps.finance.models import PaymentStatus

register = Library()

#: situação do pagamento → classe do selo. Cor nunca sozinha: o selo tem texto
#: e marcador (docs/ux/01#status-e-cor).
CLASSES = {
    PaymentStatus.A_PAGAR: "badge-rascunho",
    PaymentStatus.PROGRAMADO: "badge-editada",
    PaymentStatus.APROVADO: "badge-editada",
    PaymentStatus.PARCIAL: "badge-pendencia",
    PaymentStatus.PAGO: "badge-confirmada",
}


@register.simple_tag
def titulo_selos(titulo, hoje=None):
    """Situação do título + "Vencido", quando for o caso. Cancelado vem
    riscado, como toda exclusão no sistema."""
    if titulo.status == Status.EXCLUIDA:
        return format_html('<span class="badge-excluida">Cancelado</span>')
    selos = [(CLASSES[titulo.payment_status], titulo.situacao_rotulo)]
    if titulo.vencido(hoje):
        selos.append(("badge-erro", "Vencido"))
    return format_html_join(" ", '<span class="{}">{}</span>', selos)


@register.simple_tag
def baixa_selo(pagamento):
    if pagamento.status == Status.EXCLUIDA:
        return format_html('<span class="badge-excluida">Desfeita</span>')
    return format_html('<span class="badge-confirmada">{}</span>', pagamento.verbo)
