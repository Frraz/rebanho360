"""Códigos legíveis do ciclo.

**Um número só por operação** (cliente, 2026-10-03, pendência #32): o
compromisso nasce com `OP-000123` e as etapas seguintes carregam o mesmo número
principal — viagem `OP-000123/V1` (embarque), recebimento `OP-000123/R1`,
acerto `OP-000123/AC1` e a compra de cada item `OP-000123/I1`. Compra,
programação, compromisso, embarque, acerto, financeiro e centro de custo se
leem pelo mesmo número.

O compromisso é o dono da sequência (global, sem reiniciar por safra). O que
já existia — `CM-2025/26-0001`, `VG-…`, `RB-…`, `AC-…` — **não é renomeado**:
o código já saiu em contrato e em tela, e mudá-lo quebraria a referência. Uma
etapa nova de um compromisso antigo segue o esquema antigo.

`RB` e não `RC` no esquema antigo: `RC-` já é o recebimento de dinheiro.
"""

import re

from django.db import connection
from django.db.models import Max

from apps.organizations.models import Season

PREFIXO_DA_OPERACAO = "OP"
#: Chave do `pg_advisory_xact_lock` que serializa a numeração das operações.
TRAVA_DA_NUMERACAO = 360_001
FORMATO_DA_OPERACAO = re.compile(r"^OP-\d{6}$")


def rotulo_da_safra(season: Season) -> str:
    inicio, _, fim = season.name.partition("/")
    return f"{inicio}/{fim[-2:]}" if fim else season.name


def proximo_codigo(model, prefixo: str, season: Season) -> str:
    """Esquema antigo, por safra. O chamador trava a safra (`select_for_update`):
    sem isso, dois lançamentos simultâneos calculariam a mesma sequência.
    Registro nunca sai do banco, então a contagem só cresce."""
    base = f"{prefixo}-{rotulo_da_safra(season)}-"
    existentes = model.objects.filter(code__startswith=base).count()
    return f"{base}{existentes + 1:04d}"


def proximo_numero_da_operacao() -> str:
    """`OP-000123`. A sequência é global; a trava vale até o fim da transação
    (precisa estar dentro de `transaction.atomic`), e a segunda operação
    simultânea espera a primeira gravar para ler o número seguinte."""
    from apps.procurement.models import Commitment

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA_DA_NUMERACAO])
    ultimo = Commitment.objects.filter(code__regex=r"^OP-[0-9]{6}$").aggregate(
        m=Max("code")
    )["m"]
    numero = int(ultimo.split("-")[1]) + 1 if ultimo else 1
    return f"{PREFIXO_DA_OPERACAO}-{numero:06d}"


def eh_numero_de_operacao(codigo: str) -> bool:
    return bool(FORMATO_DA_OPERACAO.match(codigo or ""))


def codigo_da_etapa(
    model, *, compromisso, sufixo: str, legado: str, season: Season
) -> str:
    """Código de viagem, recebimento ou acerto. Compromisso novo: o número da
    operação mais a etapa (`OP-000123/V2`); antigo: o esquema por safra."""
    if not eh_numero_de_operacao(compromisso.code):
        return proximo_codigo(model, legado, season)
    base = f"{compromisso.code}/{sufixo}"
    # Conta também os excluídos: número nunca é reaproveitado.
    return f"{base}{model.objects.filter(code__startswith=base).count() + 1}"


def codigo_da_compra_do_item(compromisso, item) -> str | None:
    """`OP-000123/I1` para a compra gerada pelo acerto; `None` (esquema antigo
    `CP-`) se o compromisso é de antes da numeração única."""
    if not eh_numero_de_operacao(compromisso.code):
        return None
    return f"{compromisso.code}/I{item.number}"
