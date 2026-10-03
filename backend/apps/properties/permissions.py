"""Quem pode o quê, e sobre qual fazenda."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_GERENCIAM_FAZENDA = (Role.ADMIN, Role.GESTOR)


def pode_gerenciar_fazenda(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_GERENCIAM_FAZENDA


class GerenciaFazendaMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Cadastro de fazenda/pasto é de `ADMIN`/`GESTOR` — quem só lança no
    campo usa a fazenda já cadastrada, não a cria."""

    def test_func(self):
        return pode_gerenciar_fazenda(self.request.user)
