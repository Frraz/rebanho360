"""O ciclo de compra (Fase 5): compromisso → viagem → recebimento →
classificação → acerto, até virar a compra de sempre.

Desenho em docs/arquitetura/adr/0008-ciclo-de-compra-por-composicao.md e
regra em docs/regras-negocio/08-ciclo-de-compra.md. Em uma frase: **nenhuma
tabela do núcleo foi alterada**. Cada item do compromisso gera uma `Purchase`
quando o acerto é aprovado; a etapa do ciclo é derivada, nunca gravada.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.managers import ScopedManager
from apps.core.reversible import ReversibleModel, Status

BAND_VALIDATORS = [MinValueValidator(1), MaxValueValidator(5)]


# --------------------------------------------------------------------------
# Base das linhas
# --------------------------------------------------------------------------


class ActiveLines(models.Manager):
    """Só as linhas que não saíram. O padrão: `commitment.items` e todo
    acesso reverso passam por aqui, sem lembrar de filtrar."""

    def get_queryset(self):
        return super().get_queryset().filter(removed_at__isnull=True)


class LineModel(models.Model):
    """Linha de um documento (item, carga, linha de romaneio, linha do
    acerto, nota fiscal). **Nunca sai do banco**: `removed_at` a tira da
    operação, e o `AuditEvent` guarda o que ela era (regra 5).

    Muda sempre pela operação do pai, com um motivo só — nunca solta.
    """

    removed_at = models.DateTimeField("Retirada em", null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Retirada por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField("Criada em", auto_now_add=True)

    objects = ActiveLines()
    all_objects = models.Manager()

    class Meta:
        abstract = True


# --------------------------------------------------------------------------
# Compromisso
# --------------------------------------------------------------------------


class Commitment(ReversibleModel):
    """O compromisso (contrato de compra). `RASCUNHO` = em negociação;
    `CONFIRMADA` = **aprovado**; a etapa seguinte (viagem, recebimento,
    acerto) é derivada em `selectors.etapa_do_compromisso`.

    A programação (retirada, abate, caminhões, distância) é campo daqui, não
    entidade: não tem ciclo de vida próprio (ADR 0008).
    """

    SCOPE_FARM_FIELD = "destination_farm"

    code = models.CharField("Código", max_length=30, unique=True)
    date = models.DateField("Data do movimento")
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra",
        related_name="commitments",
        on_delete=models.PROTECT,
    )
    seller = models.ForeignKey(
        "partners.Partner",
        verbose_name="Produtor",
        related_name="commitments_as_seller",
        on_delete=models.PROTECT,
    )
    destination_farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda de destino",
        related_name="commitments",
        on_delete=models.PROTECT,
    )
    commissioned = models.ForeignKey(
        "partners.Partner",
        verbose_name="Comprador (comissionado)",
        null=True,
        blank=True,
        related_name="commitments_as_commissioned",
        on_delete=models.PROTECT,
    )
    # `commissioned` é o comprador principal (o primeiro da lista). Os demais
    # compradores — sem limite — são linhas de `Commission`, cada uma com a sua
    # comissão (cliente, 2026-10-03, pendência #30).
    origin_property = models.CharField(
        "Propriedade de origem", max_length=150, blank=True
    )
    origin_city = models.CharField("Cidade de origem", max_length=100, blank=True)
    payment_days = models.PositiveSmallIntegerField(
        "Prazo de pagamento (dias)", null=True, blank=True
    )
    payment_condition = models.ForeignKey(
        "commercial.PaymentCondition",
        verbose_name="Condição de pagamento",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    # Programação
    pickup_date = models.DateField("Data da retirada", null=True, blank=True)
    slaughter_date = models.DateField("Data prevista do abate", null=True, blank=True)
    trucks = models.PositiveSmallIntegerField("Caminhões", null=True, blank=True)
    distance_km = models.PositiveIntegerField("Distância (km)", null=True, blank=True)
    notes = models.TextField("Observações", blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Aprovado por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    approved_at = models.DateTimeField("Aprovado em", null=True, blank=True)
    # Encerramento **manual** (cliente, 2026-10-03, pendência #29): o sistema
    # não decide que a operação acabou porque as contas foram pagas.
    closed_at = models.DateTimeField("Encerrada em", null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Encerrada por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    closure_note = models.CharField(
        "Observação do encerramento", max_length=300, blank=True
    )

    objects = ScopedManager()

    class Meta:
        verbose_name = "Compromisso"
        verbose_name_plural = "Compromissos"
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["season", "date"])]
        constraints = [
            models.CheckConstraint(
                check=Q(pickup_date__isnull=True)
                | Q(slaughter_date__isnull=True)
                | Q(slaughter_date__gte=models.F("pickup_date")),
                name="commitment_slaughter_after_pickup",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    @property
    def encerrada(self) -> bool:
        return self.closed_at is not None

    @property
    def commission(self):
        """A comissão do comprador principal (ou a primeira, se ele não tem).
        Consulta, não cache: a lista de comissões muda dentro da transação."""
        comissoes = list(self.commissions.order_by("position", "id"))
        for comissao in comissoes:
            if comissao.payee_id == self.commissioned_id:
                return comissao
        return comissoes[0] if comissoes else None

    # ---- contrato ReversibleModel (implementado em commitments.py) ------

    def bloqueios(self) -> list:
        from apps.procurement import commitments

        return commitments.bloqueios_do_compromisso(self)

    def dependentes(self) -> list:
        from apps.procurement import commitments

        return commitments.dependentes_do_compromisso(self)

    def descrever_efeitos(self) -> list[str]:
        from apps.procurement import commitments

        return commitments.descrever_efeitos_do_compromisso(self)

    def aplicar_efeitos(self, *, usuario):
        from apps.procurement import commitments

        commitments.aplicar_efeitos_do_compromisso(self, usuario=usuario)

    def desfazer_efeitos(self, *, usuario):
        """A aprovação não desfaz nada fora dela: o snapshot da comissão e quem
        aprovou ficam como estavam — são o registro do que foi acordado."""


class PriceBasis(models.TextChoices):
    ARROBA = "ARROBA", "@ de carcaça (por faixa)"
    CABECA = "CABECA", "Por cabeça"


class CommitmentItem(LineModel):
    """Um item do compromisso: uma categoria, cabeças, preço (por faixa de @
    ou por cabeça). Ao aprovar o acerto, vira **uma** `Purchase`."""

    commitment = models.ForeignKey(
        Commitment,
        verbose_name="Compromisso",
        related_name="items",
        on_delete=models.PROTECT,
    )
    number = models.PositiveSmallIntegerField("Item")
    category = models.ForeignKey(
        "livestock.AnimalCategory",
        verbose_name="Categoria",
        related_name="commitment_items",
        on_delete=models.PROTECT,
    )
    product_code = models.CharField("Código do produto", max_length=20, blank=True)
    head_count = models.PositiveIntegerField("Cabeças previstas")
    avg_weight_kg = models.DecimalField(
        "Peso médio previsto (kg)",
        max_digits=8,
        decimal_places=3,
        null=True,
        blank=True,
    )
    price_basis = models.CharField(
        "Base do preço",
        max_length=8,
        choices=PriceBasis.choices,
        default=PriceBasis.ARROBA,
    )
    unit_price = models.DecimalField(
        "Preço por cabeça (R$)", max_digits=14, decimal_places=2, null=True, blank=True
    )
    price_band_1 = models.DecimalField(
        "Faixa 1 (R$/@)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    price_band_2 = models.DecimalField(
        "Faixa 2 (R$/@)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    price_band_3 = models.DecimalField(
        "Faixa 3 (R$/@)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    price_band_4 = models.DecimalField(
        "Faixa 4 (R$/@)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    price_band_5 = models.DecimalField(
        "Faixa 5 (R$/@)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    # Para o "valor previsto" de um item por @: média @ prevista por cabeça e
    # a faixa esperada. Sem eles o previsto mostra "—" (não se inventa).
    expected_arrobas = models.DecimalField(
        "Média @ prevista por cabeça",
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
    )
    expected_band = models.PositiveSmallIntegerField(
        "Faixa esperada", null=True, blank=True, validators=BAND_VALIDATORS
    )
    # Rendimento de carcaça **estimado na entrada** (cliente, 2026-10-03, #15a):
    # editável; ~50% é a referência de uso, não um valor fixo do sistema.
    entry_yield_percent = models.DecimalField(
        "Rendimento estimado de entrada (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    lot = models.ForeignKey(
        "livestock.Lot",
        verbose_name="Lote existente",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
        help_text="Vazio = a compra cria um lote novo.",
    )
    # A única ligação do ciclo com o núcleo (ADR 0008).
    purchase = models.OneToOneField(
        "purchases.Purchase",
        verbose_name="Compra gerada",
        null=True,
        blank=True,
        related_name="commitment_item",
        on_delete=models.PROTECT,
    )

    class Meta:
        verbose_name = "Item do compromisso"
        verbose_name_plural = "Itens do compromisso"
        ordering = ["commitment_id", "number"]
        constraints = [
            models.CheckConstraint(
                check=Q(head_count__gt=0), name="commitmentitem_head_count_positive"
            ),
            models.UniqueConstraint(
                fields=["commitment", "number"],
                condition=Q(removed_at__isnull=True),
                name="uniq_commitmentitem_number_active",
            ),
            models.CheckConstraint(
                check=Q(expected_band__isnull=True)
                | (Q(expected_band__gte=1) & Q(expected_band__lte=5)),
                name="commitmentitem_expected_band_1_to_5",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.commitment.code} · item {self.number}"

    def preco_da_faixa(self, faixa: int | None) -> Decimal | None:
        if faixa is None or not 1 <= faixa <= 5:
            return None
        return getattr(self, f"price_band_{faixa}")


# --------------------------------------------------------------------------
# Comissão (snapshot da regra aplicada)
# --------------------------------------------------------------------------


class CommissionSource(models.TextChoices):
    REGRA = "REGRA", "Regra cadastrada"
    MANUAL = "MANUAL", "Informada neste compromisso"


class Commission(models.Model):
    """Comissão de **um comprador** do compromisso — há uma linha por comprador.

    Antes da aprovação é o que o usuário digita (tipo e valor por comprador);
    na aprovação, o comprador que ficou sem comissão informada recebe o
    **snapshot** da regra de `commercial.CommissionRule` vigente. Mudar o
    cadastro depois não toca esta linha. O **valor em reais não é gravado**: é
    derivado (regra 6), do snapshot e dos valores do acerto.

    Cada comprador tem o seu título de comissão, com **vencimento próprio**
    (`due_date`; vazio = a data do acerto).
    """

    commitment = models.ForeignKey(
        Commitment,
        verbose_name="Compromisso",
        related_name="commissions",
        on_delete=models.PROTECT,
    )
    payee = models.ForeignKey(
        "partners.Partner",
        verbose_name="Comprador",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    position = models.PositiveSmallIntegerField("Ordem", default=1)
    source = models.CharField(
        "Origem",
        max_length=8,
        choices=CommissionSource.choices,
        default=CommissionSource.REGRA,
    )
    # Rastro do cadastro de onde veio; a regra pode mudar ou sumir sem efeito aqui.
    rule = models.ForeignKey(
        "commercial.CommissionRule",
        verbose_name="Regra de origem",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.SET_NULL,
    )
    type = models.CharField("Tipo", max_length=12)
    base = models.CharField("Base", max_length=8, default="BRUTO")
    value = models.DecimalField(
        "Valor (%, R$ por cabeça ou R$)", max_digits=12, decimal_places=4
    )
    extra_amount = models.DecimalField(
        "Comissão extra (R$)", max_digits=14, decimal_places=2, default=0
    )
    due_date = models.DateField("Vencimento", null=True, blank=True)
    snapshot_at = models.DateTimeField("Gravada em", auto_now_add=True)

    class Meta:
        verbose_name = "Comissão do compromisso"
        verbose_name_plural = "Comissões dos compromissos"
        ordering = ["commitment_id", "position", "id"]
        constraints = [
            models.CheckConstraint(
                check=Q(value__gte=0), name="commission_value_not_negative"
            ),
            models.CheckConstraint(
                check=Q(extra_amount__gte=0), name="commission_extra_not_negative"
            ),
            models.UniqueConstraint(
                fields=["commitment", "payee"],
                condition=Q(payee__isnull=False),
                name="uniq_commission_buyer_per_commitment",
            ),
        ]

    def __str__(self) -> str:
        return f"Comissão de {self.commitment.code}"

    @property
    def aguarda_regra(self) -> bool:
        """Comprador sem valor informado, ainda sem a regra gravada (ela entra
        na aprovação do compromisso)."""
        return (
            self.source == CommissionSource.REGRA
            and self.rule_id is None
            and not self.value
            and not self.extra_amount
        )

    def regra_em_texto(self) -> str:
        """A regra **gravada**, como se lê na tela e nos relatórios."""
        from apps.core.formatting import dinheiro_br, numero_br

        if self.aguarda_regra:
            return "a regra vigente será gravada na aprovação"

        if self.type == "POR_CABECA":
            return f"R$ {numero_br(self.value, 2)} por cabeça"
        if self.type == "VALOR":
            return f"{dinheiro_br(self.value)} (valor informado)"
        return f"{numero_br(self.value, 2)}% sobre o valor bruto dos animais"


# --------------------------------------------------------------------------
# Viagem e embarque
# --------------------------------------------------------------------------


class FreightCriterion(models.TextChoices):
    POR_CABECA = "POR_CABECA", "Por cabeça"
    POR_KM = "POR_KM", "Por km rodado"
    POR_KG = "POR_KG", "Por kg de origem"
    POR_VIAGEM = "POR_VIAGEM", "Valor fechado da viagem"


class Trip(ReversibleModel):
    """Uma viagem (um caminhão). Um compromisso tem uma ou várias.

    O frete é daqui: critério e tarifa dão o **previsto** (derivado); o
    **realizado** é digitado. Não há entidade `Freight` à parte.
    """

    SCOPE_FARM_FIELD = "commitment__destination_farm"

    code = models.CharField("Código", max_length=30, unique=True)
    commitment = models.ForeignKey(
        Commitment,
        verbose_name="Compromisso",
        related_name="trips",
        on_delete=models.PROTECT,
    )
    pickup_date = models.DateField("Data da retirada")
    carrier = models.ForeignKey(
        "partners.Partner",
        verbose_name="Transportador",
        null=True,
        blank=True,
        related_name="trips",
        on_delete=models.PROTECT,
    )
    driver_name = models.CharField("Motorista", max_length=100, blank=True)
    vehicle = models.CharField("Veículo", max_length=100, blank=True)
    vehicle_plate = models.CharField("Placa", max_length=10, blank=True)
    # Só o número/código do ADF, sem anexo obrigatório (cliente, 2026-10-03, #34).
    adf_number = models.CharField("Número do ADF", max_length=40, blank=True)
    distance_km = models.PositiveIntegerField("Distância (km)", null=True, blank=True)
    freight_criterion = models.CharField(
        "Critério do frete",
        max_length=12,
        choices=FreightCriterion.choices,
        blank=True,
    )
    freight_rate = models.DecimalField(
        "Tarifa (R$)", max_digits=14, decimal_places=4, null=True, blank=True
    )
    freight_actual = models.DecimalField(
        "Frete realizado (R$)", max_digits=14, decimal_places=2, null=True, blank=True
    )
    # Vencimento próprio do título de frete, independente do dos animais.
    freight_due_date = models.DateField("Vencimento do frete", null=True, blank=True)
    notes = models.TextField("Observações", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Viagem"
        verbose_name_plural = "Viagens"
        ordering = ["pickup_date", "id"]
        constraints = [
            models.CheckConstraint(
                check=Q(freight_actual__isnull=True) | Q(freight_actual__gte=0),
                name="trip_freight_actual_not_negative",
            ),
            models.CheckConstraint(
                check=Q(freight_rate__isnull=True) | Q(freight_rate__gte=0),
                name="trip_freight_rate_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    def bloqueios(self) -> list:
        from apps.procurement import trips

        return trips.bloqueios_da_viagem(self)

    def dependentes(self) -> list:
        return list(self.receivings.exclude(status=Status.EXCLUIDA))

    def aplicar_efeitos(self, *, usuario):
        """Viagem não altera rebanho, custo nem título: o frete só entra no
        acerto. Nada a aplicar — nem a desfazer."""

    def desfazer_efeitos(self, *, usuario):
        """Simétrico a `aplicar_efeitos`."""


class TripLoad(LineModel):
    """O que a viagem leva de um item: programado × embarcado."""

    trip = models.ForeignKey(
        Trip, verbose_name="Viagem", related_name="loads", on_delete=models.PROTECT
    )
    item = models.ForeignKey(
        CommitmentItem,
        verbose_name="Item",
        related_name="loads",
        on_delete=models.PROTECT,
    )
    planned_qty = models.PositiveIntegerField("Cabeças programadas", default=0)
    shipped_qty = models.PositiveIntegerField(
        "Cabeças embarcadas", null=True, blank=True
    )
    origin_weight_kg = models.DecimalField(
        "Peso de origem (kg)", max_digits=12, decimal_places=3, null=True, blank=True
    )

    class Meta:
        verbose_name = "Carga da viagem"
        verbose_name_plural = "Cargas da viagem"
        ordering = ["trip_id", "item__number"]
        constraints = [
            models.UniqueConstraint(
                fields=["trip", "item"],
                condition=Q(removed_at__isnull=True),
                name="uniq_tripload_item_active",
            ),
            models.CheckConstraint(
                check=Q(origin_weight_kg__isnull=True) | Q(origin_weight_kg__gt=0),
                name="tripload_origin_weight_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.trip.code} · item {self.item.number}"


# --------------------------------------------------------------------------
# Recebimento
# --------------------------------------------------------------------------


class Receiving(ReversibleModel):
    """A chegada de uma viagem. **Uma por viagem** (a que não foi excluída)."""

    SCOPE_FARM_FIELD = "trip__commitment__destination_farm"

    code = models.CharField("Código", max_length=30, unique=True)
    trip = models.ForeignKey(
        Trip,
        verbose_name="Viagem",
        related_name="receivings",
        on_delete=models.PROTECT,
    )
    date = models.DateField("Data do recebimento")
    # **Digitada** (cliente, 2026-10-03): o sistema não calcula nem alerta a
    # quebra, e não desconta nada do valor dos animais. É informação da viagem,
    # usada nos relatórios.
    trip_loss_percent = models.DecimalField(
        "Quebra de viagem (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    notes = models.TextField("Ocorrências", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Recebimento"
        verbose_name_plural = "Recebimentos"
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["trip"],
                condition=~Q(status=Status.EXCLUIDA),
                name="uniq_receiving_per_trip",
            )
        ]

    def __str__(self) -> str:
        return self.code

    def bloqueios(self) -> list:
        from apps.procurement import receivings

        return receivings.bloqueios_do_recebimento(self)

    def aplicar_efeitos(self, *, usuario):
        """O animal só entra no rebanho quando o acerto é aprovado (ADR 0008,
        pendência #24). Receber não escreve no razão."""

    def desfazer_efeitos(self, *, usuario):
        """Simétrico a `aplicar_efeitos`."""


class ReceivingLine(LineModel):
    """O que chegou de uma carga: cabeças, peso, categoria e ocorrência."""

    receiving = models.ForeignKey(
        Receiving,
        verbose_name="Recebimento",
        related_name="lines",
        on_delete=models.PROTECT,
    )
    load = models.ForeignKey(
        TripLoad,
        verbose_name="Carga",
        related_name="received_lines",
        on_delete=models.PROTECT,
    )
    received_qty = models.PositiveIntegerField("Cabeças recebidas")
    received_weight_kg = models.DecimalField(
        "Peso recebido (kg)", max_digits=12, decimal_places=3, null=True, blank=True
    )
    received_category = models.ForeignKey(
        "livestock.AnimalCategory",
        verbose_name="Categoria recebida",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
        help_text="Só se for diferente da prevista.",
    )
    occurrence = models.CharField("Ocorrência", max_length=200, blank=True)

    class Meta:
        verbose_name = "Linha do recebimento"
        verbose_name_plural = "Linhas do recebimento"
        ordering = ["receiving_id", "load__item__number"]
        constraints = [
            models.UniqueConstraint(
                fields=["receiving", "load"],
                condition=Q(removed_at__isnull=True),
                name="uniq_receivingline_load_active",
            ),
            models.CheckConstraint(
                check=Q(received_weight_kg__isnull=True) | Q(received_weight_kg__gt=0),
                name="receivingline_weight_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.receiving.code} · {self.load}"


# --------------------------------------------------------------------------
# Classificação de carcaça — romaneio valorizado
# --------------------------------------------------------------------------


class GradingLine(LineModel):
    """Uma linha do romaneio valorizado: classificação × faixa. Média @,
    valor bruto, valor/kg e líquido **saem de `grading.py`**, nunca de campo."""

    item = models.ForeignKey(
        CommitmentItem,
        verbose_name="Item",
        related_name="gradings",
        on_delete=models.PROTECT,
    )
    carcass_class = models.ForeignKey(
        "commercial.CarcassClass",
        verbose_name="Classificação",
        related_name="+",
        on_delete=models.PROTECT,
    )
    band = models.PositiveSmallIntegerField("Faixa", validators=BAND_VALIDATORS)
    head_count = models.PositiveIntegerField("Cabeças")
    carcass_weight_kg = models.DecimalField(
        "Peso de carcaça (kg)", max_digits=12, decimal_places=3
    )
    # Copiado da faixa do contrato e editável: a diferença para o contratado
    # aparece no acerto (pendência #20).
    price_per_arroba = models.DecimalField(
        "Preço da @ (R$)", max_digits=12, decimal_places=4
    )
    discount_percent = models.DecimalField(
        "Desconto (%)", max_digits=5, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = "Linha do romaneio"
        verbose_name_plural = "Linhas do romaneio"
        ordering = ["item_id", "carcass_class__display_order", "band", "id"]
        constraints = [
            models.CheckConstraint(
                check=Q(band__gte=1) & Q(band__lte=5), name="gradingline_band_1_to_5"
            ),
            models.CheckConstraint(
                check=Q(head_count__gt=0), name="gradingline_head_count_positive"
            ),
            models.CheckConstraint(
                check=Q(carcass_weight_kg__gt=0), name="gradingline_weight_positive"
            ),
            models.CheckConstraint(
                check=Q(price_per_arroba__gt=0), name="gradingline_price_positive"
            ),
            models.CheckConstraint(
                check=Q(discount_percent__gte=0) & Q(discount_percent__lte=100),
                name="gradingline_discount_0_to_100",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item} · {self.carcass_class} · faixa {self.band}"


# --------------------------------------------------------------------------
# Acerto
# --------------------------------------------------------------------------


class Settlement(ReversibleModel):
    """O acerto do compromisso. `RASCUNHO` = em acerto; `CONFIRMADA` =
    **aprovado** (trava de fechamento: `bloqueios()`, não estado à parte).

    Aprovar cria e confirma **uma `Purchase` por item**. Totais, previsto ×
    realizado e rateio são derivados (`settlement.py`) — nada é gravado aqui.
    """

    SCOPE_FARM_FIELD = "commitment__destination_farm"

    code = models.CharField("Código", max_length=30, unique=True)
    commitment = models.ForeignKey(
        Commitment,
        verbose_name="Compromisso",
        related_name="settlements",
        on_delete=models.PROTECT,
    )
    date = models.DateField("Data do acerto")
    notes = models.TextField("Observações", blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Aprovado por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    approved_at = models.DateTimeField("Aprovado em", null=True, blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Acerto"
        verbose_name_plural = "Acertos"
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["commitment"],
                condition=~Q(status=Status.EXCLUIDA),
                name="uniq_settlement_per_commitment",
            )
        ]

    def __str__(self) -> str:
        return self.code

    def bloqueios(self) -> list:
        from apps.procurement import closing

        return closing.bloqueios_do_acerto(self)

    def dependentes(self) -> list:
        from apps.procurement import closing

        return closing.dependentes_do_acerto(self)

    def descrever_efeitos(self) -> list[str]:
        from apps.procurement import closing

        return closing.descrever_efeitos_do_acerto(self)

    def aplicar_efeitos(self, *, usuario):
        from apps.procurement import closing

        closing.aplicar_efeitos_do_acerto(self, usuario=usuario)

    def desfazer_efeitos(self, *, usuario):
        from apps.procurement import closing

        closing.desfazer_efeitos_do_acerto(self, usuario=usuario)


class SettlementLine(LineModel):
    """Tributo, taxa, desconto, adiantamento ou crédito — **valor digitado**
    (pendência #21). O efeito vem da natureza do tipo."""

    settlement = models.ForeignKey(
        Settlement,
        verbose_name="Acerto",
        related_name="lines",
        on_delete=models.PROTECT,
    )
    tax_type = models.ForeignKey(
        "commercial.TaxType",
        verbose_name="Tipo",
        related_name="+",
        on_delete=models.PROTECT,
    )
    amount = models.DecimalField("Valor (R$)", max_digits=14, decimal_places=2)
    # Campos auxiliares, **só de registro** (cliente, 2026-10-03, #14): o valor
    # digitado é a referência; alíquota e base não calculam nada.
    rate_percent = models.DecimalField(
        "Alíquota (%)", max_digits=7, decimal_places=4, null=True, blank=True
    )
    base_amount = models.DecimalField(
        "Base (R$)", max_digits=14, decimal_places=2, null=True, blank=True
    )
    # Quem recebe — informado pelo usuário, nunca deduzido.
    payee = models.ForeignKey(
        "partners.Partner",
        verbose_name="Favorecido",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    due_date = models.DateField("Vencimento", null=True, blank=True)
    reference = models.CharField("Documento", max_length=60, blank=True)
    notes = models.CharField("Observação", max_length=200, blank=True)

    class Meta:
        verbose_name = "Linha do acerto"
        verbose_name_plural = "Linhas do acerto"
        ordering = ["settlement_id", "id"]
        constraints = [
            models.CheckConstraint(
                check=Q(amount__gt=0), name="settlementline_amount_positive"
            )
        ]

    def __str__(self) -> str:
        return f"{self.settlement.code} · {self.tax_type}"


class FiscalNote(LineModel):
    """Nota fiscal **registrada** no acerto (o sistema não emite nota). Com
    nota registrada, reabrir o acerto é bloqueado: o documento fiscal já
    existe (regras-negocio/06#o-que-bloqueia)."""

    settlement = models.ForeignKey(
        Settlement,
        verbose_name="Acerto",
        related_name="fiscal_notes",
        on_delete=models.PROTECT,
    )
    number = models.CharField("Número", max_length=20)
    series = models.CharField("Série", max_length=5, blank=True)
    issue_date = models.DateField("Data de emissão")
    amount = models.DecimalField("Valor (R$)", max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "Nota fiscal"
        verbose_name_plural = "Notas fiscais"
        ordering = ["settlement_id", "issue_date", "number"]
        constraints = [
            models.CheckConstraint(
                check=Q(amount__gte=0), name="fiscalnote_amount_not_negative"
            ),
            models.UniqueConstraint(
                fields=["settlement", "number", "series"],
                condition=Q(removed_at__isnull=True),
                name="uniq_fiscalnote_number_active",
            ),
        ]

    def __str__(self) -> str:
        return f"NF {self.number}"


class SettlementAllocation(models.Model):
    """O que cada item recebe do frete, da comissão, dos tributos, dos
    descontos e dos adiantamentos do acerto — **informado pelo usuário**.

    O sistema não rateia sozinho (cliente, 2026-10-03, pendência #13): não
    decide se o rateio é por cabeça, por peso ou por valor. Com um único item
    recebido não há o que distribuir; com mais de um, cada total tem de ser
    repartido aqui e a soma tem de fechar com o total — senão o acerto não é
    aprovado, e a mensagem diz quanto falta.
    """

    settlement = models.ForeignKey(
        Settlement,
        verbose_name="Acerto",
        related_name="allocations",
        on_delete=models.CASCADE,
    )
    item = models.ForeignKey(
        CommitmentItem,
        verbose_name="Item",
        related_name="+",
        on_delete=models.PROTECT,
    )
    discount_value = models.DecimalField(
        "Descontos (R$)", max_digits=14, decimal_places=2, default=0
    )
    abatement_value = models.DecimalField(
        "Adiantamentos e créditos (R$)", max_digits=14, decimal_places=2, default=0
    )
    freight_value = models.DecimalField(
        "Frete (R$)", max_digits=14, decimal_places=2, default=0
    )
    commission_value = models.DecimalField(
        "Comissão (R$)", max_digits=14, decimal_places=2, default=0
    )
    tax_value = models.DecimalField(
        "Tributos e taxas (R$)", max_digits=14, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = "Distribuição do acerto por item"
        verbose_name_plural = "Distribuições do acerto por item"
        ordering = ["settlement_id", "item__number"]
        constraints = [
            models.UniqueConstraint(
                fields=["settlement", "item"], name="uniq_allocation_item"
            ),
            models.CheckConstraint(
                check=Q(discount_value__gte=0)
                & Q(abatement_value__gte=0)
                & Q(freight_value__gte=0)
                & Q(commission_value__gte=0)
                & Q(tax_value__gte=0),
                name="allocation_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.settlement.code} · item {self.item.number}"
