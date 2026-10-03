"""Quem pode o quê em vendas. Confirmar exige o mesmo papel que lançar —
docs/regras-negocio/04#validações (item 7: `sales.confirm_sale`)."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_LANCAM_VENDA = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)


def pode_lancar_venda(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_LANCAM_VENDA


def pode_confirmar_venda(user) -> bool:
    return pode_lancar_venda(user)


class LancaVendaMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_lancar_venda(self.request.user)
