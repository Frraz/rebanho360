"""Leitura. Consultas e agregações."""

from apps.properties.models import Farm, Paddock


def listar_fazendas():
    return Farm.objects.select_related("business_unit").all()


def listar_pastos_para(user):
    return Paddock.objects.for_user(user).select_related("farm")
