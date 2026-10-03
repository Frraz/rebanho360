"""Simula o uso real de um produtor grande, em três safras.

    python manage.py seed_operacao_grande
    python manage.py seed_operacao_grande --escala 0.2      # versão rápida
    python manage.py seed_operacao_grande --vincular-acessos

Cria 12 fazendas (cria, recria, engorda a pasto e confinamento), parceiros,
compras diretas, o ciclo completo de compra (OP), nascimentos e desmama,
pesagens, mortes, transferências, vendas e abates, custos, máquinas, títulos e
baixas — de 01/07/2024 até hoje (ou até o dia anterior ao começo da safra de
outra empresa, ver abaixo).

Tudo passa pelos **serviços** do sistema, então o razão fecha, os títulos
nascem e a auditoria registra. **Não cria nem altera nenhum usuário**: lança em
nome do ADMIN e aprova em nome do GESTOR que já existem.

O que o seed cria é identificável (fazendas `S3-…`, parceiros marcados) e se
desfaz com `python manage.py desfazer_seed_operacao_grande`.

Nunca roda em produção: recusa `DEBUG=False` sem `--force`.
"""

import datetime
import random
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from apps.core.context import current_company
from apps.core.request_context import use_context
from apps.herd.models import HerdLedgerEntry, HerdMovement
from apps.organizations.models import Season
from apps.organizations.seed_operacao import (
    cadastros,
    extras,
    financeiro,
    simulacao,
)
from apps.organizations.seed_operacao import catalogo as cat
from apps.organizations.seed_operacao.contexto import Contexto, descobrir_atores
from apps.properties.models import Farm


