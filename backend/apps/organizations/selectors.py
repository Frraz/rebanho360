"""Leitura. Consultas e agregações."""

from apps.organizations.models import BusinessUnit, Company, Season


def listar_empresas():
    return Company.objects.all()


def listar_unidades():
    return BusinessUnit.objects.select_related("company").all()


def listar_safras():
    return Season.objects.select_related("company").all()
