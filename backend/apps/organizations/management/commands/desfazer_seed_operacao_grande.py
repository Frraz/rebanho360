"""Desfaz o que `seed_operacao_grande` criou — só isso.

    python manage.py desfazer_seed_operacao_grande --simular   # só mostra o que sairia
    python manage.py desfazer_seed_operacao_grande             # pede confirmação
    python manage.py desfazer_seed_operacao_grande --sim       # sem perguntar

Apaga de verdade as fazendas `S3-…`, tudo que pertence a elas, os parceiros
marcados `[seed-3safras]` e as safras que o seed criou (e que ficaram sem uso).
**Não toca em usuários nem nos seus acessos**, e **nunca apaga a auditoria**:
no fim grava um evento dizendo que o seed foi desfeito.

É tudo-ou-nada: se algum dado seu (que não é do seed) ainda depender de algo
que seria apagado, o comando para e não remove nada.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.core.management.mixins import InvalidaCacheDeResultados
from apps.organizations.seed_operacao import purga
from apps.organizations.seed_operacao.contexto import descobrir_atores


class Command(InvalidaCacheDeResultados, BaseCommand):
    help = "Desfaz o seed_operacao_grande, sem tocar em usuários nem na auditoria."

    def add_arguments(self, parser):
        parser.add_argument(
            "--simular",
            action="store_true",
            help="Executa tudo numa transação e desfaz no fim: só mostra os números.",
        )
        parser.add_argument(
            "--sim", action="store_true", help="Não pergunta antes de apagar."
        )
        parser.add_argument(
            "--force", action="store_true", help="Permite rodar com DEBUG=False."
        )

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError(
                "Recusado: apaga dados de verdade e só roda com DEBUG=True "
                "(ou com --force, por sua conta e risco)."
            )
        if connection.vendor != "postgresql":
            raise CommandError("O desfazer precisa de PostgreSQL.")
        if not purga.existe_seed():
            self.stdout.write("Não há nada do seed neste banco.")
            return
        try:
            admin = descobrir_atores().admin
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if not opts["simular"] and not opts["sim"]:
            self.stdout.write(
                "Isto apaga, de verdade, as fazendas S3-…, tudo que pertence a elas e "
                "os parceiros do seed. Usuários e auditoria não são tocados."
            )
            if input("Digite 'desfazer' para continuar: ").strip() != "desfazer":
                self.stdout.write("Cancelado. Nada foi apagado.")
                return

        try:
            apagados = purga.desfazer(admin=admin, simular=opts["simular"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        titulo = (
            "Simulação (nada foi apagado):" if opts["simular"] else "Seed desfeito:"
        )
        self.stdout.write(self.style.SUCCESS(titulo))
        for rotulo, n in apagados.items():
            self.stdout.write(f"  {rotulo}: {n}")
        if not opts["simular"]:
            self.stdout.write(
                "\nA auditoria foi preservada e um evento 'Seed desfeito' foi gravado."
            )
