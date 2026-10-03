from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts import two_factor
from apps.accounts.models import User


class Command(BaseCommand):
    help = (
        "Mostra a hora do servidor e quem já usa o segundo fator. O segundo "
        "fator é opcional, mas depende do relógio: com a hora errada, os "
        "códigos do celular não batem."
    )

    def handle(self, *args, **options):
        agora = timezone.now()
        self.stdout.write(
            f"Hora do servidor (UTC): {agora:%Y-%m-%d %H:%M:%S} — confira com "
            "`timedatectl` (NTP ativo). Os códigos do celular dependem disto: "
            f"tolerância de ±{settings.TWO_FACTOR_WINDOW * two_factor.PASSO_EM_SEGUNDOS} s."
        )
        self.stdout.write(f"Passo TOTP atual: {two_factor.passo_atual()}\n")

        sem = 0
        for usuario in User.objects.filter(
            is_active=True, deleted_at__isnull=True
        ).order_by("username"):
            ativo = two_factor.dispositivo_confirmado(usuario) is not None
            situacao = (
                f"ativo, {two_factor.codigos_de_recuperacao_restantes(usuario)} códigos de recuperação"
                if ativo
                else "não usa"
            )
            self.stdout.write(f"  {usuario.username:<24} {usuario.role:<11} {situacao}")
            sem += 0 if ativo else 1

        if sem:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{sem} usuário(s) sem segundo fator. Não é obrigatório: "
                    "recomende a cada um ativar na página Conta."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nTodos usam o segundo fator."))
