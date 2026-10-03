"""Quem pode o quê no ciclo de compra (pendência #25).

Palpite do desenvolvimento, ajustável aqui, uma linha por papel:

- **Lançam e corrigem** (compromisso, viagem, recebimento, romaneio, linhas do
  acerto): `ADMIN`, `GESTOR`, `ESCRITORIO`.
- **Aprovam e reabrem o acerto:** `ADMIN` e `GESTOR` — é ele que vira compra,
  custo e título. O `ESCRITORIO` não aprova o que lançou.
- **Veem:** todos, menos `CAMPO`. Preço, comissão e frete são dado comercial.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_LANCAM_NO_CICLO = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)
PAPEIS_QUE_APROVAM_O_ACERTO = (Role.ADMIN, Role.GESTOR)
PAPEIS_QUE_VEEM_O_CICLO = (
    Role.ADMIN,
    Role.GESTOR,
    Role.ESCRITORIO,
    Role.FINANCEIRO,
    Role.CONSULTA,
)


def _tem_papel(user, papeis) -> bool:
    return user.is_authenticated and user.role in papeis


def pode_lancar_no_ciclo(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_LANCAM_NO_CICLO)


def pode_aprovar_o_acerto(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_APROVAM_O_ACERTO)


def pode_ver_o_ciclo(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_VEEM_O_CICLO)


class VeOCicloMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_ver_o_ciclo(self.request.user)


class LancaNoCicloMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_lancar_no_ciclo(self.request.user)


class AprovaOAcertoMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_aprovar_o_acerto(self.request.user)
