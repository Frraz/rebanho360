"""Parâmetros de relatório vindos da web (querystring ou POST).

Fica fora de `views.py` porque a geração de PDF (`apps.documents`) usa o
mesmo parsing — e serviço não importa de view.
"""

import datetime
from decimal import Decimal, InvalidOperation

from apps.core import context as ctx
from apps.livestock.models import Lot
from apps.reports import services

#: Situações do lote que o relatório filtra (`Lot.Status`).
SITUACOES_DO_LOTE = (("ABERTO", "Abertos"), ("ENCERRADO", "Encerrados"))


def _data(valor):
    try:
        return datetime.date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def _decimal(valor):
    try:
        return Decimal(valor.replace(",", ".")) if valor else None
    except InvalidOperation:
        return None


def parametros_do_relatorio(user, slug, origem) -> dict:
    """Só repassa o que o relatório declara aceitar (`services.PARAMETROS`).
    `origem` é a querystring (tela) ou o POST (geração de PDF). Lote fora do
    escopo do usuário simplesmente não existe."""
    extras = {}
    aceitos = services.PARAMETROS.get(slug, ())
    if "de" in aceitos:
        extras["start"] = _data(origem.get("de"))
    if "ate" in aceitos:
        extras["end"] = _data(origem.get("ate"))
    if "lote" in aceitos and origem.get("lote", "").isdigit():
        extras["lote"] = Lot.objects.for_user(user).filter(pk=origem["lote"]).first()
    if "acerto" in aceitos and origem.get("acerto", "").isdigit():
        # Fora do escopo de fazenda do usuário, o acerto simplesmente não existe.
        from apps.procurement.models import Settlement

        extras["acerto"] = (
            Settlement.objects.for_user(user).filter(pk=origem["acerto"]).first()
        )
    if "comprador" in aceitos and origem.get("comprador", "").isdigit():
        extras["comprador"] = (
            compradores_do_escopo(user).filter(pk=origem["comprador"]).first()
        )
    if "fazenda" in aceitos and origem.get("fazenda", "").isdigit():
        # Fazenda fora do escopo do usuário simplesmente não existe.
        extras["fazenda"] = (
            ctx.available_farms(user).filter(pk=origem["fazenda"]).first()
        )
    if "situacao" in aceitos and origem.get("situacao") in dict(SITUACOES_DO_LOTE):
        extras["situacao"] = origem["situacao"]
    if "preco_arroba" in aceitos:
        extras["preco_arroba"] = _decimal(origem.get("preco_arroba", ""))
    if "rendimento_entrada" in aceitos:
        extras["rendimento_entrada"] = _decimal(origem.get("rendimento_entrada", ""))
    return extras


def compradores_do_escopo(user):
    """Quem aparece como comprador (comissionado) em algum compromisso que o
    usuário enxerga — a lista do filtro "Comprador" dos relatórios."""
    from apps.partners.models import Partner
    from apps.procurement.models import Commission, Commitment

    return Partner.objects.filter(
        pk__in=Commission.objects.filter(
            commitment__in=Commitment.objects.for_user(user), payee__isnull=False
        ).values("payee")
    ).order_by("name")


def campos_de_selecao(user, slug, origem) -> list[dict]:
    """Os filtros de escolha (comprador, fazenda, situação) que o relatório
    aceita, prontos para a tela montar os `<select>`."""
    aceitos = services.PARAMETROS.get(slug, ())
    campos = []
    if "comprador" in aceitos:
        campos.append(
            {
                "nome": "comprador",
                "rotulo": "Comprador",
                "vazio": "Todos os compradores",
                "opcoes": [(p.pk, p.name) for p in compradores_do_escopo(user)],
                "valor": origem.get("comprador", ""),
            }
        )
    if "fazenda" in aceitos:
        campos.append(
            {
                "nome": "fazenda",
                "rotulo": "Fazenda",
                "vazio": "A do topo da tela",
                "opcoes": [(f.pk, f.name) for f in ctx.available_farms(user)],
                "valor": origem.get("fazenda", ""),
            }
        )
    if "situacao" in aceitos:
        campos.append(
            {
                "nome": "situacao",
                "rotulo": "Situação do lote",
                "vazio": "Todos os lotes",
                "opcoes": list(SITUACOES_DO_LOTE),
                "valor": origem.get("situacao", ""),
            }
        )
    return campos
