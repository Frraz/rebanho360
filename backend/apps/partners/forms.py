"""Validação de entrada vinda da web."""

from django import forms

from apps.partners.models import BankAccount, Partner, PartnerRoleChoice


class PartnerForm(forms.ModelForm):
    roles = forms.MultipleChoiceField(
        label="Papéis",
        choices=PartnerRoleChoice.choices,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        help_text="O mesmo parceiro pode exercer mais de um papel — marque todos que se aplicam.",
    )

    class Meta:
        model = Partner
        fields = [
            "name",
            "legal_name",
            "trade_name",
            "document",
            "address",
            "city",
            "state",
            "phone",
            "email",
            "notes",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["roles"].initial = list(
                self.instance.roles.values_list("role", flat=True)
            )


class BankAccountForm(forms.ModelForm):
    reason = forms.CharField(
        label="Motivo da alteração",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
        help_text="Obrigatório ao alterar uma conta já cadastrada.",
    )

    class Meta:
        model = BankAccount
        fields = [
            "bank_code",
            "bank_name",
            "branch",
            "account",
            "account_type",
            "pix_key",
            "is_default",
        ]

    def clean_reason(self):
        reason = self.cleaned_data.get("reason", "").strip()
        if self.instance.pk and not reason:
            raise forms.ValidationError(
                "Motivo é obrigatório para alterar um dado bancário já cadastrado."
            )
        return reason


class PartnerFilterForm(forms.Form):
    """Filtros da listagem de Parceiros."""

    q = forms.CharField(label="Buscar por nome, documento ou cidade", required=False)
    papel = forms.ChoiceField(
        label="Papel",
        required=False,
        choices=[("", "Todos os papéis"), *PartnerRoleChoice.choices],
    )
