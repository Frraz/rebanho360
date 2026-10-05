"""Descarta todos os resultados guardados (dashboard e Início).

Só é preciso depois de uma escrita que não passa por modelo nem auditoria (SQL
manual, restauração de backup). O resto invalida sozinho
(apps/core/result_cache.py)."""

from django.core.management.base import BaseCommand

from apps.core import result_cache


class Command(BaseCommand):
    help = "Descarta os resultados guardados do dashboard e da tela Início."

    def handle(self, *args, **options):
        result_cache.avancar()
        self.stdout.write(
            self.style.SUCCESS(
                "Cache de resultados limpo: a próxima abertura recalcula."
            )
        )
