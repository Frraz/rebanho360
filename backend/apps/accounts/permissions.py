"""Quem pode o quê, e sobre qual fazenda."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role


def pode_gerenciar_usuarios(user) -> bool:
    """Gerenciar usuários é do `ADMIN`. `is_superuser` também (quem criou o
    sistema com `createsuperuser` tem papel padrão de consulta). `is_staff`
    sozinho não basta — nunca se confia só nele (docs/seguranca/01)."""
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.role == Role.ADMIN or user.is_superuser)
    )


class GerenciaUsuariosMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Sem permissão, 403 para quem está logado e login para quem não está."""

    def test_func(self):
        return pode_gerenciar_usuarios(self.request.user)
