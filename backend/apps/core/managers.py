from django.db import models


class ScopedQuerySet(models.QuerySet):
    def for_user(self, user):
        """Filtra pelo escopo de fazenda do usuário.

        `ADMIN` e `GESTOR` enxergam tudo, por definição do papel (ADR 0003).
        Qualquer outro papel só vê o que `UserFarmAccess` concede.

        Toda listagem deve usar `for_user()`, nunca `.all()` — é o que torna
        o vazamento entre fazendas improvável por construção, não por
        lembrança. O campo de fazenda é lido em `farm_field_name` (padrão
        `"farm"`), para servir modelos cujo campo se chama diferente.
        """
        if user.has_broad_access:
            return self.all()

        farm_field = getattr(self.model, "SCOPE_FARM_FIELD", "farm")
        accessible_ids = user.farm_access.values_list("farm_id", flat=True)
        return self.filter(**{f"{farm_field}__in": accessible_ids})


class ScopedManager(models.Manager.from_queryset(ScopedQuerySet)):
    """Manager base para todo modelo com fazenda.

    Uso:
        class Lot(models.Model):
            farm = models.ForeignKey("properties.Farm", ...)
            objects = ScopedManager()

    Listar sempre com `Model.objects.for_user(request.user)`.
    """
