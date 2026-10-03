from django.conf import settings
from django.db import models

from apps.core.managers import ScopedManager
from apps.core.reversible import ReversibleModel, Status


class TimestampedModel(models.Model):
    """`created_at`/`updated_at` automáticos, para cadastros simples."""

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        abstract = True


class CounterTestModel(models.Model):
    """Existe só para testar `ReversibleModel`/`editar`/`excluir` (F0-10)."""

    total = models.IntegerField(default=0)

    class Meta:
        app_label = "core"


class ReversibleTestModel(ReversibleModel):
    """Efeito: soma `amount` em `counter.total`. Desfazer: subtrai."""

    counter = models.ForeignKey(
        CounterTestModel, on_delete=models.CASCADE, related_name="entries"
    )
    amount = models.IntegerField()
    blocked = models.BooleanField(default=False)
    fails_on_undo = models.BooleanField(default=False)

    class Meta:
        app_label = "core"

    def aplicar_efeitos(self, *, usuario):
        self.counter.total += self.amount
        self.counter.save(update_fields=["total"])

    def desfazer_efeitos(self, *, usuario):
        if self.fails_on_undo:
            raise RuntimeError("Falha simulada, para testar atomicidade da cascata.")
        self.counter.total -= self.amount
        self.counter.save(update_fields=["total"])

    def dependentes(self):
        return list(self.dependents.filter(status=Status.CONFIRMADA))

    def bloqueios(self):
        return ["motivo de teste"] if self.blocked else []


class DependentTestModel(ReversibleModel):
    """Dependente de `ReversibleTestModel`, para testar cascata (F0-10)."""

    parent = models.ForeignKey(
        ReversibleTestModel, on_delete=models.CASCADE, related_name="dependents"
    )
    counter = models.ForeignKey(
        CounterTestModel, on_delete=models.CASCADE, related_name="dependent_entries"
    )
    amount = models.IntegerField()

    class Meta:
        app_label = "core"

    def aplicar_efeitos(self, *, usuario):
        self.counter.total += self.amount
        self.counter.save(update_fields=["total"])

    def desfazer_efeitos(self, *, usuario):
        self.counter.total -= self.amount
        self.counter.save(update_fields=["total"])


class ScopeTestModel(models.Model):
    """Existe só para testar `ScopedManager`/`ScopedQuerysetMixin` (F0-06).

    `Farm` nasce vazio nesta fase (ver apps/properties/models.py) só para
    este propósito; a entidade real chega na F1-02.
    """

    SCOPE_FARM_FIELD = "farm"

    farm = models.ForeignKey(
        "properties.Farm", on_delete=models.CASCADE, related_name="+"
    )
    label = models.CharField(max_length=50, blank=True)

    objects = ScopedManager()

    class Meta:
        app_label = "core"


class SoftDeletableModel(models.Model):
    """Exclusão lógica para cadastros simples (sem efeitos a desfazer).

    Para registros transacionais (Purchase, Sale, HerdMovement, CostEntry,
    Weighing), use `apps.core.reversible.ReversibleModel` em vez deste —
    aqueles exigem o fluxo completo de análise de impacto e auditoria.
    """

    is_deleted = models.BooleanField("Excluído", default=False)
    deleted_at = models.DateTimeField("Excluído em", null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Excluído por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )

    class Meta:
        abstract = True
