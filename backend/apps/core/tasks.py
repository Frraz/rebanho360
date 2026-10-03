import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="core.ping")
def ping() -> str:
    """Task mínima para validar o caminho web → broker → worker (F0-14)."""
    logger.info("core.ping executada com sucesso")
    return "pong"
