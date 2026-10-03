"""Validação de entrada vinda da web.

O formulário aceita todos os campos possíveis — qual conjunto é exigido
depende do `type` escolhido, e essa regra mora no serviço
(`apps.herd.services.registrar_movimento`), não aqui. O form só garante
tipos e formatos; a tela esconde/mostra campos via Alpine.js conforme o
tipo (docs/ux/01#formulário-de-campo).
"""

from django import forms

from apps.herd.models import DeathCause, MovementType, WeighingReason
from apps.livestock.models import AnimalCategory, Lot
from apps.partners.models import Partner
from apps.properties.models import Farm


class MovementForm(forms.Form):
    type = forms.ChoiceField(label="Tipo", choices=MovementType.choices)
    date = forms.DateField(
        label="Data",
        # `<input type="date">` exige valor ISO (AAAA-MM-DD) — o formato
        # pt-br do DateInput padrão (DD/MM/AAAA) faz o navegador descartar
        # o valor inicial silenciosamente. Achado ao verificar a tela em
        # 360px com navegador real.
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    quantity = forms.IntegerField(label="Quantidade", min_value=1)
    total_weight_kg = forms.DecimalField(
        label="Peso total (kg)", required=False, min_value=0
    )

    origin_farm = forms.ModelChoiceField(
        label="Fazenda de origem", queryset=Farm.objects.none(), required=False
    )
    origin_lot = forms.ModelChoiceField(
        label="Lote de origem", queryset=Lot.objects.none(), required=False
    )
    origin_category = forms.ModelChoiceField(
        label="Categoria de origem",
        queryset=AnimalCategory.objects.filter(is_active=True),
        required=False,
    )

    destination_farm = forms.ModelChoiceField(
        label="Fazenda de destino", queryset=Farm.objects.none(), required=False
    )
    destination_lot = forms.ModelChoiceField(
        label="Lote de destino", queryset=Lot.objects.none(), required=False
    )
    destination_category = forms.ModelChoiceField(
        label="Categoria de destino",
        queryset=AnimalCategory.objects.filter(is_active=True),
        required=False,
    )

    partner = forms.ModelChoiceField(
        label="Parceiro",
        queryset=Partner.objects.filter(is_active=True),
        required=False,
    )
    reason = forms.CharField(
        label="Motivo", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    death_cause = forms.ChoiceField(
        label="Causa da morte",
        required=False,
        choices=[("", "Não informada")] + list(DeathCause.choices),
    )
    notes = forms.CharField(
        label="Observação", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core import context as ctx

        fazendas = ctx.available_farms(user) if user else Farm.objects.none()
        self.fields["origin_farm"].queryset = fazendas
        self.fields["destination_farm"].queryset = fazendas
        self.fields["origin_lot"].queryset = (
            Lot.objects.for_user(user) if user else Lot.objects.none()
        )
        self.fields["destination_lot"].queryset = self.fields["origin_lot"].queryset


class MovementEditForm(MovementForm):
    """Mesmo formulário do lançamento, mais o motivo da edição — campo
    diferente de `reason` (o motivo do próprio movimento, ex.: por que a
    morte aconteceu). Este é o motivo exigido por
    `apps.core.reversible.editar()` para corrigir um registro confirmado."""

    edit_reason = forms.CharField(
        label="Motivo da correção",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Por que este lançamento está sendo corrigido.",
    )


class WeighingForm(forms.Form):
    date = forms.DateField(
        label="Data",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    farm = forms.ModelChoiceField(label="Fazenda", queryset=Farm.objects.none())
    lot = forms.ModelChoiceField(label="Lote", queryset=Lot.objects.none())
    reason = forms.ChoiceField(label="Motivo", choices=WeighingReason.choices)
    head_count = forms.IntegerField(label="Cabeças pesadas", min_value=1)
    total_weight_kg = forms.DecimalField(label="Peso total (kg)", min_value=0.001)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core import context as ctx

        self.fields["farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )
        self.fields["lot"].queryset = (
            Lot.objects.for_user(user) if user else Lot.objects.none()
        )
