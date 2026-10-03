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


@shared_task(name="accounts.manutencao")
def manutencao() -> dict:
    """Uma vez por dia: sessões vencidas (`django_session` só cresce) e
    dispositivos confiáveis vencidos ou revogados há mais de 30 dias."""
    from django.core.management import call_command

    from apps.accounts import trusted_devices

    call_command("clearsessions")
    return {"dispositivos_apagados": trusted_devices.limpar_antigos()}
