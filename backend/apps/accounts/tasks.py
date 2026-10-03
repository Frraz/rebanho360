"""Tarefas Celery."""

import logging

from celery import shared_task
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


@shared_task(
    name="accounts.enviar_email",
    autoretry_for=(OSError,),
    retry_backoff=30,
    max_retries=3,
)
def enviar_email(assunto: str, corpo: str, destinatarios: list[str]) -> int:
    """Envia um e-mail de texto. SMTP fora do ar (OSError) tenta de novo com
    espera crescente; depois disso fica no log, sem derrubar ninguém."""
    mensagem = EmailMessage(subject=assunto, body=corpo, to=destinatarios)
    return mensagem.send(fail_silently=False)
