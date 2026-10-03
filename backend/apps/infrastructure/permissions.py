"""Quem cadastra e lança. Ler é de qualquer usuário autenticado, no escopo de
fazenda (ADR 0003); cadastrar estrutura e máquina é do escritório para cima."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_CADASTRAM = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)
#: O campo também lança o uso da máquina (horas, combustível) — é dele o dado.
PAPEIS_QUE_LANCAM_USO = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO, Role.CAMPO)


def pode_cadastrar(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_CADASTRAM


def pode_lancar_uso(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_LANCAM_USO


class CadastraMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_cadastrar(self.request.user)


class LancaUsoMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_lancar_uso(self.request.user)
