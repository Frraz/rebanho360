"""Códigos legíveis do ciclo: `CM-2025/26-0001` (compromisso), `VG-` (viagem),
`RB-` (recebimento), `AC-` (acerto). Sequência por safra, como `CP-`, `VD-` e
`TT-`. `RB` e não `RC`: `RC-` já é o recebimento de dinheiro da Fase 4."""

from apps.organizations.models import Season


def rotulo_da_safra(season: Season) -> str:
    inicio, _, fim = season.name.partition("/")
    return f"{inicio}/{fim[-2:]}" if fim else season.name


def proximo_codigo(model, prefixo: str, season: Season) -> str:
    """O chamador trava a safra (`select_for_update`): sem isso, dois lançamentos
    simultâneos calculariam a mesma sequência. Registro nunca sai do banco,
    então a contagem só cresce."""
    base = f"{prefixo}-{rotulo_da_safra(season)}-"
    existentes = model.objects.filter(code__startswith=base).count()
    return f"{base}{existentes + 1:04d}"
