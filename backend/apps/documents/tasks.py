"""Tarefas Celery. Relatório pesado não segura o navegador."""

from celery import shared_task

from apps.documents import services


@shared_task(name="documents.gerar_pdf")
def gerar_pdf(documento_id: int) -> str:
    documento = services.gerar_documento(documento_id)
    return str(documento.document_id)
