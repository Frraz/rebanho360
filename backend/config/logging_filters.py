"""Filtro que impede dado sensível de chegar ao log — nunca na disciplina
de quem escreve o log. Ver docs/seguranca/01-seguranca.md#segredos."""

import logging
import re

_PATTERNS = [
    (
        re.compile(r'(password["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+', re.IGNORECASE),
        r"\1***",
    ),
    (re.compile(r'(token["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+', re.IGNORECASE), r"\1***"),
    (
        re.compile(r'(secret_key["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+', re.IGNORECASE),
        r"\1***",
    ),
    # CPF/CNPJ completos (11 ou 14 dígitos, com ou sem pontuação)
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "***.***.***-**"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "**.***.***/****-**"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)

        # `LogRecord.args` vira um dict puro (não uma tupla com um dict
        # dentro) quando o chamador usa %-formatting por mapeamento — é o
        # que o Celery faz no log de sucesso de task. Preservar a forma,
        # senão `getMessage()` quebra tentando iterar o dict como posicional.
        if isinstance(record.args, dict):
            record.args = {
                key: (redact(value) if isinstance(value, str) else value)
                for key, value in record.args.items()
            }
        elif record.args:
            record.args = tuple(
                redact(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True
