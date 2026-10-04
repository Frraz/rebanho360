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


def filtrar_parceiros(termo: str = "", papel: str = ""):
    """A listagem de Parceiros: texto (nome, documento, cidade) e papel. Sem
    nenhum dos dois devolve todos — o campo vazio não é "não achei nada"."""
    qs = Partner.objects.prefetch_related("roles").order_by("name")
    termo = (termo or "").strip()
    if termo:
        qs = qs.filter(
            Q(name__icontains=termo)
            | Q(document__icontains=termo)
            | Q(city__icontains=termo)
        )
    if papel:
        # Um parceiro tem no máximo uma linha por papel (UNIQUE): sem duplicata.
        qs = qs.filter(roles__role=papel)
    return qs
