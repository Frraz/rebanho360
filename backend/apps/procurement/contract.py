"""O contrato de compra (compromisso) em PDF.

Cada geração é um `GeneratedDocument` próprio, com a **versão do template** e o
hash do arquivo: o PDF guardado é a reprodução exata do que foi impresso, mesmo
que o layout mude depois (docs/relatorios/01#documentos-gerados).

**Dado bancário** (banco, agência e conta do produtor) **vai no contrato** — o
cliente confirmou em 2026-10-03 que o modelo de contrato de compra já os traz
(pendência #27). Mas só quando quem gera o PDF já pode ver dado bancário
(`ADMIN`, `GESTOR`, `FINANCEIRO`): para os demais, o contrato sai sem os três
campos, e a geração com dado bancário fica registrada na auditoria.
"""

import hashlib
import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria, registrar_operacao
from apps.core import context as ctx
from apps.core.exceptions import BusinessError
from apps.core.reversible import Status
from apps.documents.models import DocumentStatus, DocumentType, GeneratedDocument
from apps.finance.permissions import pode_ver_dado_bancario
from apps.finance.services import conta_padrao
from apps.procurement import commitments
from apps.procurement.models import Commitment, PriceBasis
from apps.procurement.permissions import pode_ver_o_ciclo

logger = logging.getLogger(__name__)

#: Muda quando o layout do contrato muda. Fica gravada em cada documento.
TEMPLATE_VERSION = "contrato-v2"


def contratos_do_compromisso(compromisso: Commitment):
    return GeneratedDocument.objects.filter(
        doc_type=DocumentType.CONTRATO,
        entity_type="Commitment",
        entity_id=str(compromisso.pk),
    ).select_related("generated_by")


def conta_do_produtor(compromisso: Commitment):
    """A conta padrão do produtor (ou a única que ele tem); `None` se não há."""
    return conta_padrao(compromisso.seller)


def renderizar_html(
    compromisso: Commitment, *, emitido_por: str, emitido_em, com_dado_bancario=False
) -> str:
    itens = list(compromisso.items.select_related("category").order_by("number"))
    return render_to_string(
        "documents/contrato.html",
        {
            "compromisso": compromisso,
            "compradores": commitments.comissoes_do(compromisso),
            "conta": conta_do_produtor(compromisso) if com_dado_bancario else None,
            "com_dado_bancario": com_dado_bancario,
            "condicao": (
                compromisso.payment_condition.resumo
                if compromisso.payment_condition_id
                else (
                    f"{compromisso.payment_days} dias"
                    if compromisso.payment_days
                    else "à vista"
                )
            ),
            "empresa": ctx.current_company(),
            "itens": itens,
            "por_arroba": PriceBasis.ARROBA,
            "emitido_por": emitido_por,
            "emitido_em": emitido_em,
            "versao": TEMPLATE_VERSION,
        },
    )


@transaction.atomic
def gerar_contrato(compromisso: Commitment, *, usuario) -> GeneratedDocument:
    """Gera o PDF na hora (é uma página; não vale a fila). Falha vira documento
    com o motivo, nunca traceback."""
    if not pode_ver_o_ciclo(usuario):
        raise BusinessError("Você não tem permissão para gerar o contrato.")
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.CONFIRMADA:
        raise BusinessError("O contrato só se gera depois da aprovação do compromisso.")

    documento = GeneratedDocument.objects.create(
        doc_type=DocumentType.CONTRATO,
        entity_type="Commitment",
        entity_id=str(compromisso.pk),
        title=f"Contrato de compra {compromisso.code}",
        template_version=TEMPLATE_VERSION,
        params={
            "commitment_id": compromisso.pk,
            "commitment_version": compromisso.version,
        },
        filters=[f"Compromisso {compromisso.code}", f"Versão {compromisso.version}"],
        generated_by=usuario,
    )
    agora = timezone.localtime()
    try:
        import weasyprint

        html = renderizar_html(
            compromisso,
            emitido_por=str(usuario),
            emitido_em=agora,
            com_dado_bancario=pode_ver_dado_bancario(usuario),
        )
        pdf = weasyprint.HTML(string=html).write_pdf()
    except Exception:  # o usuário vê o motivo e o código, nunca um traceback
        logger.exception("Falha ao gerar o contrato %s", documento.document_id)
        documento.status = DocumentStatus.ERRO
        documento.error = (
            "Não foi possível gerar o PDF do contrato. Tente de novo; se persistir, "
            f"avise o suporte com o código {documento.document_id}."
        )
        documento.finished_at = timezone.now()
        documento.save(update_fields=["status", "error", "finished_at"])
        return documento

    documento.file.save(
        f"contrato-{compromisso.code.replace('/', '-')}-{documento.document_id}.pdf",
        ContentFile(pdf),
        save=False,
    )
    documento.file_hash = hashlib.sha256(pdf).hexdigest()
    documento.size_bytes = len(pdf)
    documento.status = DocumentStatus.PRONTO
    documento.finished_at = timezone.now()
    documento.save()

    registrar_auditoria(
        action=AuditAction.EXPORT,
        entity_type="Documento",
        entity_id=str(documento.document_id),
        reason=f"{documento.title} · versão {compromisso.version} do compromisso"
        + (" · com dados bancários" if pode_ver_dado_bancario(usuario) else ""),
        actor=usuario,
    )
    registrar_operacao(
        entity=compromisso,
        title="Contrato gerado",
        description=f"PDF {documento.document_id} (layout {TEMPLATE_VERSION}).",
        document=str(documento.document_id),
        actor=usuario,
    )
    return documento
