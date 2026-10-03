"""Validação e apresentação de documentos pessoais.

O CPF é guardado só com dígitos (11) e nunca vai inteiro para log nem para a
auditoria: lá entra mascarado (`mascarar_cpf`).
"""

import re

from django.core.exceptions import ValidationError

_NAO_DIGITO = re.compile(r"\D")


def somente_digitos(valor: str | None) -> str:
    return _NAO_DIGITO.sub("", valor or "")


def _digito_verificador(base: str) -> str:
    # Pesos decrescentes, a partir de len(base) + 1; resto < 2 vira 0.
    soma = sum(int(d) * peso for d, peso in zip(base, range(len(base) + 1, 1, -1)))
    resto = (soma * 10) % 11
    return str(0 if resto == 10 else resto)


def cpf_valido(valor: str | None) -> bool:
    cpf = somente_digitos(valor)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    d1 = _digito_verificador(cpf[:9])
    d2 = _digito_verificador(cpf[:9] + d1)
    return cpf[9:] == d1 + d2


def validar_cpf(valor: str | None) -> str:
    """Devolve o CPF só com dígitos; `""` se vazio (o campo é opcional)."""
    cpf = somente_digitos(valor)
    if not cpf:
        return ""
    if not cpf_valido(cpf):
        raise ValidationError("CPF inválido. Confira os 11 números.")
    return cpf


def formatar_cpf(valor: str | None) -> str:
    """`12345678909` → `123.456.789-09`. Vazio ou incompleto volta como veio."""
    cpf = somente_digitos(valor)
    if len(cpf) != 11:
        return valor or ""
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def mascarar_cpf(valor: str | None) -> str:
    """`12345678909` → `***.***.***-09`: serve para auditoria e telas de terceiros."""
    cpf = somente_digitos(valor)
    if len(cpf) != 11:
        return ""
    return f"***.***.***-{cpf[9:]}"
