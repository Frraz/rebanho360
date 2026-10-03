"""Quem pode o quê em compras. Confirmar exige o mesmo papel que lançar —
ver docs/regras-negocio/03#validações (item 8)."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_LANCAM_COMPRA = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)


def pode_lancar_compra(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_LANCAM_COMPRA


def pode_confirmar_compra(user) -> bool:
    return pode_lancar_compra(user)


class LancaCompraMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_lancar_compra(self.request.user)
