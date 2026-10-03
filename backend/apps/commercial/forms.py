"""Validação de entrada vinda da web."""

from decimal import Decimal

from django import forms

from apps.commercial.models import (
    CarcassClass,
    CommissionRule,
    CommissionType,
    PaymentCondition,
    TaxType,
    parse_prazos,
)
from apps.livestock.models import AnimalCategory
from apps.partners.models import Partner, PartnerRoleChoice

ISO_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class CarcassClassForm(forms.ModelForm):
    class Meta:
        model = CarcassClass
        fields = ["code", "name", "display_order", "default_band", "is_active"]
        widgets = {"code": forms.TextInput(attrs={"autocapitalize": "characters"})}

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class TaxTypeForm(forms.ModelForm):
    class Meta:
        model = TaxType
        fields = ["name", "nature", "effect", "display_order", "is_active"]


class CommissionRuleForm(forms.ModelForm):
    class Meta:
        model = CommissionRule
        fields = [
            "commissioned",
            "category",
            "type",
            "base",
            "value",
            "valid_from",
            "valid_to",
            "is_active",
            "notes",
        ]
        widgets = {
            "valid_from": ISO_DATE,
            "valid_to": ISO_DATE,
            "value": forms.NumberInput(
                attrs={"inputmode": "decimal", "step": "0.0001"}
            ),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["commissioned"].queryset = Partner.objects.filter(
            is_active=True, roles__role=PartnerRoleChoice.COMISSIONADO
        ).distinct()
        self.fields["category"].queryset = AnimalCategory.objects.filter(is_active=True)
        self.fields["valid_from"].input_formats = ["%Y-%m-%d"]
        self.fields["valid_to"].input_formats = ["%Y-%m-%d"]
        # Respostas do cliente (2026-10-03): a base do percentual é o valor bruto
        # dos animais; e o valor direto (R$) é informado na operação, não em regra.
        self.fields["base"].choices = [
            (v, r) for v, r in self.fields["base"].choices if v == "BRUTO"
        ]
        self.fields["base"].help_text = "Percentual × valor bruto dos animais."
        self.fields["type"].choices = [
            (v, r) for v, r in self.fields["type"].choices if v != CommissionType.VALOR
        ]

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("valid_from"), dados.get("valid_to")
        if inicio and fim and fim < inicio:
            self.add_error("valid_to", "A vigência não pode terminar antes de começar.")
        valor = dados.get("value")
        if valor is not None and valor <= 0:
            self.add_error("value", "O valor deve ser maior que zero.")
        if (
            dados.get("type") == CommissionType.PERCENTUAL
            and valor is not None
            and valor > Decimal("100")
        ):
            self.add_error("value", "Um percentual não passa de 100.")
        return dados


class PaymentConditionForm(forms.ModelForm):
    class Meta:
        model = PaymentCondition
        fields = ["name", "days", "display_order", "is_active"]

    def clean_days(self):
        texto = self.cleaned_data["days"].replace(" ", "")
        try:
            prazos = parse_prazos(texto)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if prazos[-1] > 3650:
            raise forms.ValidationError("O prazo máximo é de 3.650 dias.")
        return ",".join(str(p) for p in prazos)
