"""Validação de entrada vinda da web."""

from decimal import Decimal

from django import forms

from apps.core import context as ctx
from apps.costs.models import CostCenter, CostClass
from apps.livestock.models import Lot
from apps.partners.models import Partner
from apps.properties.models import Farm

ISO_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class CostCenterForm(forms.ModelForm):
    class Meta:
        model = CostCenter
        fields = ["name", "parent", "allocation_criterion", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Um centro não pode ser pai de si mesmo.
        pais = CostCenter.objects.filter(is_active=True)
        if self.instance.pk:
            pais = pais.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = pais


class CostEntryForm(forms.Form):
    """Fazenda, centro e classe são obrigatórios — mudança consciente em
    relação à planilha (docs/regras-negocio/02#obrigatoriedade...)."""

    date = forms.DateField(label="Data", widget=ISO_DATE, input_formats=["%Y-%m-%d"])
    farm = forms.ModelChoiceField(label="Fazenda", queryset=Farm.objects.none())
    cost_center = forms.ModelChoiceField(
        label="Centro de custo", queryset=CostCenter.objects.filter(is_active=True)
    )
    cost_class = forms.ModelChoiceField(
        label="Classe", queryset=CostClass.objects.filter(is_active=True)
    )
    amount = forms.DecimalField(
        label="Valor (R$)",
        min_value=Decimal("0.01"),
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
    )
    description = forms.CharField(label="Descrição", max_length=200)
    payer = forms.ModelChoiceField(
        label="Pagador",
        queryset=Partner.objects.filter(is_active=True),
        required=False,
    )
    lot = forms.ModelChoiceField(
        label="Lote (custo direto)",
        queryset=Lot.objects.none(),
        required=False,
        help_text="Deixe em branco para custo indireto — ele é rateado entre os lotes.",
    )
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )
        self.fields["lot"].queryset = (
            Lot.objects.for_user(user).exclude(status="EXCLUIDO")
            if user
            else Lot.objects.none()
        )


class CostEntryEditForm(CostEntryForm):
    edit_reason = forms.CharField(
        label="Motivo da correção",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Por que este lançamento está sendo corrigido.",
    )


class CostFilterForm(forms.Form):
    farm = forms.ModelChoiceField(
        label="Fazenda", queryset=Farm.objects.none(), required=False
    )
    cost_center = forms.ModelChoiceField(
        label="Centro", queryset=CostCenter.objects.all(), required=False
    )
    cost_class = forms.ModelChoiceField(
        label="Classe", queryset=CostClass.objects.all(), required=False
    )
    q = forms.CharField(label="Buscar", required=False)
    situacao = forms.ChoiceField(
        label="Situação",
        required=False,
        choices=[("CONFIRMADA", "Confirmados"), ("EXCLUIDA", "Excluídos")],
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )
