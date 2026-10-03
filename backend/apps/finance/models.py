"""Títulos e baixas — o dinheiro que entra e sai de verdade.

Ver docs/regras-negocio/07-financeiro.md e docs/fluxos/02-maquinas-de-estado.md.

Dois ciclos de vida, de propósito separados:

- `status` (herdado de `ReversibleModel`): o ciclo do **registro** — o título
  nasce `CONFIRMADA` e pode ser `EXCLUIDA` (cancelado) e restaurado. Não existe
  `CANCELADO` à parte: exclusão cobre o caso (regras-negocio/06).
- `payment_status`: o ciclo do **dinheiro** — `A_PAGAR → PROGRAMADO →
  APROVADO → PARCIAL/PAGO`. É o que a máquina de estados da Fase 4 descreve.
"""

import datetime
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum

from apps.core.exceptions import Bloqueio
from apps.core.managers import ScopedManager
from apps.core.reversible import ReversibleModel, Status


class Direction(models.TextChoices):
    PAGAR = "PAGAR", "A pagar"
    RECEBER = "RECEBER", "A receber"


class PaymentStatus(models.TextChoices):
    # Os códigos são os do vocabulário (modelo-dados/02). Em título a receber
    # o mesmo código ganha outro rótulo: ver `Invoice.situacao_rotulo`.
    A_PAGAR = "A_PAGAR", "A pagar"
    PROGRAMADO = "PROGRAMADO", "Programado"
    APROVADO = "APROVADO", "Aprovado"
    PARCIAL = "PARCIAL", "Pago em parte"
    PAGO = "PAGO", "Pago"


#: O que ainda falta receber ou pagar.
SITUACOES_EM_ABERTO = (
    PaymentStatus.A_PAGAR,
    PaymentStatus.PROGRAMADO,
    PaymentStatus.APROVADO,
    PaymentStatus.PARCIAL,
)

ROTULOS_A_RECEBER = {
    PaymentStatus.A_PAGAR: "A receber",
    PaymentStatus.PROGRAMADO: "Programado",
    PaymentStatus.APROVADO: "Aprovado",
    PaymentStatus.PARCIAL: "Recebido em parte",
    PaymentStatus.PAGO: "Recebido",
}


class Component(models.TextChoices):
    """De onde vem a obrigação. Junto com a operação de origem, é a chave de
    idempotência: a mesma compra não gera dois títulos de frete."""

    ANIMAIS = "ANIMAIS", "Animais"
    FRETE = "FRETE", "Frete"
    COMISSAO = "COMISSAO", "Comissão"
    IMPOSTOS = "IMPOSTOS", "Impostos"
    VENDA = "VENDA", "Venda"
    OUTRO = "OUTRO", "Outro"


COMPONENTES_A_PAGAR = (
    Component.ANIMAIS,
    Component.FRETE,
    Component.COMISSAO,
    Component.IMPOSTOS,
    Component.OUTRO,
)
COMPONENTES_A_RECEBER = (Component.VENDA, Component.OUTRO)


class PaymentMethod(models.TextChoices):
    PIX = "PIX", "Pix"
    TED = "TED", "TED / transferência"
    BOLETO = "BOLETO", "Boleto"
    CHEQUE = "CHEQUE", "Cheque"
    DINHEIRO = "DINHEIRO", "Dinheiro"
    OUTRO = "OUTRO", "Outro"


