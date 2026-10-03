"""Validação de entrada vinda da web. As regras de negócio moram no
serviço (`apps.sales.services`); o form garante tipos e formatos."""

from decimal import Decimal

from django import forms

from apps.core import context as ctx
from apps.livestock.models import AnimalCategory, Lot, LotStatus
from apps.partners.models import Partner, PartnerRoleChoice
from apps.properties.models import Farm
from apps.sales.models import SaleForm, SaleType


def _numero(label, *, casas, obrigatorio=False, **extra):
    passo = "0." + "0" * (casas - 1) + "1" if casas else "1"
    return forms.DecimalField(
        label=label,
        required=obrigatorio,
        min_value=Decimal(passo),
        max_digits=14,
        decimal_places=casas,
        widget=forms.NumberInput(
            attrs={"inputmode": "decimal", "step": passo, "data-previa": "1"}
        ),
        **extra,
    )


class SaleEntryForm(forms.Form):
    type = forms.ChoiceField(label="Tipo", choices=SaleType.choices)
    date = forms.DateField(
        label="Data",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    buyer = forms.ModelChoiceField(
        label="Comprador / frigorífico", queryset=Partner.objects.none()
    )
    farm = forms.ModelChoiceField(label="Fazenda", queryset=Farm.objects.none())
    lot = forms.ModelChoiceField(label="Lote", queryset=Lot.objects.none())
    category = forms.ModelChoiceField(
        label="Categoria", queryset=AnimalCategory.objects.filter(is_active=True)
    )
    head_count = forms.IntegerField(
        label="Cabeças",
        min_value=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "data-previa": "1"}),
    )
    total_weight_kg = _numero("Peso vivo de saída (kg)", casas=3, obrigatorio=True)
    carcass_weight_kg = _numero(
        "Peso de carcaça (kg) — só no abate, quando o romaneio chegar",
        casas=3,
    )
    total_value = _numero("Valor total (R$)", casas=2, obrigatorio=True)
    sale_form = forms.ChoiceField(
        label="Forma", choices=SaleForm.choices, initial=SaleForm.PASTO
    )
    payment_days = forms.IntegerField(
        label="Prazo de recebimento (dias)",
        required=False,
        min_value=0,
        max_value=3650,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
        help_text=(
            "Dá o vencimento do título a receber gerado ao confirmar. Vazio = vence "
            "na data da venda; depois o vencimento se ajusta no próprio título."
        ),
    )
    partnership = forms.CharField(label="Parceria", max_length=100, required=False)
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )
        # Lote encerrado também entra: corrigir uma venda confirmada que
        # encerrou o lote precisa enxergá-lo. O saldo é que barra o resto.
        self.fields["lot"].queryset = (
            Lot.objects.for_user(user).exclude(status=LotStatus.EXCLUIDO)
            if user
            else Lot.objects.none()
        )
        self.fields["buyer"].queryset = Partner.objects.filter(
            is_active=True,
            roles__role__in=[
                PartnerRoleChoice.FRIGORIFICO,
                PartnerRoleChoice.COMPRADOR,
            ],
        ).distinct()

    def dados_limpos(self) -> dict:
        dados = dict(self.cleaned_data)
        dados["partnership"] = dados.get("partnership") or ""
        dados["notes"] = dados.get("notes") or ""
        return dados


class SaleEditForm(SaleEntryForm):
    # Obrigatório só em venda confirmada — a view decide (rascunho não tem).
    edit_reason = forms.CharField(
        label="Motivo da correção",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Por que esta venda está sendo corrigida.",
    )
