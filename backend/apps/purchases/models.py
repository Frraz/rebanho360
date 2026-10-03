"""Compra de gado do produtor — comprar bezerro para engordar.

Ver docs/regras-negocio/03-compra-de-gado.md. Não confundir com o ciclo
de compra do frigorífico (Fase 5).
"""

from django.db import models
from django.db.models import Q

from apps.core.managers import ScopedManager
from apps.core.reversible import ReversibleModel, Status


class Purchase(ReversibleModel):
    """A compra. Confirmar gera, na mesma transação, a entrada no rebanho
    e um lançamento de custo por valor preenchido — registrar uma vez,
    reaproveitar em todo o sistema.

    Custo de aquisição, média por cabeça, custo/@ e custo/kg **não são
    campos**: saem de `PurchaseCostService` (regra 6 do CLAUDE.md).
    """

    SCOPE_FARM_FIELD = "destination_farm"

    code = models.CharField("Código", max_length=30, unique=True)
    date = models.DateField("Data da compra")
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra",
        related_name="purchases",
        on_delete=models.PROTECT,
    )
    seller = models.ForeignKey(
        "partners.Partner",
        verbose_name="Vendedor",
        null=True,
        blank=True,
        related_name="sales_to_us",
        on_delete=models.PROTECT,
    )
    destination_farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda de destino",
        related_name="purchases",
        on_delete=models.PROTECT,
    )
    category = models.ForeignKey(
        "livestock.AnimalCategory",
        verbose_name="Categoria",
        related_name="purchases",
        on_delete=models.PROTECT,
    )
    head_count = models.PositiveIntegerField("Cabeças")
    # Opcional: nem toda compra é pesada na entrada (regra 03#peso-na-compra).
    total_weight_kg = models.DecimalField(
        "Peso total (kg)", max_digits=12, decimal_places=3, null=True, blank=True
    )
    animal_value = models.DecimalField(
        "Valor dos animais (R$)", max_digits=14, decimal_places=2
    )
    freight_value = models.DecimalField(
        "Frete (R$)", max_digits=14, decimal_places=2, default=0
    )
    # Digitada, sem cálculo automático — pendência #4 (Fase 5).
    commission_value = models.DecimalField(
        "Comissão (R$)", max_digits=14, decimal_places=2, default=0
    )
    tax_value = models.DecimalField(
        "Impostos (R$)", max_digits=14, decimal_places=2, default=0
    )
    lot = models.ForeignKey(
        "livestock.Lot",
        verbose_name="Lote",
        null=True,
        blank=True,
        related_name="purchases",
        on_delete=models.PROTECT,
    )
    # Só dá o vencimento do título que a confirmação gera (data + prazo). Vazio
    # = vence na data da compra. Pendência #16 (Fase 4).
    payment_days = models.PositiveSmallIntegerField(
        "Prazo de pagamento (dias)", null=True, blank=True
    )
    # Texto livre, preservado e sem efeito em cálculo — pendência #3.
    partnership = models.CharField("Parceria", max_length=100, blank=True)
    notes = models.TextField("Observações", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Compra"
        verbose_name_plural = "Compras"
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                check=Q(head_count__gt=0), name="purchase_head_count_positive"
            ),
            models.CheckConstraint(
                check=Q(animal_value__gt=0), name="purchase_animal_value_positive"
            ),
            models.CheckConstraint(
                check=Q(freight_value__gte=0)
                & Q(commission_value__gte=0)
                & Q(tax_value__gte=0),
                name="purchase_accessories_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    # ---- contrato ReversibleModel -------------------------------------

    def bloqueios(self) -> list:
        from apps.finance.selectors import bloqueios_financeiros_da_compra
        from apps.organizations.models import SeasonStatus

        bloqueios = []
        if self.season.status == SeasonStatus.ENCERRADA:
            bloqueios.append(
                f"a safra {self.season.name} está encerrada. Peça a um "
                "administrador para reabrir a safra antes de editar ou excluir."
            )
        # Pagamento baixado — da compra ou da venda do lote — bloqueia: o
        # dinheiro saiu de verdade (regras-negocio/06#o-que-bloqueia, F4-05).
        return [*bloqueios_financeiros_da_compra(self), *bloqueios]

    def dependentes(self) -> list:
        from apps.costs.models import CostEntry
        from apps.herd.models import HerdMovement, Weighing

        lot = self.lot
        if lot is None or lot.origin_purchase_id != self.pk:
            # Lote preexistente: nada "pertence" a esta compra. Se os animais
            # já saíram, a checagem de saldo bloqueia com a explicação.
            return []

        from apps.sales.models import Sale

        confirmada = Status.CONFIRMADA
        # O movimento que uma venda gerou **não** é dependente por conta
        # própria: ele se desfaz pelo documento de origem. Listá-lo (e
        # excluí-lo) deixaria a venda confirmada sem saída no rebanho.
        movimentos = (
            HerdMovement.objects.filter(
                status=confirmada,
                origin_purchase__isnull=True,
                origin_sale__isnull=True,
            )
            .filter(Q(origin_lot=lot) | Q(destination_lot=lot))
            .order_by("date", "id")
        )
        vendas = Sale.objects.filter(status=confirmada, lot=lot).order_by("date", "id")
        outras_compras = (
            Purchase.objects.filter(status=confirmada, lot=lot)
            .exclude(pk=self.pk)
            .order_by("date", "id")
        )
        pesagens = Weighing.objects.filter(status=confirmada, lot=lot).order_by(
            "date", "id"
        )
        custos = CostEntry.objects.filter(
            status=confirmada, lot=lot, source_purchase=None
        ).order_by("date", "id")
        return [*movimentos, *vendas, *outras_compras, *pesagens, *custos]

    def descrever_efeitos(self) -> list[str]:
        efeitos = []
        lote = self.lot.code if self.lot_id else "a ser criado"
        efeitos.append(
            f"entrada de {self.head_count} cabeças em {self.destination_farm}, "
            f"no lote {lote}"
        )
        for campo, centro, rotulo in (
            ("animal_value", "DESPESA GADO", "animais"),
            ("freight_value", "DESPESA GADO", "frete"),
            ("commission_value", "COMISSÃO", "comissão"),
            ("tax_value", "IMPOSTO E TAXAS", "impostos"),
        ):
            valor = getattr(self, campo)
            if valor and valor > 0:
                efeitos.append(f"R$ {valor} em {centro} ({rotulo})")
        if self.lot_id and self.lot.origin_purchase_id == self.pk:
            efeitos.append(
                f"o lote {self.lot.code} (criado por esta compra, se não tiver "
                "mais nada)"
            )
        from apps.finance.services import descrever_titulos_da_origem

        efeitos.extend(descrever_titulos_da_origem(self))
        return efeitos

    def aplicar_efeitos(self, *, usuario):
        from apps.purchases.services import aplicar_efeitos_da_compra

        aplicar_efeitos_da_compra(self, usuario=usuario)

    def desfazer_efeitos(self, *, usuario):
        from apps.purchases.services import desfazer_efeitos_da_compra

        desfazer_efeitos_da_compra(self, usuario=usuario)
