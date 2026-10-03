from django.core.management.base import BaseCommand, CommandError

from apps.accounts import two_factor
from apps.accounts.models import User


class Command(BaseCommand):
    help = (
        "Redefine o segundo fator de um usuário que perdeu o celular e os "
        "códigos de recuperação. Último recurso — fica na auditoria. No próximo "
        "login a pessoa configura de novo."
    )

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument(
            "--motivo", default="", help="Por que (vai para a auditoria)."
        )

    def handle(self, *args, **options):
        try:
            usuario = User.objects.get(username=options["username"])
        except User.DoesNotExist as exc:
            raise CommandError(f"Usuário '{options['username']}' não existe.") from exc
        two_factor.redefinir_segundo_fator(usuario, por=None, motivo=options["motivo"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Segundo fator de {usuario.username} redefinido. "
                "Ele entra só com a senha e pode ativar de novo na página Conta."
            )
        )
