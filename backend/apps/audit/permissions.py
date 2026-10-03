from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role


def pode_ver_auditoria(user) -> bool:
    """Console de auditoria é do `ADMIN`; `GESTOR` entra se
    `AUDIT_CONSOLE_INCLUDE_GESTOR = True` nas settings. A exportação da trilha
    segue a mesma regra."""
    papeis = {Role.ADMIN}
    if getattr(settings, "AUDIT_CONSOLE_INCLUDE_GESTOR", False):
        papeis.add(Role.GESTOR)
    return getattr(user, "role", None) in papeis


class AuditConsoleAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Console de auditoria é do `ADMIN`; `GESTOR` entra se
    `AUDIT_CONSOLE_INCLUDE_GESTOR = True` nas settings."""

    def test_func(self):
        return pode_ver_auditoria(self.request.user)
