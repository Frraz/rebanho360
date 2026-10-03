"""Quem pode o quê em Empresa/Unidade/Safra.

Cadastro estrutural, não transacional — mas safra encerrada afeta todo
lançamento do sistema, por isso reabrir é restrito a `ADMIN`
(docs/regras-negocio/06-edicao-exclusao-e-auditoria.md#permissões).
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_GERENCIAM_ORGANIZACAO = (Role.ADMIN, Role.GESTOR)


def pode_gerenciar_organizacao(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_GERENCIAM_ORGANIZACAO


def pode_reabrir_safra(user) -> bool:
    return user.is_authenticated and user.role == Role.ADMIN


class GerenciaOrganizacaoMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Para as telas de cadastro de Empresa/Unidade/Safra: `ADMIN`/`GESTOR`."""

    def test_func(self):
        return pode_gerenciar_organizacao(self.request.user)
