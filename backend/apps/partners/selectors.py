"""Leitura. Consultas e agregações."""

from django.db.models import Q

from apps.partners.models import Partner


def listar_parceiros():
    return Partner.objects.prefetch_related("roles")


def buscar_parceiros(termo: str, *, limite: int = 10):
    """Para o combobox com busca (docs/ux/01#autocomplete-nunca-select-gigante):
    nome, documento ou cidade, nunca select gigante."""
    termo = (termo or "").strip()
    if not termo:
        return Partner.objects.none()
    return Partner.objects.filter(
        Q(name__icontains=termo)
        | Q(document__icontains=termo)
        | Q(city__icontains=termo)
    ).order_by("name")[:limite]
