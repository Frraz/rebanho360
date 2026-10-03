"""Validação de entrada vinda da web. As regras de negócio moram no serviço
(`apps.finance.services`); o form garante tipos e formatos.

Dado bancário nunca é digitado aqui: a conta vem do cadastro do favorecido
(`BankAccount`) e o rótulo dela é **mascarado** — o número inteiro só aparece
na tela do título, para quem pode vê-lo, e a consulta é auditada.
"""

import datetime
from decimal import Decimal

from django import forms

from apps.core import context as ctx
from apps.finance.models import (
    COMPONENTES_A_PAGAR,
    COMPONENTES_A_RECEBER,
    Component,
    Direction,
    PaymentMethod,
    PaymentStatus,
)
from apps.partners.models import BankAccount, Partner
from apps.properties.models import Farm

ISO_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def mascarar(texto: str, visiveis: int = 4) -> str:
    """`12345-6` → `••••5-6`? Não: só os últimos dígitos, sem revelar o resto."""
    limpo = (texto or "").strip()
    if len(limpo) <= visiveis:
        return limpo
    return "•" * (len(limpo) - visiveis) + limpo[-visiveis:]


def rotulo_da_conta(conta: BankAccount) -> str:
    """Para escolher a conta sem expor o número: banco · agência · final da conta."""
    banco = conta.bank_name or conta.bank_code or "Banco"
    partes = [banco]
    if conta.branch:
        partes.append(f"ag. {conta.branch}")
    if conta.account:
        partes.append(f"conta {mascarar(conta.account)}")
    if conta.pix_key and not conta.account:
        partes.append("Pix")
    if conta.is_default:
        partes.append("padrão")
    return " · ".join(partes)


class ContaChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return rotulo_da_conta(obj)


def _dinheiro(label, **extra):
    return forms.DecimalField(
        label=label,
        min_value=Decimal("0.01"),
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        **extra,
    )


