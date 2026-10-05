"""Escrita de dado de negócio invalida o cache de resultados.

Cada gravação ou exclusão de um modelo que alimenta o dashboard sobe a época
do cache (`apps/core/result_cache.py`) depois do commit. É a segunda rede: a
primeira é a auditoria (toda ação auditada também invalida), esta cobre quem
grava sem auditar (ex.: um ajuste direto num serviço).

Fora da lista de propósito: `audit` (já invalida pelo serviço), `exports` e
`documents` (mudam de estado a cada poucos segundos e não entram em número
nenhum), `imports` (a prévia não é dado; a confirmação grava os modelos reais)
e `accounts` (login atualiza `last_login`: invalidaria a cada entrada; mudança
de papel e de acesso é auditada).
"""

from django.apps import apps
from django.db.models.signals import post_delete, post_save

from apps.core import result_cache

APPS_DE_DADOS = frozenset(
    {
        "commercial",
        "costs",
        "finance",
        "herd",
        "infrastructure",
        "livestock",
        "organizations",
        "partners",
        "procurement",
        "properties",
        "purchases",
        "reproduction",
        "sales",
    }
)

#: `accounts.UserFarmAccess` muda o que cada usuário enxerga.
MODELOS_EXTRAS = frozenset({"accounts.userfarmaccess"})


def _invalidar(sender, **kwargs):
    result_cache.avancar_ao_confirmar()


def conectar() -> None:
    for modelo in apps.get_models():
        rotulo = modelo._meta.label_lower
        if modelo._meta.app_label in APPS_DE_DADOS or rotulo in MODELOS_EXTRAS:
            for sinal in (post_save, post_delete):
                sinal.connect(
                    _invalidar,
                    sender=modelo,
                    weak=False,
                    dispatch_uid=f"r360-resultados-{sinal_nome(sinal)}-{rotulo}",
                )


def sinal_nome(sinal) -> str:
    return "save" if sinal is post_save else "delete"
