"""Quem exporta. Pendência #44: palpite do desenvolvimento, uma linha por papel.

Exportar em massa é o jeito mais fácil de levar dado para fora, então a tela
não é de todo mundo: `CAMPO` e `CONSULTA` ficam de fora. Além do papel, **cada
conjunto de dados tem a própria regra** (`catalog.Conjunto.permitido`): quem não
vê o financeiro na tela também não o exporta, e usuários e auditoria são do
`ADMIN`. O escopo por fazenda vale sempre.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_EXPORTAM = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO, Role.FINANCEIRO)


def pode_exportar(user) -> bool:
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.role in PAPEIS_QUE_EXPORTAM or user.is_superuser)
    )


class ExportaMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Sem permissão, 403 para quem está logado e login para quem não está."""

    def test_func(self):
        return pode_exportar(self.request.user)