class TituloForm(forms.Form):
    direction = forms.ChoiceField(label="Tipo", choices=Direction.choices)
    component = forms.ChoiceField(
        label="Origem da obrigação",
        choices=[(c.value, c.label) for c in Component if c != Component.VENDA]
        + [(Component.VENDA.value, Component.VENDA.label)],
        initial=Component.OUTRO,
    )
    farm = forms.ModelChoiceField(label="Fazenda", queryset=Farm.objects.none())
    payee = forms.ModelChoiceField(
        label="Favorecido / cliente",
        queryset=Partner.objects.none(),
        required=False,
        help_text="Sem favorecido o título existe, mas não pode ser programado.",
    )
    bank_account = ContaChoiceField(
        label="Conta bancária do favorecido",
        queryset=BankAccount.objects.none(),
        required=False,
        empty_label="Nenhuma / usar a conta padrão",
        help_text="Vem do cadastro do parceiro: não se digita dado bancário aqui.",
    )
    document = forms.CharField(
        label="Documento",
        max_length=60,
        required=False,
        help_text="Nota, duplicata, contrato…",
    )
    issue_date = forms.DateField(
        label="Emissão", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    due_date = forms.DateField(
        label="Vencimento", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    amount = _dinheiro("Valor (R$)")
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    # Operação de origem: vem por querystring ("Novo título desta compra"),
    # nunca de um select com centenas de linhas.
    origin_purchase = forms.ModelChoiceField(
        queryset=None, required=False, widget=forms.HiddenInput
    )
    origin_sale = forms.ModelChoiceField(
        queryset=None, required=False, widget=forms.HiddenInput
    )

    def __init__(self, *args, user=None, **kwargs):
        from apps.purchases.models import Purchase
        from apps.sales.models import Sale

        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )
        self.fields["payee"].queryset = Partner.objects.filter(is_active=True)
        self.fields["origin_purchase"].queryset = (
            Purchase.objects.for_user(user).filter(status="CONFIRMADA")
            if user
            else Purchase.objects.none()
        )
        self.fields["origin_sale"].queryset = (
            Sale.objects.for_user(user).filter(status="CONFIRMADA")
            if user
            else Sale.objects.none()
        )
        # As contas oferecidas são as do favorecido escolhido (ou já gravado).
        payee_id = self.data.get("payee") or self.initial.get("payee")
        if payee_id and str(payee_id).isdigit():
            self.fields["bank_account"].queryset = BankAccount.objects.filter(
                partner_id=int(payee_id)
            )
        self.fields["payee"].widget.attrs.update(
            {
                "hx-get": "/financeiro/contas-do-favorecido/",
                "hx-trigger": "change",
                "hx-target": "#id_bank_account",
                "hx-swap": "outerHTML",
            }
        )

    def clean(self):
        dados = super().clean()
        direcao, componente = dados.get("direction"), dados.get("component")
        if direcao and componente:
            validos = (
                COMPONENTES_A_RECEBER
                if direcao == Direction.RECEBER
                else COMPONENTES_A_PAGAR
            )
            if componente not in validos:
                self.add_error(
                    "component", "Esta origem não vale para este tipo de título."
                )
        return dados

    def dados_limpos(self) -> dict:
        dados = dict(self.cleaned_data)
        dados["document"] = dados.get("document") or ""
        dados["notes"] = dados.get("notes") or ""
        return dados


class TituloEditForm(TituloForm):
    edit_reason = forms.CharField(
        label="Motivo da correção",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Por que este título está sendo corrigido. Fica na auditoria.",
    )

    def __init__(self, *args, user=None, campos_editaveis=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        if campos_editaveis is not None:
            # Título que nasceu de compra/venda: valor e favorecido vêm dela
            # ("corrija a compra — o título acompanha").
            for nome in list(self.fields):
                if nome not in (*campos_editaveis, "edit_reason"):
                    del self.fields[nome]
        for oculto in ("origin_purchase", "origin_sale", "direction"):
            self.fields.pop(oculto, None)


class ProgramarForm(forms.Form):
    scheduled_date = forms.DateField(
        label="Pagar em", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    bank_account = ContaChoiceField(
        label="Conta bancária do favorecido",
        queryset=BankAccount.objects.none(),
        required=False,
        empty_label="Manter a conta atual",
    )

    def __init__(self, *args, titulo=None, **kwargs):
        super().__init__(*args, **kwargs)
        if titulo is not None and titulo.payee_id:
            self.fields["bank_account"].queryset = BankAccount.objects.filter(
                partner_id=titulo.payee_id
            )

    def clean_scheduled_date(self):
        data = self.cleaned_data["scheduled_date"]
        if data < datetime.date.today():
            raise forms.ValidationError("A data programada não pode estar no passado.")
        return data


class BaixaForm(forms.Form):
    date = forms.DateField(
        label="Data do pagamento", widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    amount = _dinheiro(
        "Valor (R$)", help_text="Pode ser menor que o saldo: a baixa fica parcial."
    )
    method = forms.ChoiceField(label="Forma", choices=PaymentMethod.choices)
    document = forms.CharField(
        label="Documento de pagamento",
        max_length=60,
        help_text=(
            "Comprovante: nº da TED, ID do Pix, nº do cheque. É ele que impede a "
            "mesma baixa de ser registrada duas vezes."
        ),
    )
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def clean_date(self):
        data = self.cleaned_data["date"]
        if data > datetime.date.today():
            raise forms.ValidationError("A data do pagamento não pode estar no futuro.")
        return data


class MotivoForm(forms.Form):
    motivo = forms.CharField(
        label="Motivo",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Fica registrado na auditoria, com seu nome e a data.",
    )


class FiltroContasForm(forms.Form):
    SITUACOES = [
        ("abertos", "Em aberto"),
        ("vencidos", "Vencidos"),
        (PaymentStatus.A_PAGAR.value, "A pagar / a receber"),
        (PaymentStatus.PROGRAMADO.value, "Programados"),
        (PaymentStatus.APROVADO.value, "Aprovados"),
        (PaymentStatus.PARCIAL.value, "Pagos em parte"),
        (PaymentStatus.PAGO.value, "Pagos / recebidos"),
        ("todos", "Todos"),
    ]

    payee = forms.ModelChoiceField(
        label="Favorecido", queryset=Partner.objects.none(), required=False
    )
    situacao = forms.ChoiceField(
        label="Situação", choices=SITUACOES, required=False, initial="abertos"
    )
    de = forms.DateField(
        label="Vence de", required=False, widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )
    ate = forms.DateField(
        label="até", required=False, widget=ISO_DATE, input_formats=["%Y-%m-%d"]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payee"].queryset = Partner.objects.filter(
            invoices__isnull=False
        ).distinct()
