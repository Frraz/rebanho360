"""Documento automático da aprovação, sem efeitos financeiros."""

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.documents.models import GeneratedDocument
from apps.documents.services import gerar_documento

SLUG = "programacao-de-compras-e-pagamentos"


def gerar_programacao(compromisso, *, usuario):
    # Chamado dentro da aprovação bloqueada por select_for_update. A segunda
    # aprovação é recusada antes daqui; uma falha de renderização não a desfaz.
    documento = GeneratedDocument.objects.create(
        entity_type="Relatorio",
        entity_id=SLUG,
        title="Programação de compras e pagamentos",
        template_version="programacao-v1",
        params={
            "season_id": compromisso.season_id,
            "farm_id": compromisso.destination_farm_id,
            "commitment_id": compromisso.pk,
            "commitment_version": compromisso.version,
        },
        filters=[
            f"Safra: {compromisso.season}",
            f"Fazenda: {compromisso.destination_farm}",
        ],
        generated_by=usuario,
    )
    registrar_auditoria(
        action=AuditAction.EXPORT,
        entity_type="Documento",
        entity_id=str(documento.document_id),
        reason=f"Programação automática · aprovação de {compromisso.code}",
        actor=usuario,
    )
    return gerar_documento(documento.pk)
