"""Condição de pagamento aplicada a uma operação (compra, compromisso, venda).

A operação guarda a condição escolhida **e** o prazo do primeiro vencimento
(`payment_days`), que é o que o financeiro lê. Condição parcelada gera mais de
um título (ver `finance.services`); o primeiro prazo é o do primeiro título.
"""

from apps.core.exceptions import BusinessError


def aplicar_condicao(dados: dict, *, atual=None) -> dict:
    """Copia o primeiro prazo da condição escolhida para `payment_days`.

    Condição inativa só é aceita se já era a da operação (`atual`). Sem
    condição escolhida, `payment_days` fica como o usuário digitou.
    """
    condicao = dados.get("payment_condition")
    if condicao is None:
        return dados
    if not condicao.is_active and (atual is None or atual.pk != condicao.pk):
        raise BusinessError(f"A condição de pagamento {condicao} está inativa.")
    return {**dados, "payment_days": condicao.primeiro_prazo}
