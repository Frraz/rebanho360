"""Quem pode o quê."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_GERENCIAM_LIVESTOCK = (Role.ADMIN, Role.GESTOR)
PAPEIS_QUE_GERENCIAM_LOTE = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)


def pode_gerenciar_livestock(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_GERENCIAM_LIVESTOCK


def pode_gerenciar_lote(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_GERENCIAM_LOTE


class GerenciaLivestockMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_gerenciar_livestock(self.request.user)


class GerenciaLoteMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_gerenciar_lote(self.request.user)
