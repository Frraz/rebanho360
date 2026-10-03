"""Leitura dos cadastros comerciais."""

from apps.commercial.models import (
    CarcassClass,
    CommissionRule,
    PaymentCondition,
    TaxType,
)


def listar_classes():
    return CarcassClass.objects.all()


def classes_ativas():
    return CarcassClass.objects.filter(is_active=True)


def listar_tipos():
    return TaxType.objects.all()


def tipos_ativos():
    return TaxType.objects.filter(is_active=True)


def listar_regras_de_comissao():
    return CommissionRule.objects.select_related("commissioned", "category")


def listar_condicoes():
    return PaymentCondition.objects.all()


def condicoes_ativas():
    return PaymentCondition.objects.filter(is_active=True)
