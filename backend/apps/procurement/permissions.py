"""Quem pode o quê no ciclo de compra (pendências #25 e #28, respondidas pelo
cliente em 2026-10-03).

Uma linha por papel, ajustável aqui:

- **Lançam e corrigem** (compromisso, viagem, recebimento, romaneio, linhas do
  acerto): `ADMIN`, `GESTOR`, `ESCRITORIO`.
- **Aprovam o compromisso e o acerto, e reabrem o acerto:** `ADMIN` e
  `GESTOR`. **Não há segregação**: quem lançou pode aprovar o próprio
  lançamento — o que fica registrado é quem lançou, quem aprovou, data e hora
  (`created_by`, `approved_by`, `approved_at` e a auditoria), mesmo sendo a
  mesma pessoa. O `ESCRITORIO` lança, mas não aprova.
- **Encerram a operação:** `ADMIN` e `GESTOR`.
- **Veem:** todos, menos `CAMPO`. Preço, comissão e frete são dado comercial.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_LANCAM_NO_CICLO = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)
PAPEIS_QUE_APROVAM_O_COMPROMISSO = (Role.ADMIN, Role.GESTOR)
PAPEIS_QUE_APROVAM_O_ACERTO = (Role.ADMIN, Role.GESTOR)
PAPEIS_QUE_ENCERRAM_A_OPERACAO = (Role.ADMIN, Role.GESTOR)
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


def pode_aprovar_o_compromisso(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_APROVAM_O_COMPROMISSO)


def pode_aprovar_o_acerto(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_APROVAM_O_ACERTO)


def pode_encerrar_a_operacao(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_ENCERRAM_A_OPERACAO)


def pode_ver_o_ciclo(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_VEEM_O_CICLO)


class VeOCicloMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_ver_o_ciclo(self.request.user)


class LancaNoCicloMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_lancar_no_ciclo(self.request.user)


class AprovaOCompromissoMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_aprovar_o_compromisso(self.request.user)


class AprovaOAcertoMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_aprovar_o_acerto(self.request.user)
