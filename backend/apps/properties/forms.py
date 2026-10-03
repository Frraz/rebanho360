"""Validação de entrada vinda da web."""

from django import forms

from apps.properties.models import Farm, Paddock


class FarmForm(forms.ModelForm):
    class Meta:
        model = Farm
        fields = [
            "business_unit",
            "name",
            "code",
            "city",
            "state",
            "total_area_ha",
            "pasture_area_ha",
            "is_active",
        ]


class PaddockForm(forms.ModelForm):
    class Meta:
        model = Paddock
        fields = ["farm", "name", "type", "area_ha", "capacity_ua", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = Farm.objects.filter(is_active=True)
