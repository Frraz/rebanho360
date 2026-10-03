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


def pode_aprovar_acessos(user) -> bool:
    """Decidir pedidos de acesso: `ADMIN` e `GESTOR` (pendência #41, respondida
    pelo cliente em 2026-10-03). Quem aprova não ganha com isso o resto da
    gestão de usuários — editar, redefinir senha e excluir seguem do `ADMIN`."""
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.role in (Role.ADMIN, Role.GESTOR) or user.is_superuser)
    )


class AprovaAcessosMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_aprovar_acessos(self.request.user)
