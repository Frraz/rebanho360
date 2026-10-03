"""Quem pode editar/excluir registro confirmado — regra transversal.

Ver docs/regras-negocio/06-edicao-exclusao-e-auditoria.md#permissões e a
pendência #9 (docs/regras-negocio/99-pendencias.md): `ESCRITORIO` edita mas
não exclui, até o produtor decidir diferente. Ajuste é de uma linha aqui.
"""

from apps.accounts.models import Role

PAPEIS_QUE_EDITAM_CONFIRMADO = (Role.ESCRITORIO, Role.GESTOR, Role.ADMIN)
PAPEIS_QUE_EXCLUEM_CONFIRMADO = (Role.GESTOR, Role.ADMIN)


def pode_editar_confirmado(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_EDITAM_CONFIRMADO


def pode_excluir_confirmado(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_EXCLUEM_CONFIRMADO
