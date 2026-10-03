"""Quem pode o quê em custos."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_LANCAM_CUSTO = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)
PAPEIS_QUE_GERENCIAM_CENTRO = (Role.ADMIN, Role.GESTOR)


def pode_lancar_custo(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_LANCAM_CUSTO


def pode_gerenciar_centro_de_custo(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_GERENCIAM_CENTRO


class LancaCustoMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_lancar_custo(self.request.user)


class GerenciaCentroDeCustoMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_gerenciar_centro_de_custo(self.request.user)
