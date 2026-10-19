"""Classificação operacional solicitada em atualizacao/8.md, item 13."""

from django.db import models

from apps.core.exceptions import BusinessError


class OperationType(models.TextChoices):
    PROPRIO = "PROPRIO", "Gado Próprio"
    PARCERIA = "PARCERIA", "Parceria"
    BOI_BRASIL = "BOI_BRASIL", "Parceria Boi Brasil"


def validar_tipo(valor):
    # Vazio preserva registros históricos e importação legada. Formulários novos exigem tipo.
    if valor and valor not in OperationType.values:
        raise BusinessError("Tipo de operação inválido.")