class Invoice(ReversibleModel):
    """O título: uma obrigação de pagar (compra, frete…) ou um direito de
    receber (venda), com valor e vencimento.

    Nunca guarda dado bancário: aponta para a `BankAccount` do favorecido —
    "dados bancários nunca são redigitados" (F4-01). Quanto já foi pago, quanto
    falta e se está vencido **não são campos**: saem das baixas (regra 6).
    """

    code = models.CharField("Código", max_length=30, unique=True)
    direction = models.CharField(
        "Tipo", max_length=10, choices=Direction.choices, default=Direction.PAGAR
    )
    component = models.CharField(
        "Origem da obrigação",
        max_length=10,
        choices=Component.choices,
        default=Component.OUTRO,
    )
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra",
        related_name="invoices",
        on_delete=models.PROTECT,
    )
    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="invoices",
        on_delete=models.PROTECT,
    )
    # Nulo quando a operação não diz para quem (compra sem vendedor; frete,
    # comissão e impostos). Título sem favorecido existe, mas não é programado.
    payee = models.ForeignKey(
        "partners.Partner",
        verbose_name="Favorecido",
        null=True,
        blank=True,
        related_name="invoices",
        on_delete=models.PROTECT,
    )
    bank_account = models.ForeignKey(
        "partners.BankAccount",
        verbose_name="Conta bancária",
        null=True,
        blank=True,
        related_name="invoices",
        on_delete=models.PROTECT,
    )
    origin_purchase = models.ForeignKey(
        "purchases.Purchase",
        verbose_name="Compra de origem",
        null=True,
        blank=True,
        related_name="invoices",
        on_delete=models.PROTECT,
    )
    origin_sale = models.ForeignKey(
        "sales.Sale",
        verbose_name="Venda de origem",
        null=True,
        blank=True,
        related_name="invoices",
        on_delete=models.PROTECT,
    )
    # Frete (por viagem), comissão (por comprador) e tributos (por linha) nascem
    # do **acerto**, não da compra: cada obrigação tem favorecido e vencimento
    # próprios (cliente, 2026-10-03, #17 e #18).
    origin_settlement = models.ForeignKey(
        "procurement.Settlement",
        verbose_name="Acerto de origem",
        null=True,
        blank=True,
        related_name="invoices",
        on_delete=models.PROTECT,
    )
    # Distingue vários títulos do mesmo componente na mesma origem: `viagem:12`,
    # `comissao:3`, `linha:7`, `parcela:2`. Vazio = o título único de sempre.
    ref = models.CharField("Referência", max_length=30, blank=True, default="")
    document = models.CharField(
        "Documento",
        max_length=60,
        blank=True,
        help_text="Nota fiscal, duplicata, contrato…",
    )
    issue_date = models.DateField("Emissão")
    due_date = models.DateField("Vencimento")
    amount = models.DecimalField("Valor (R$)", max_digits=14, decimal_places=2)

    payment_status = models.CharField(
        "Situação do pagamento",
        max_length=12,
        choices=PaymentStatus.choices,
        default=PaymentStatus.A_PAGAR,
    )
    scheduled_date = models.DateField(
        "Pagamento programado para", null=True, blank=True
    )
    scheduled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Programado por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Aprovado por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    approved_at = models.DateTimeField("Aprovado em", null=True, blank=True)
    # Verdadeiro quando o título saiu junto com a operação (compra/venda
    # excluída ou em correção). É o que separa "cancelei este título" de
    # "ele foi desfeito com a compra" — só o segundo volta sozinho quando a
    # compra é restaurada.
    voided_with_origin = models.BooleanField("Desfeito com a origem", default=False)
    notes = models.TextField("Observações", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Título"
        verbose_name_plural = "Títulos"
        ordering = ["due_date", "id"]
        constraints = [
            models.CheckConstraint(
                check=Q(amount__gt=0), name="invoice_amount_positive"
            ),
            models.CheckConstraint(
                check=Q(due_date__gte=models.F("issue_date")),
                name="invoice_due_after_issue",
            ),
            models.CheckConstraint(
                # No máximo uma origem: compra, venda ou acerto.
                check=(Q(origin_purchase__isnull=True) & Q(origin_sale__isnull=True))
                | (Q(origin_purchase__isnull=True) & Q(origin_settlement__isnull=True))
                | (Q(origin_sale__isnull=True) & Q(origin_settlement__isnull=True)),
                name="invoice_single_origin",
            ),
            # A chave de idempotência (F4-02): uma obrigação por operação e
            # componente. Confirmar duas vezes — ou duas pessoas ao mesmo
            # tempo — não gera dois títulos; o banco é quem garante.
            models.UniqueConstraint(
                fields=["origin_purchase", "component", "ref"],
                condition=Q(origin_purchase__isnull=False),
                name="uniq_invoice_purchase_component",
            ),
            models.UniqueConstraint(
                fields=["origin_sale", "component", "ref"],
                condition=Q(origin_sale__isnull=False),
                name="uniq_invoice_sale_component",
            ),
            models.UniqueConstraint(
                fields=["origin_settlement", "component", "ref"],
                condition=Q(origin_settlement__isnull=False),
                name="uniq_invoice_settlement_component",
            ),
        ]
        indexes = [
            models.Index(fields=["farm", "season"]),
            models.Index(fields=["due_date", "payment_status"]),
        ]

    def __str__(self) -> str:
        return self.code

    # ---- derivados: nunca gravados ------------------------------------

    @property
    def a_receber(self) -> bool:
        return self.direction == Direction.RECEBER

    @property
    def paid_total(self) -> Decimal:
        # Lista já anotada por `selectors` evita uma consulta por linha.
        if hasattr(self, "paid_sum"):
            return Decimal(self.paid_sum or 0)
        total = self.payments.filter(status=Status.CONFIRMADA).aggregate(
            t=Sum("amount")
        )["t"]
        return total or Decimal("0")

    @property
    def balance(self) -> Decimal:
        return self.amount - self.paid_total

    @property
    def em_aberto(self) -> bool:
        return (
            self.status == Status.CONFIRMADA
            and self.payment_status in SITUACOES_EM_ABERTO
        )

    def vencido(self, hoje: datetime.date | None = None) -> bool:
        hoje = hoje or datetime.date.today()
        return self.em_aberto and self.due_date < hoje

    @property
    def situacao_rotulo(self) -> str:
        if self.status == Status.EXCLUIDA:
            return "Cancelado"
        if self.a_receber:
            return ROTULOS_A_RECEBER[self.payment_status]
        return self.get_payment_status_display()

    @property
    def favorecido_rotulo(self) -> str:
        return "Cliente" if self.a_receber else "Favorecido"

    @property
    def origem(self):
        return self.origin_purchase or self.origin_sale or self.origin_settlement

    # ---- contrato ReversibleModel -------------------------------------

    def baixas_ativas(self):
        return self.payments.filter(status=Status.CONFIRMADA).order_by("date", "id")

    def bloqueios(self) -> list:
        from django.urls import reverse

        from apps.core.formatting import dinheiro_br
        from apps.organizations.models import SeasonStatus

        bloqueios = []
        for baixa in self.baixas_ativas():
            verbo = "recebimento" if self.a_receber else "pagamento"
            bloqueios.append(
                Bloqueio(
                    f"o título {self.code} já tem {verbo} baixado em "
                    f"{baixa.date:%d/%m/%Y} ({dinheiro_br(baixa.amount)}). "
                    f"Para prosseguir, desfaça antes a baixa do {verbo} {baixa.code}.",
                    reverse("finance:pagamento_detalhe", args=[baixa.pk]),
                    f"Ir para o {verbo}",
                )
            )
        if self.season.status == SeasonStatus.ENCERRADA:
            bloqueios.append(
                f"a safra {self.season.name} está encerrada. Peça a um "
                "administrador para reabrir a safra antes de editar ou excluir."
            )
        return bloqueios

    def dependentes(self) -> list:
        # Baixa não é dependente reversível: dinheiro que saiu bloqueia.
        return []

    def descrever_efeitos(self) -> list[str]:
        from apps.core.formatting import dinheiro_br

        quem = f" · {self.payee}" if self.payee_id else ""
        efeitos = [
            f"o título {self.code} ({dinheiro_br(self.amount)}{quem}) deixa de "
            "constar em contas a "
            f"{'receber' if self.a_receber else 'pagar'} e no fluxo de caixa"
        ]
        if self.payment_status in (PaymentStatus.PROGRAMADO, PaymentStatus.APROVADO):
            efeitos.append("a programação e a aprovação deste título deixam de valer")
        return efeitos

    def aplicar_efeitos(self, *, usuario):
        """O título não produz efeito em outro registro: ele **é** o efeito
        da compra ou da venda."""

    def desfazer_efeitos(self, *, usuario):
        """Simétrico a `aplicar_efeitos`: nada a desfazer fora dele."""


class Payment(ReversibleModel):
    """A baixa: dinheiro que saiu (ou entrou) para quitar um título, no todo
    ou em parte.

    Idempotente por `(título, documento)`: o documento é o comprovante (nº da
    TED, id do Pix, nº do cheque). Clique duplo — ou duas abas — chega ao mesmo
    documento e a segunda baixa é recusada, no serviço e no banco.

    Desfazer a baixa é a **única exceção** ao "tudo é editável": desfazer aqui
    não desfaz a transferência no banco. Por isso é de `FINANCEIRO`/`ADMIN`,
    com motivo, e enquanto a baixa existe ela bloqueia tudo a montante.
    """

    SCOPE_FARM_FIELD = "invoice__farm"

    code = models.CharField("Código", max_length=30, unique=True)
    invoice = models.ForeignKey(
        Invoice,
        verbose_name="Título",
        related_name="payments",
        on_delete=models.PROTECT,
    )
    date = models.DateField("Data do pagamento")
    amount = models.DecimalField("Valor (R$)", max_digits=14, decimal_places=2)
    method = models.CharField(
        "Forma", max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.PIX
    )
    document = models.CharField(
        "Documento de pagamento",
        max_length=60,
        help_text="Comprovante: nº da TED, ID do Pix, nº do cheque…",
    )
    notes = models.TextField("Observações", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Baixa"
        verbose_name_plural = "Baixas"
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                check=Q(amount__gt=0), name="payment_amount_positive"
            ),
            models.CheckConstraint(
                check=~Q(document=""), name="payment_document_required"
            ),
            # A chave de idempotência da baixa (F4-04). Baixa desfeita sai da
            # chave — senão não haveria como lançar de novo, certo.
            models.UniqueConstraint(
                fields=["invoice", "document"],
                condition=~Q(status="EXCLUIDA"),
                name="uniq_payment_invoice_document",
            ),
        ]
        indexes = [models.Index(fields=["date"])]

    def __str__(self) -> str:
        return self.code

    @property
    def a_receber(self) -> bool:
        return self.invoice.direction == Direction.RECEBER

    @property
    def verbo(self) -> str:
        return "Recebimento" if self.a_receber else "Pagamento"

    # ---- contrato ReversibleModel -------------------------------------

    def bloqueios(self) -> list[str]:
        from apps.organizations.models import SeasonStatus

        if self.invoice.season.status == SeasonStatus.ENCERRADA:
            return [
                f"a safra {self.invoice.season.name} está encerrada. Peça a um "
                "administrador para reabrir a safra antes de desfazer a baixa."
            ]
        return []

    def dependentes(self) -> list:
        return []

    def descrever_efeitos(self) -> list[str]:
        from apps.core.formatting import dinheiro_br

        return [
            f"{dinheiro_br(self.amount)} voltam a constar como em aberto no título "
            f"{self.invoice.code}",
            "o sistema não desfaz a transferência no banco: confira o extrato "
            "e providencie o estorno ou a devolução fora do sistema",
        ]

    def aplicar_efeitos(self, *, usuario):
        from apps.finance.services import recalcular_situacao

        recalcular_situacao(self.invoice_id, incluir=self)

    def desfazer_efeitos(self, *, usuario):
        from apps.finance.services import recalcular_situacao

        recalcular_situacao(self.invoice_id, excluir=self)


__all__ = [
    "Invoice",
    "Payment",
    "Direction",
    "PaymentStatus",
    "Component",
    "PaymentMethod",
    "Status",
]
