"""Validação de entrada vinda da web. As regras de negócio moram no
serviço (`apps.purchases.services`); o form garante tipos e formatos."""

from decimal import Decimal

from django import forms

from apps.commercial.models import PaymentCondition
from apps.core import context as ctx
from apps.livestock.models import AnimalCategory, Lot
from apps.partners.models import Partner, PartnerRoleChoice
from apps.properties.models import Farm


def _dinheiro(label, *, obrigatorio=False):
    return forms.DecimalField(
        label=label,
        required=obrigatorio,
        min_value=Decimal("0"),
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"inputmode": "decimal", "step": "0.01", "data-previa": "1"}
        ),
    )


class PurchaseForm(forms.Form):
    date = forms.DateField(
        label="Data",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    seller = forms.ModelChoiceField(
        label="Vendedor", queryset=Partner.objects.none(), required=False
    )
    destination_farm = forms.ModelChoiceField(
        label="Fazenda de destino", queryset=Farm.objects.none()
    )
    category = forms.ModelChoiceField(
        label="Categoria", queryset=AnimalCategory.objects.filter(is_active=True)
    )
    head_count = forms.IntegerField(
        label="Cabeças",
        min_value=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "data-previa": "1"}),
    )
    total_weight_kg = forms.DecimalField(
        label="Peso total (kg) — opcional",
        required=False,
        min_value=Decimal("0.001"),
        widget=forms.NumberInput(
            attrs={"inputmode": "decimal", "step": "0.001", "data-previa": "1"}
        ),
    )
    animal_value = _dinheiro("Valor dos animais (R$)", obrigatorio=True)
    freight_value = _dinheiro("Frete (R$)")
    commission_value = _dinheiro("Comissão (R$)")
    tax_value = _dinheiro("Impostos (R$)")
    lot = forms.ModelChoiceField(
        label="Lote",
        queryset=Lot.objects.none(),
        required=False,
        empty_label="Criar um lote novo para esta compra",
        help_text="Ou adicione a compra a um lote que já existe.",
    )
    payment_condition = forms.ModelChoiceField(
        label="Condição de pagamento",
        queryset=PaymentCondition.objects.none(),
        required=False,
        empty_label="Informar o prazo em dias",
        help_text="Cadastrada em Comercial. Parcelada gera um título por parcela.",
    )
    entry_yield_percent = forms.DecimalField(
        label="Rendimento estimado de entrada (%)",
        required=False,
        min_value=Decimal("1"),
        max_value=Decimal("100"),
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        help_text="Editável. Cerca de 50% é a referência de uso, não um valor fixo.",
    )
    payment_days = forms.IntegerField(
        label="Prazo de pagamento (dias)",
        required=False,
        min_value=0,
        max_value=3650,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
        help_text=(
            "Dá o vencimento do título a pagar gerado ao confirmar. Vazio = vence "
            "na data da compra; depois o vencimento se ajusta no próprio título."
        ),
    )
    partnership = forms.CharField(label="Parceria", max_length=100, required=False)
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destination_farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )
        self.fields["lot"].queryset = (
            Lot.objects.for_user(user).filter(status="ABERTO")
            if user
            else Lot.objects.none()
        )
        self.fields["payment_condition"].queryset = PaymentCondition.objects.filter(
            is_active=True
        )
        self.fields["seller"].queryset = Partner.objects.filter(
            is_active=True,
            roles__role__in=[PartnerRoleChoice.FORNECEDOR, PartnerRoleChoice.PRODUTOR],
        ).distinct()

    def dados_limpos(self) -> dict:
        dados = dict(self.cleaned_data)
        for campo in ("freight_value", "commission_value", "tax_value"):
            dados[campo] = dados.get(campo) or Decimal("0")
        dados["partnership"] = dados.get("partnership") or ""
        dados["notes"] = dados.get("notes") or ""
        return dados


class PurchaseEditForm(PurchaseForm):
    # Obrigatório só em compra confirmada — a view decide (rascunho não tem).
    edit_reason = forms.CharField(
        label="Motivo da correção",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Por que esta compra está sendo corrigida.",
    )


class PurchaseFilterForm(forms.Form):
    """Filtros da listagem de compras: nº de registro, vendedor, destino, datas
    e situação."""

    registro = forms.CharField(label="Nº de registro", required=False)
    vendedor = forms.ModelChoiceField(
        label="Vendedor", queryset=Partner.objects.none(), required=False
    )
    destino = forms.ModelChoiceField(
        label="Destino", queryset=Farm.objects.none(), required=False
    )
    data_de = forms.DateField(
        label="De",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    data_ate = forms.DateField(
        label="Até",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    situacao = forms.ChoiceField(
        label="Situação",
        required=False,
        choices=[
            ("", "Todas"),
            ("RASCUNHO", "Rascunhos"),
            ("CONFIRMADA", "Confirmadas"),
            ("EXCLUIDA", "Excluídas"),
        ],
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destino"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )
        # Quem já vendeu para nós, mesmo inativo hoje ou vindo do ciclo de compra:
        # a lista do cadastro (só fornecedor/produtor ativo) esconderia compras antigas.
        self.fields["vendedor"].queryset = (
            Partner.objects.filter(sales_to_us__isnull=False)
            .distinct()
            .order_by("name")
        )

    def clean(self):
        dados = super().clean()
        de, ate = dados.get("data_de"), dados.get("data_ate")
        if de and ate and de > ate:
            self.add_error("data_ate", "A data final é anterior à inicial.")
        return dados
