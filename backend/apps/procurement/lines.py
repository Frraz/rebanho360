"""Sincronizar as linhas de um documento: criar, corrigir e retirar, com um
motivo só e auditoria linha a linha.

Linha **nunca sai do banco** (`removed_at`): o que ela era fica no `AuditEvent`
e no próprio registro. A operação do pai (compromisso, romaneio, acerto…) é
quem chama — linha solta não se edita (ADR 0008).
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.exceptions import BusinessError
from apps.core.serialization import diff_fields, snapshot


@dataclass
class ResultadoLinhas:
    criadas: list = field(default_factory=list)
    alteradas: list = field(default_factory=list)
    retiradas: list = field(default_factory=list)

    @property
    def mudou(self) -> bool:
        return bool(self.criadas or self.alteradas or self.retiradas)


def _normalizar(valor):
    if isinstance(valor, Decimal):
        return valor.normalize() if valor else Decimal("0")
    if isinstance(valor, str):
        return valor.strip()
    return valor


def _mudou(linha, entrada: dict, campos) -> bool:
    return any(
        campo in entrada
        and _normalizar(getattr(linha, campo)) != _normalizar(entrada[campo])
        for campo in campos
    )


def sincronizar_linhas(
    *,
    existentes,
    entradas: list[dict],
    campos: tuple,
    criar,
    usuario,
    motivo: str = "",
    antes_de_retirar=None,
) -> ResultadoLinhas:
    """`existentes`: as linhas ativas do pai. `entradas`: o que a tela mandou —
    cada uma com `id` (a linha existente) ou sem (linha nova). Linha existente
    que **não** veio em `entradas` é retirada.

    `criar(entrada)` devolve a linha nova **já salva**. `antes_de_retirar(linha)`
    pode recusar a retirada (`BusinessError`) quando algo depende dela.

    Corrigir ou retirar linha existente exige `motivo`; acrescentar, não.
    """
    por_id = {linha.pk: linha for linha in existentes}
    ids_enviados = {e["id"] for e in entradas if e.get("id") is not None}
    desconhecidos = ids_enviados - set(por_id)
    if desconhecidos:
        raise BusinessError("Uma das linhas enviadas não pertence a este documento.")

    a_retirar = [linha for pk, linha in por_id.items() if pk not in ids_enviados]
    a_alterar = [
        (por_id[e["id"]], e)
        for e in entradas
        if e.get("id") is not None and _mudou(por_id[e["id"]], e, campos)
    ]
    if (a_retirar or a_alterar) and not (motivo or "").strip():
        raise BusinessError(
            "Informe o motivo da correção: há linhas alteradas ou retiradas."
        )

    resultado = ResultadoLinhas()
    for linha in a_retirar:
        if antes_de_retirar is not None:
            antes_de_retirar(linha)
        antes = snapshot(linha)
        linha.removed_at = timezone.now()
        linha.removed_by = usuario
        linha.save(update_fields=["removed_at", "removed_by"])
        registrar_auditoria(
            action=AuditAction.DELETE,
            entity=linha,
            before=antes,
            after=snapshot(linha),
            reason=motivo,
            actor=usuario,
        )
        resultado.retiradas.append(linha)

    for linha, entrada in a_alterar:
        antes = snapshot(linha)
        for campo in campos:
            # Só o que mudou de verdade: regravar `480` por cima de `480.000`
            # faria a auditoria apontar um campo que ninguém mexeu.
            if campo in entrada and _normalizar(getattr(linha, campo)) != _normalizar(
                entrada[campo]
            ):
                setattr(linha, campo, entrada[campo])
        linha.save()
        depois = snapshot(linha)
        registrar_auditoria(
            action=AuditAction.UPDATE,
            entity=linha,
            before=antes,
            after=depois,
            changed_fields=diff_fields(antes, depois),
            reason=motivo,
            actor=usuario,
        )
        resultado.alteradas.append(linha)

    for entrada in entradas:
        if entrada.get("id") is not None:
            continue
        linha = criar(entrada)
        registrar_auditoria(
            action=AuditAction.CREATE,
            entity=linha,
            after=snapshot(linha),
            actor=usuario,
        )
        resultado.criadas.append(linha)
    return resultado
