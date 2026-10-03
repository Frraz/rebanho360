"""Quem cadastra o quê no comercial. Ler é de qualquer usuário autenticado;
mudar classificação, tributo e comissão é de `ADMIN` e `GESTOR` — comissão é
dinheiro, e a regra aplicada vira snapshot da operação."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_GERENCIAM_O_COMERCIAL = (Role.ADMIN, Role.GESTOR)


def pode_gerenciar_o_comercial(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_GERENCIAM_O_COMERCIAL


class GerenciaOComercialMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_gerenciar_o_comercial(self.request.user)
