from apps.core import result_cache


class InvalidaCacheDeResultados:
    """Comando que grava dado em massa (seed, carga): ao terminar, ainda que com
    erro, o cache de resultados recomeça. Esses comandos usam `bulk_create` e SQL
    direto, que não passam pelos sinais de invalidação."""

    def execute(self, *args, **options):
        try:
            return super().execute(*args, **options)
        finally:
            result_cache.avancar()
