"""Parâmetros de relatório vindos da web (querystring ou POST).

Fica fora de `views.py` porque a geração de PDF (`apps.documents`) usa o
mesmo parsing — e serviço não importa de view.
"""

import datetime
from decimal import Decimal, InvalidOperation

from apps.livestock.models import Lot
from apps.reports import services


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
    if "rendimento_entrada" in aceitos:
        extras["rendimento_entrada"] = _decimal(origem.get("rendimento_entrada", ""))
    return extras
