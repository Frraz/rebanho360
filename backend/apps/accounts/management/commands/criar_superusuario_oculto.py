import os
from getpass import getpass

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Role, User


class Command(BaseCommand):
    help = (
        "Cria o superusuário de suporte: acesso total e invisível para os demais "
        "usuários (não aparece em listas, filtros, exportações nem no admin). "
        "Aparece na auditoria só como 'Suporte Técnico'. Os outros usuários "
        "se criam por ele ou pelos administradores, dentro do sistema."
    )

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument(
            "--email",
            default="",
            help="Opcional. Só para recuperar a senha; ninguém mais o vê.",
        )
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="Lê a senha de DJANGO_SUPERUSER_PASSWORD em vez de perguntar.",
        )

    def handle(self, *args, **options):
        username = options["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError(f"Já existe um usuário '{username}'.")

        senha = self._senha(options["noinput"])
        try:
            password_validation.validate_password(senha, User(username=username))
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        # O papel é ADMIN para que toda checagem por papel passe; `is_superuser`
        # é o que o torna oculto e com acesso a todas as fazendas
        # (`User.has_broad_access`). O nome genérico é de propósito: é o que
        # aparece nos registros de auditoria para os outros usuários.
        User.objects.create_superuser(
            username=username,
            email=options["email"],
            password=senha,
            role=Role.ADMIN,
            first_name="Suporte",
            last_name="Técnico",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Superusuário '{username}' criado. Ele não aparece para os outros "
                "usuários. Ative o segundo fator dele na página Conta (recomendado)."
            )
        )

    def _senha(self, sem_perguntar: bool) -> str:
        if sem_perguntar:
            senha = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
            if not senha:
                raise CommandError(
                    "Defina DJANGO_SUPERUSER_PASSWORD para usar --noinput."
                )
            return senha
        senha = getpass("Senha: ")
        if senha != getpass("Senha (de novo): "):
            raise CommandError("As senhas não conferem.")
        return senha
