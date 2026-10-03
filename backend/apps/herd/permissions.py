"""Quem pode o quê, e sobre qual fazenda."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role, UserFarmAccess

PAPEIS_QUE_LANCAM_MOVIMENTO = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO, Role.CAMPO)
PAPEIS_QUE_LANCAM_EM_SAFRA_ENCERRADA = (Role.ADMIN,)
PAPEIS_QUE_LANCAM_AJUSTE_INVENTARIO = (Role.ADMIN, Role.GESTOR)


def pode_lancar_movimento(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_LANCAM_MOVIMENTO


def pode_lancar_ajuste_inventario(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_LANCAM_AJUSTE_INVENTARIO


def pode_lancar_em_safra_encerrada(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_LANCAM_EM_SAFRA_ENCERRADA


def tem_acesso_de_escrita_a_fazenda(user, farm) -> bool:
    if farm is None:
        return True
    if user.has_broad_access:
        return True
    return UserFarmAccess.objects.filter(user=user, farm=farm, can_write=True).exists()


class LancaMovimentoMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_lancar_movimento(self.request.user)
