"""Quem pode o quê no financeiro, e sobre qual fazenda.

O papel define a ação; `UserFarmAccess` define o alcance (ADR 0003) — as
consultas passam por `for_user()`, e fora do escopo o registro é 404.

A separação que importa: **quem aprova não é quem executa**. São duas
permissões distintas (`finance.approve_payment` e `finance.execute_payment`
da especificação), e o serviço ainda recusa que a mesma pessoa faça as duas no
mesmo título quando há outro usuário que possa executar. Qualquer ajuste de
quem pode o quê é uma linha aqui — pendência #17.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_VEEM_TITULOS = (
    Role.ADMIN,
    Role.GESTOR,
    Role.FINANCEIRO,
    Role.ESCRITORIO,
    Role.CONSULTA,
)
#: Conta bancária e Pix de terceiros: mais restrito que ver o título.
PAPEIS_QUE_VEEM_DADO_BANCARIO = (Role.ADMIN, Role.GESTOR, Role.FINANCEIRO)
#: Criar, corrigir e programar título.
PAPEIS_QUE_GERENCIAM_TITULOS = (
    Role.ADMIN,
    Role.GESTOR,
    Role.FINANCEIRO,
    Role.ESCRITORIO,
)
#: `finance.approve_payment`
PAPEIS_QUE_APROVAM_PAGAMENTO = (Role.ADMIN, Role.GESTOR, Role.FINANCEIRO)
#: `finance.execute_payment` — dar a baixa.
PAPEIS_QUE_EXECUTAM_PAGAMENTO = (Role.ADMIN, Role.FINANCEIRO)
#: Desfazer baixa: FINANCEIRO ou ADMIN, com motivo (fluxos/02).
PAPEIS_QUE_DESFAZEM_BAIXA = (Role.ADMIN, Role.FINANCEIRO)


def _tem_papel(user, papeis) -> bool:
    return user.is_authenticated and user.role in papeis


def pode_ver_titulos(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_VEEM_TITULOS)


def pode_ver_dado_bancario(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_VEEM_DADO_BANCARIO)


def pode_gerenciar_titulos(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_GERENCIAM_TITULOS)


def pode_aprovar_pagamento(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_APROVAM_PAGAMENTO)


def pode_executar_pagamento(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_EXECUTAM_PAGAMENTO)


def pode_desfazer_baixa(user) -> bool:
    return _tem_papel(user, PAPEIS_QUE_DESFAZEM_BAIXA)


class VeTitulosMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_ver_titulos(self.request.user)


class GerenciaTitulosMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_gerenciar_titulos(self.request.user)
