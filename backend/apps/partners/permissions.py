"""Quem pode o quê."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_GERENCIAM_PARCEIRO = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)


def pode_gerenciar_parceiro(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_GERENCIAM_PARCEIRO


class GerenciaParceiroMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_gerenciar_parceiro(self.request.user)
