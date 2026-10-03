from django.core.management.base import BaseCommand, CommandError

from apps.imports.conferencia import conferir, tabela_de_texto


class Command(BaseCommand):
    help = (
        "Compara o que o sistema tem com o que a planilha CONTROLE PASTO tem "
        "(235 custos, R$ 1.046.907,76, 954 cabeças, R$ 2.457.752,15, 354 "
        "abatidas, saldo 1.954...). Sai com erro se qualquer número divergir."
    )

    def handle(self, *args, **options):
        verificacoes = conferir()
        self.stdout.write(tabela_de_texto(verificacoes))
        divergentes = [v for v in verificacoes if not v.ok]
        if divergentes:
            raise CommandError(
                f"{len(divergentes)} de {len(verificacoes)} verificações divergem da planilha."
            )
        self.stdout.write(self.style.SUCCESS("Tudo confere com a planilha."))
