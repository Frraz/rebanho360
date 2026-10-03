"""Tarefas Celery. A leitura pesada fica fora do navegador."""

from celery import shared_task

from apps.exports import services

# Uma hora para ler tudo e empacotar; o aviso (`SoftTimeLimitExceeded`) vem 5
# minutos antes do corte, a tempo de `executar_exportacao` registrar o motivo.
LIMITE_SUAVE = 60 * 60
LIMITE_DURO = LIMITE_SUAVE + 5 * 60


@shared_task(
    name="exports.executar", soft_time_limit=LIMITE_SUAVE, time_limit=LIMITE_DURO
)
def executar(job_id: int) -> str:
    return str(services.executar_exportacao(job_id).job_id)


@shared_task(name="exports.manutencao")
def manutencao() -> dict:
    return services.manutencao()
