from decimal import Decimal

from django import forms

from apps.core import context as ctx
from apps.infrastructure.models import FarmStructure, Machine
from apps.properties.models import Farm


class _FazendaDoUsuario(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )


class FarmStructureForm(_FazendaDoUsuario):
    class Meta:
        model = FarmStructure
        fields = [
            "farm",
            "kind",
            "name",
            "area_m2",
            "trough_m",
            "waterers",
            "animals",
            "notes",
            "is_active",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class MachineForm(_FazendaDoUsuario):
    class Meta:
        model = Machine
        fields = ["farm", "name", "kind", "new_value", "notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


def _decimal(rotulo, **extra):
    return forms.DecimalField(
        label=rotulo,
        required=False,
        min_value=Decimal("0"),
        decimal_places=2,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        **extra,
    )


class MachineLogForm(forms.Form):
    date = forms.DateField(
        label="Data",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    hours = forms.DecimalField(
        label="Horas trabalhadas",
        min_value=Decimal("0.01"),
        decimal_places=2,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
    )
    fuel_liters = _decimal("Combustível (litros)")
    fuel_cost = _decimal("Combustível (R$)")
    maintenance_cost = _decimal("Manutenção (R$)")
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class MachineLogEditForm(MachineLogForm):
    edit_reason = forms.CharField(
        label="Motivo da correção",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Por que este lançamento está sendo corrigido. Fica na auditoria.",
    )
