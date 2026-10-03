"""Validação de entrada vinda da web. As regras de negócio moram nos serviços;
o formulário garante tipos e formatos.

As linhas repetidas (itens, cargas, romaneio…) são `formset`s: a tela manda a
tabela inteira e o serviço decide o que é linha nova, o que mudou e o que foi
retirada (`lines.sincronizar_linhas`).
"""

from decimal import Decimal

from django import forms
from django.forms import BaseFormSet, formset_factory

from apps.commercial.models import CarcassClass, TaxType
from apps.core import context as ctx
from apps.livestock.models import AnimalCategory, Lot
from apps.partners.models import Partner, PartnerRoleChoice
from apps.procurement.models import (
    CommitmentItem,
    FreightCriterion,
    PriceBasis,
    TripLoad,
)


class LinhasFormSet(BaseFormSet):
    """Linha nunca sai do banco: "retirar" a tira do documento, e o que ela era
    fica na auditoria. O rótulo diz isso, em vez do "Apagar" padrão."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if "DELETE" in form.fields:
            form.fields["DELETE"].label = "Retirar esta linha"


ISO_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
FAIXAS = [(n, f"Faixa {n}") for n in range(1, 6)]


def _decimal(label, *, casas="0.01", obrigatorio=False, minimo=Decimal("0"), ajuda=""):
    return forms.DecimalField(
        label=label,
        required=obrigatorio,
        min_value=minimo,
        max_digits=14,
        decimal_places=len(casas.split(".")[1]),
        help_text=ajuda,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": casas}),
    )


def _inteiro(label, *, obrigatorio=False, minimo=0, ajuda=""):
    return forms.IntegerField(
        label=label,
        required=obrigatorio,
        min_value=minimo,
        help_text=ajuda,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )


def _parceiros(papeis):
    return Partner.objects.filter(is_active=True, roles__role__in=papeis).distinct()


# --------------------------------------------------------------------------
# Compromisso
# --------------------------------------------------------------------------


class CommitmentForm(forms.Form):
    date = forms.DateField(
        label="Data do movimento", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    seller = forms.ModelChoiceField(label="Produtor", queryset=Partner.objects.none())
    destination_farm = forms.ModelChoiceField(
        label="Fazenda de destino", queryset=Partner.objects.none()
    )
    commissioned = forms.ModelChoiceField(
        label="Comprador (comissionado)",
        queryset=Partner.objects.none(),
        required=False,
        help_text="Quem negociou e recebe a comissão. A regra vigente é gravada na aprovação.",
    )
    second_buyer = forms.ModelChoiceField(
        label="Comprador adicional",
        queryset=Partner.objects.none(),
        required=False,
        help_text="Só informativo: não divide a comissão.",
    )
    origin_property = forms.CharField(
        label="Propriedade de origem", max_length=150, required=False
    )
    origin_city = forms.CharField(
        label="Cidade de origem", max_length=100, required=False
    )
    payment_days = _inteiro(
        "Prazo de pagamento (dias)",
        ajuda="Dá o vencimento dos títulos gerados na aprovação do acerto.",
    )
    pickup_date = forms.DateField(
        label="Data da retirada",
        required=False,
        widget=ISO_DATE,
        input_formats=["%Y-%m-%d"],
    )
    slaughter_date = forms.DateField(
        label="Data prevista do abate",
        required=False,
        widget=ISO_DATE,
        input_formats=["%Y-%m-%d"],
    )
    trucks = _inteiro("Caminhões")
    distance_km = _inteiro("Distância (km)")
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["seller"].queryset = _parceiros(
            (PartnerRoleChoice.PRODUTOR, PartnerRoleChoice.FORNECEDOR)
        )
        self.fields["commissioned"].queryset = _parceiros(
            (PartnerRoleChoice.COMISSIONADO,)
        )
        self.fields["second_buyer"].queryset = _parceiros(
            (PartnerRoleChoice.COMISSIONADO,)
        )
        from apps.properties.models import Farm

        self.fields["destination_farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )

    def dados_limpos(self) -> dict:
        return {k: v for k, v in self.cleaned_data.items() if k != "edit_reason"}


class CommitmentEditForm(CommitmentForm):
    edit_reason = forms.CharField(
        label="Motivo da correção",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obrigatório em compromisso aprovado. Fica na auditoria.",
    )


class ItemForm(forms.Form):
    """Uma linha do compromisso. `id` vazio = item novo."""

    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    category = forms.ModelChoiceField(
        label="Categoria", queryset=AnimalCategory.objects.filter(is_active=True)
    )
    head_count = _inteiro("Cabeças previstas", obrigatorio=True, minimo=1)
    avg_weight_kg = _decimal("Peso médio previsto (kg)", casas="0.001")
    price_basis = forms.ChoiceField(
        label="Base do preço",
        choices=PriceBasis.choices,
        initial=PriceBasis.ARROBA,
        help_text="Por @ de carcaça usa as faixas e o romaneio; por cabeça, não.",
    )
    unit_price = _decimal("Preço por cabeça (R$)", ajuda="Só na base por cabeça.")
    price_band_1 = _decimal("Faixa 1 (R$/@)")
    price_band_2 = _decimal("Faixa 2 (R$/@)")
    price_band_3 = _decimal("Faixa 3 (R$/@)")
    price_band_4 = _decimal("Faixa 4 (R$/@)")
    price_band_5 = _decimal("Faixa 5 (R$/@)")
    expected_arrobas = _decimal(
        "Média @ prevista por cabeça",
        ajuda="Com a faixa esperada, dá o valor previsto. Sem eles, fica em branco.",
    )
    expected_band = forms.TypedChoiceField(
        label="Faixa esperada",
        choices=[("", "—")] + FAIXAS,
        coerce=int,
        empty_value=None,
        required=False,
    )
    lot = forms.ModelChoiceField(
        label="Lote existente",
        queryset=Lot.objects.none(),
        required=False,
        empty_label="Criar um lote novo",
    )
    product_code = forms.CharField(
        label="Código do produto", max_length=20, required=False
    )

    def __init__(self, *args, farm_lots=None, **kwargs):
        super().__init__(*args, **kwargs)
        if farm_lots is not None:
            self.fields["lot"].queryset = farm_lots


ItemFormSet = formset_factory(ItemForm, extra=0, can_delete=True, formset=LinhasFormSet)


def itens_iniciais(compromisso) -> list[dict]:
    return [
        {
            "id": i.pk,
            "category": i.category_id,
            "head_count": i.head_count,
            "avg_weight_kg": i.avg_weight_kg,
            "price_basis": i.price_basis,
            "unit_price": i.unit_price,
            "price_band_1": i.price_band_1,
            "price_band_2": i.price_band_2,
            "price_band_3": i.price_band_3,
            "price_band_4": i.price_band_4,
            "price_band_5": i.price_band_5,
            "expected_arrobas": i.expected_arrobas,
            "expected_band": i.expected_band,
            "lot": i.lot_id,
            "product_code": i.product_code,
        }
        for i in compromisso.items.order_by("number")
    ]


class CommissionForm(forms.Form):
    """Comissão informada neste compromisso, ou correção da gravada."""

    payee = forms.ModelChoiceField(
        label="Favorecido", queryset=Partner.objects.none(), required=False
    )
    type = forms.ChoiceField(
        label="Tipo",
        choices=[("PERCENTUAL", "Percentual"), ("POR_CABECA", "Valor por cabeça")],
    )
    base = forms.ChoiceField(
        label="Base do percentual",
        choices=[
            ("BRUTO", "Valor bruto dos animais"),
            ("LIQUIDO", "Valor líquido (sem frete e tributos)"),
        ],
        help_text="Só vale para percentual. Pendência #4: bruto ou líquido?",
    )
    value = forms.DecimalField(
        label="Valor (% ou R$ por cabeça)",
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.0001"}),
    )
    extra_amount = _decimal(
        "Comissão extra (R$)", ajuda="Somada ao valor calculado, sem regra."
    )
    reason = forms.CharField(
        label="Motivo",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obrigatório para corrigir a comissão que já existe.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payee"].queryset = _parceiros((PartnerRoleChoice.COMISSIONADO,))


# --------------------------------------------------------------------------
# Viagem e recebimento
# --------------------------------------------------------------------------


class TripForm(forms.Form):
    pickup_date = forms.DateField(
        label="Data da retirada", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    carrier = forms.ModelChoiceField(
        label="Transportador", queryset=Partner.objects.none(), required=False
    )
    driver_name = forms.CharField(label="Motorista", max_length=100, required=False)
    vehicle_plate = forms.CharField(
        label="Placa",
        max_length=10,
        required=False,
        widget=forms.TextInput(attrs={"autocapitalize": "characters"}),
    )
    distance_km = _inteiro("Distância (km)")
    freight_criterion = forms.ChoiceField(
        label="Critério do frete",
        choices=[("", "Sem frete")] + FreightCriterion.choices,
        required=False,
    )
    freight_rate = _decimal(
        "Tarifa (R$)",
        casas="0.0001",
        ajuda="Por cabeça, por km, por kg ou o valor fechado da viagem — conforme o critério.",
    )
    freight_actual = _decimal(
        "Frete realizado (R$)",
        ajuda="O que foi cobrado de fato. Sem ele, o acerto usa o previsto.",
    )
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["carrier"].queryset = _parceiros((PartnerRoleChoice.TRANSPORTADOR,))

    def dados_limpos(self) -> dict:
        return {k: v for k, v in self.cleaned_data.items() if k != "edit_reason"}


class TripEditForm(TripForm):
    edit_reason = forms.CharField(
        label="Motivo da correção",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class LoadForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    item = forms.ModelChoiceField(label="Item", queryset=CommitmentItem.objects.none())
    planned_qty = _inteiro("Cabeças programadas")
    shipped_qty = _inteiro("Cabeças embarcadas")
    origin_weight_kg = _decimal("Peso de origem (kg)", casas="0.001")

    def __init__(self, *args, itens=None, **kwargs):
        super().__init__(*args, **kwargs)
        if itens is not None:
            self.fields["item"].queryset = itens
            self.fields["item"].label_from_instance = lambda i: (
                f"Item {i.number} · {i.category.name}"
            )


LoadFormSet = formset_factory(LoadForm, extra=0, can_delete=True, formset=LinhasFormSet)


def cargas_iniciais(viagem) -> list[dict]:
    return [
        {
            "id": c.pk,
            "item": c.item_id,
            "planned_qty": c.planned_qty,
            "shipped_qty": c.shipped_qty,
            "origin_weight_kg": c.origin_weight_kg,
        }
        for c in viagem.loads.select_related("item")
    ]


class ReceivingForm(forms.Form):
    date = forms.DateField(
        label="Data do recebimento", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    notes = forms.CharField(
        label="Ocorrências",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="O que aconteceu na viagem: animal caído, atraso, divergência.",
    )
    edit_reason = forms.CharField(
        label="Motivo da correção",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class ReceivingLineForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    load = forms.ModelChoiceField(label="Item", queryset=TripLoad.objects.none())
    received_qty = _inteiro("Cabeças recebidas", obrigatorio=True)
    received_weight_kg = _decimal("Peso recebido (kg)", casas="0.001")
    received_category = forms.ModelChoiceField(
        label="Categoria recebida",
        queryset=AnimalCategory.objects.filter(is_active=True),
        required=False,
        empty_label="A prevista",
        help_text="Só se chegou categoria diferente.",
    )
    occurrence = forms.CharField(label="Ocorrência", max_length=200, required=False)

    def __init__(self, *args, cargas=None, **kwargs):
        super().__init__(*args, **kwargs)
        if cargas is not None:
            self.fields["load"].queryset = cargas
            self.fields["load"].label_from_instance = lambda c: (
                f"Item {c.item.number} · {c.item.category.name}"
                + (f" · embarcou {c.shipped_qty}" if c.shipped_qty is not None else "")
            )


ReceivingLineFormSet = formset_factory(
    ReceivingLineForm, extra=0, can_delete=True, formset=LinhasFormSet
)


def linhas_de_recebimento_iniciais(recebimento) -> list[dict]:
    return [
        {
            "id": linha.pk,
            "load": linha.load_id,
            "received_qty": linha.received_qty,
            "received_weight_kg": linha.received_weight_kg,
            "received_category": linha.received_category_id,
            "occurrence": linha.occurrence,
        }
        for linha in recebimento.lines.select_related("load")
    ]


# --------------------------------------------------------------------------
# Romaneio
# --------------------------------------------------------------------------


class GradingLineForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    carcass_class = forms.ModelChoiceField(
        label="Classificação", queryset=CarcassClass.objects.none()
    )
    band = forms.TypedChoiceField(label="Faixa", choices=FAIXAS, coerce=int)
    head_count = _inteiro("Cabeças", obrigatorio=True, minimo=1)
    carcass_weight_kg = _decimal(
        "Peso de carcaça (kg)", casas="0.001", obrigatorio=True, minimo=Decimal("0.001")
    )
    price_per_arroba = _decimal(
        "Preço da @ (R$)",
        casas="0.0001",
        ajuda="Vazio = o preço da faixa no contrato.",
    )
    discount_percent = _decimal("Desconto (%)")

    def __init__(self, *args, classes=None, **kwargs):
        super().__init__(*args, **kwargs)
        if classes is not None:
            self.fields["carcass_class"].queryset = classes


GradingLineFormSet = formset_factory(
    GradingLineForm, extra=0, can_delete=True, formset=LinhasFormSet
)


def linhas_de_romaneio_iniciais(item) -> list[dict]:
    return [
        {
            "id": g.pk,
            "carcass_class": g.carcass_class_id,
            "band": g.band,
            "head_count": g.head_count,
            "carcass_weight_kg": g.carcass_weight_kg,
            "price_per_arroba": g.price_per_arroba,
            "discount_percent": g.discount_percent,
        }
        for g in item.gradings.all()
    ]


# --------------------------------------------------------------------------
# Acerto
# --------------------------------------------------------------------------


class SettlementForm(forms.Form):
    date = forms.DateField(
        label="Data do acerto", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class SettlementLineForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    tax_type = forms.ModelChoiceField(label="Tipo", queryset=TaxType.objects.none())
    amount = _decimal(
        "Valor (R$)",
        obrigatorio=True,
        minimo=Decimal("0.01"),
        ajuda="Digitado: não há cálculo.",
    )
    reference = forms.CharField(label="Documento", max_length=60, required=False)
    notes = forms.CharField(label="Observação", max_length=200, required=False)

    def __init__(self, *args, tipos=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tipos is not None:
            self.fields["tax_type"].queryset = tipos
            self.fields["tax_type"].label_from_instance = lambda t: (
                f"{t.name} ({t.get_nature_display().lower()})"
            )


SettlementLineFormSet = formset_factory(
    SettlementLineForm, extra=0, can_delete=True, formset=LinhasFormSet
)


def linhas_do_acerto_iniciais(acerto) -> list[dict]:
    return [
        {
            "id": linha.pk,
            "tax_type": linha.tax_type_id,
            "amount": linha.amount,
            "reference": linha.reference,
            "notes": linha.notes,
        }
        for linha in acerto.lines.select_related("tax_type")
    ]


class FiscalNoteForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    number = forms.CharField(label="Número", max_length=20)
    series = forms.CharField(label="Série", max_length=5, required=False)
    issue_date = forms.DateField(
        label="Emissão", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    amount = _decimal("Valor (R$)", obrigatorio=True)


FiscalNoteFormSet = formset_factory(
    FiscalNoteForm, extra=0, can_delete=True, formset=LinhasFormSet
)


def notas_iniciais(acerto) -> list[dict]:
    return [
        {
            "id": n.pk,
            "number": n.number,
            "series": n.series,
            "issue_date": n.issue_date,
            "amount": n.amount,
        }
        for n in acerto.fiscal_notes.all()
    ]


class ReasonForm(forms.Form):
    """Motivo único de uma operação sobre linhas já confirmadas."""

    reason = forms.CharField(
        label="Motivo da correção",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obrigatório ao corrigir ou retirar linhas que já existiam. Fica na auditoria.",
    )


# --------------------------------------------------------------------------
# Do formset para o que o serviço espera
# --------------------------------------------------------------------------


def entradas_do_formset(formset, *, descartar=("DELETE",)) -> list[dict]:
    """As linhas que ficam: sem as marcadas "Retirar", sem as extras em branco.
    O serviço trata o que não veio como linha retirada."""
    entradas = []
    for form in formset.forms:
        if form in formset.deleted_forms:
            continue
        dados = {k: v for k, v in form.cleaned_data.items() if k not in descartar}
        if not dados.get("id") and not form.has_changed():
            continue
        dados["id"] = dados.get("id") or None
        entradas.append(dados)
    return entradas