class Command(BaseCommand):
    help = (
        "Popula o sistema com 3 safras de uma operação pecuária grande (12 fazendas)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--semente", type=int, default=360)
        parser.add_argument(
            "--escala",
            type=Decimal,
            default=Decimal("1"),
            help="1 = volume completo; 0.2 = versão rápida para teste.",
        )
        parser.add_argument(
            "--vincular-acessos",
            action="store_true",
            help="Dá acesso às fazendas do seed aos usuários de papel restrito "
            "(escritório, campo, financeiro, consulta). ADMIN e GESTOR já veem tudo.",
        )
        parser.add_argument(
            "--manter-safras-abertas",
            action="store_true",
            help="Não encerra as safras passadas que o seed criou.",
        )
        parser.add_argument(
            "--force", action="store_true", help="Permite rodar com DEBUG=False."
        )

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError(
                "Recusado: este comando inventa compras, vendas e pagamentos e só "
                "roda com DEBUG=True (ou com --force, por sua conta e risco)."
            )
        if connection.vendor != "postgresql":
            raise CommandError(
                "O seed precisa de PostgreSQL (triggers e travas do razão)."
            )
        if opts["escala"] <= 0:
            raise CommandError("--escala precisa ser maior que zero.")
        if Farm.objects.filter(code__startswith=cat.PREFIXO).exists():
            raise CommandError(
                "Já existem fazendas do seed (códigos S3-…). Rode "
                "'desfazer_seed_operacao_grande' antes de rodar de novo."
            )
        company = current_company()
        if company is None:
            raise CommandError("Não há empresa ativa cadastrada.")
        try:
            atores = descobrir_atores()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        hoje = timezone.localdate()
        inicio = datetime.date(2024, 7, 1)
        cutoff = self._corte(company, inicio, hoje)
        ctx = Contexto(
            rnd=random.Random(opts["semente"]),
            escala=opts["escala"],
            hoje=hoje,
            inicio=inicio,
            cutoff=cutoff,
            company=company,
            atores=atores,
            saida=self.stdout.write,
        )
        self.stdout.write(
            f"Empresa: {company.name} · de {inicio:%d/%m/%Y} até {cutoff:%d/%m/%Y} · "
            f"lançando como {atores.admin.username} (aprova: {atores.gestor.username})"
        )
        if cutoff < hoje:
            self.stdout.write(
                f"  (o corte é {cutoff:%d/%m/%Y} e não hoje: a partir de "
                f"{cutoff + datetime.timedelta(days=1):%d/%m/%Y} outra empresa tem safra "
                "aberta, e o sistema escolhe a safra só pela data)"
            )
        for aviso in atores.avisos:
            self.stdout.write(self.style.WARNING("  Aviso: " + aviso))

        with use_context(actor=atores.admin, request_id=uuid.UUID(cat.SEED_UUID)):
            self._executar(ctx, opts)

        self._resumo(ctx)

    # ------------------------------------------------------------------
    def _corte(self, company, inicio, hoje):
        """`season_para_data` escolhe a safra só pela data, sem olhar a empresa:
        se outra empresa tem uma safra que começa dentro do período, os fatos
        a partir dela cairiam na safra errada. O seed para na véspera."""
        # Nunca além da última safra simulada (2026/2027 termina em 30/06/2027).
        corte = min(hoje, cadastros.SAFRAS[-1][2])
        for outra in Season.objects.exclude(company=company).filter(
            end_date__gte=inicio
        ):
            if outra.start_date > inicio:
                corte = min(corte, outra.start_date - datetime.timedelta(days=1))
        return corte

    def _executar(self, ctx, opts):
        self.stdout.write("Cadastros…")
        cadastros.preparar_referencias(ctx)
        cadastros.preparar_safras(ctx)
        cadastros.criar_fazendas(ctx)
        cadastros.criar_parceiros(ctx)
        cadastros.criar_regras_de_comissao(ctx)
        cadastros.criar_estruturas_e_maquinas(ctx)
        if opts["vincular_acessos"]:
            n = cadastros.vincular_acessos(ctx)
            self.stdout.write(f"  {n} acessos às fazendas do seed concedidos.")

        self.stdout.write("Simulação mês a mês…")
        simulacao.montar_agenda(ctx)
        simulacao.rodar(ctx)

        self.stdout.write("Correções e exclusões com motivo…")
        extras.correcoes(ctx)
        self.stdout.write("Financeiro (programar, aprovar, baixar)…")
        financeiro.pagar_e_receber(ctx)
        extras.desfazer_uma_baixa(ctx)
        if not opts["manter_safras_abertas"]:
            extras.encerrar_safras(ctx)

    def _resumo(self, ctx):
        from apps.finance.models import Invoice, Payment
        from apps.procurement.models import Commitment
        from apps.purchases.models import Purchase
        from apps.sales.models import Sale

        farms = Farm.objects.filter(code__startswith=cat.PREFIXO)
        linhas = [
            ("Fazendas", farms.count()),
            ("Lotes", ctx.stats["lotes"]),
            (
                "Movimentos do rebanho",
                HerdMovement.objects.filter(
                    status="CONFIRMADA", origin_farm__in=farms
                ).count()
                + HerdMovement.objects.filter(
                    status="CONFIRMADA",
                    origin_farm__isnull=True,
                    destination_farm__in=farms,
                ).count(),
            ),
            ("Linhas no razão", HerdLedgerEntry.objects.filter(farm__in=farms).count()),
            (
                "Compras diretas e de operações",
                Purchase.objects.filter(destination_farm__in=farms).count(),
            ),
            (
                "Operações de compra (OP)",
                Commitment.objects.filter(destination_farm__in=farms).count(),
            ),
            ("Vendas e abates", Sale.objects.filter(farm__in=farms).count()),
            ("Títulos", Invoice.objects.filter(farm__in=farms).count()),
            ("Baixas", Payment.objects.filter(invoice__farm__in=farms).count()),
        ]
        self.stdout.write(self.style.SUCCESS("\nSeed concluído:"))
        for rotulo, valor in linhas:
            self.stdout.write(f"  {rotulo}: {valor}")
        saldo = HerdLedgerEntry.objects.filter(farm__in=farms).values_list(
            "quantity", flat=True
        )
        self.stdout.write(f"  Cabeças no rebanho do seed hoje: {sum(saldo)}")

        recusas = {k: v for k, v in ctx.stats.items() if k.startswith("falha:")}
        if recusas:
            self.stdout.write(
                self.style.WARNING("\nO sistema recusou (regra de negócio):")
            )
            for chave, n in sorted(recusas.items(), key=lambda kv: -kv[1]):
                nome = chave.removeprefix("falha:")
                exemplo = ctx.falhas[nome][0] if ctx.falhas[nome] else ""
                self.stdout.write(f"  {nome}: {n}×  ex.: {exemplo}")
        self.stdout.write(
            "\nPara desfazer: python manage.py desfazer_seed_operacao_grande"
        )
