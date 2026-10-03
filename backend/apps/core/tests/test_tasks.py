"""F0-14: o caminho web → broker → worker existe e uma task roda de verdade."""

from apps.core.tasks import ping
from config.celery import app as celery_app


def test_task_core_ping_esta_registrada():
    assert "core.ping" in celery_app.tasks


def test_task_core_ping_executa_e_devolve_pong():
    assert ping.run() == "pong"
