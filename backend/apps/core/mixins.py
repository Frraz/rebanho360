"""Mixins de view compartilhados entre apps.

`ScopedQuerysetMixin` é o que garante, nas views genéricas baseadas em
classe, que um registro fora do escopo do usuário devolve 404 — nunca
403, que confirmaria a existência do registro (ADR 0003).
"""

from django.contrib.auth.mixins import LoginRequiredMixin


class ScopedQuerysetMixin(LoginRequiredMixin):
    """Para `ListView`/`DetailView`/`UpdateView` de modelo com `ScopedManager`.

    `get_object()` do Django busca dentro de `get_queryset()`; ao restringir
    o queryset pelo escopo, um registro de outra fazenda simplesmente não
    está lá — `Http404` nasce sozinho, sem checagem extra de permissão.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.for_user(self.request.user)
