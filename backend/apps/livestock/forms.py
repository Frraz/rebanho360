"""Validação de entrada vinda da web."""

from django import forms

from apps.livestock.models import AnimalCategory, Breed, Lot
from apps.properties.models import Farm


class AnimalCategoryForm(forms.ModelForm):
    class Meta:
        model = AnimalCategory
        fields = ["name", "sex", "age_order", "display_order", "is_active"]


class BreedForm(forms.ModelForm):
    class Meta:
        model = Breed
        fields = ["name", "is_active"]


class LotForm(forms.ModelForm):
    """Sem campo de código: é gerado pelo serviço — nunca digitado.
    Sem quantidade, peso ou categoria: saem do razão (ADR 0002)."""

    class Meta:
        model = Lot
        fields = [
            "farm",
            "season",
            "entry_date",
            "exit_date",
            "breed",
            "cost_center",
            "origin_partner",
            "notes",
        ]
        widgets = {
            # `format` força ISO — ver nota em apps/organizations/forms.py.
            "entry_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "exit_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = Farm.objects.filter(is_active=True)
