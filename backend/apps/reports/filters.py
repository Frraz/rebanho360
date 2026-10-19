"""Filtros operacionais compartilhados por listas, relatórios e exportações."""

from django import forms
from django.db.models import Q

from apps.core import context as ctx
from apps.core.operation_types import OperationType
from apps.core.reversible import Status
from apps.costs.models import CostCenter
from apps.livestock.models import AnimalCategory
from apps.organizations.models import BusinessUnit
from apps.partners.models import Partner
from apps.procurement.models import Commission, Commitment
from apps.properties.models import Farm

SITUACOES = [
    ("", "Todas"),
    ("ABERTO", "Em aberto"),
    ("ENCERRADA", "Encerrada"),
    ("RASCUNHO", "Em negociação"),
    ("CONFIRMADA", "Aprovada"),
    ("EXCLUIDA", "Excluída"),
]


class OperationalFilterForm(forms.Form):
    unidade = forms.ModelChoiceField(
        label="Unidade", queryset=BusinessUnit.objects.none(), required=False
    )
    fazenda = forms.ModelChoiceField(
        label="Fazenda", queryset=Farm.objects.none(), required=False
    )
    comprador = forms.ModelChoiceField(
        label="Comprador", queryset=Partner.objects.none(), required=False
    )
    produtor = forms.ModelChoiceField(
        label="Produtor/pecuarista", queryset=Partner.objects.none(), required=False
    )
    de = forms.DateField(
        label="De", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    ate = forms.DateField(
        label="Até", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    categoria = forms.ModelChoiceField(
        label="Categoria", queryset=AnimalCategory.objects.all(), required=False
    )
    operacao = forms.ModelChoiceField(
        label="Operação", queryset=Commitment.objects.none(), required=False
    )
    situacao_operacao = forms.ChoiceField(
        label="Situação", choices=SITUACOES, required=False
    )
    centro_custo = forms.ModelChoiceField(
        label="Centro de custo", queryset=CostCenter.objects.all(), required=False
    )
    tipo_operacao = forms.ChoiceField(
        label="Tipo de operação",
        choices=[("", "Todos"), ("SEM_TIPO", "Sem classificação")]
        + OperationType.choices,
        required=False,
    )

    def __init__(self, *args, user, company=None, fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        company = company or ctx.current_company()
        farms = ctx.available_farms(user).filter(
            Q(business_unit__company=company) | Q(business_unit__isnull=True)
        )
        self.fields["fazenda"].queryset = farms
        self.fields["unidade"].queryset = BusinessUnit.objects.filter(
            company=company, farms__in=farms
        ).distinct()
        self.fields["operacao"].queryset = Commitment.objects.for_user(user).filter(
            season__company=company
        )
        visible = self.fields["operacao"].queryset
        from apps.purchases.models import Purchase

        purchases = Purchase.objects.for_user(user).filter(season__company=company)
        self.fields["produtor"].queryset = Partner.objects.filter(
            Q(pk__in=visible.values("seller_id"))
            | Q(pk__in=purchases.values("seller_id"))
        ).distinct()
        self.fields["comprador"].queryset = Partner.objects.filter(
            Q(
                pk__in=Commission.objects.filter(commitment__in=visible).values(
                    "payee_id"
                )
            )
            | Q(pk__in=visible.values("commissioned_id"))
            | Q(pk__in=purchases.values("buyer_id"))
        ).distinct()
        if fields is not None:
            for name in list(self.fields):
                if name not in fields:
                    del self.fields[name]

    def clean(self):
        data = super().clean()
        if data.get("de") and data.get("ate") and data["de"] > data["ate"]:
            self.add_error("ate", "A data final é anterior à inicial.")
        if (
            data.get("fazenda")
            and data.get("unidade")
            and data["fazenda"].business_unit_id != data["unidade"].pk
        ):
            self.add_error("fazenda", "A fazenda não pertence à unidade selecionada.")
        return data


def filtrar_compromissos(
    qs,
    *,
    unidade=None,
    comprador=None,
    produtor=None,
    categoria=None,
    operacao=None,
    situacao_operacao="",
    centro_custo=None,
    tipo_operacao="",
    **unused,
):
    if unidade:
        qs = qs.filter(destination_farm__business_unit=unidade)
    if produtor:
        qs = qs.filter(seller=produtor)
    if comprador:
        qs = qs.filter(Q(commissioned=comprador) | Q(commissions__payee=comprador))
    if categoria:
        qs = qs.filter(items__category=categoria, items__removed_at__isnull=True)
    if operacao:
        qs = qs.filter(pk=operacao.pk)
    if situacao_operacao == "ABERTO":
        qs = qs.filter(closed_at__isnull=True).exclude(status=Status.EXCLUIDA)
    elif situacao_operacao == "ENCERRADA":
        qs = qs.filter(closed_at__isnull=False).exclude(status=Status.EXCLUIDA)
    elif situacao_operacao:
        qs = qs.filter(status=situacao_operacao)
    if centro_custo:
        qs = qs.filter(
            items__purchase__cost_entries__cost_center=centro_custo,
            items__purchase__cost_entries__status=Status.CONFIRMADA,
        )
    if tipo_operacao:
        qs = qs.filter(
            operation_type="" if tipo_operacao == "SEM_TIPO" else tipo_operacao
        )
    return qs.distinct()


def filtrar_compras(
    qs,
    *,
    unidade=None,
    comprador=None,
    produtor=None,
    categoria=None,
    operacao=None,
    situacao_operacao="",
    centro_custo=None,
    tipo_operacao="",
    **unused,
):
    if unidade:
        qs = qs.filter(destination_farm__business_unit=unidade)
    if produtor:
        qs = qs.filter(seller=produtor)
    if comprador:
        qs = qs.filter(
            Q(buyer=comprador)
            | Q(commitment_item__commitment__commissioned=comprador)
            | Q(
                commitment_item__commitment__commissions__payee=comprador,
            )
        )
    if categoria:
        qs = qs.filter(category=categoria)
    if operacao:
        qs = qs.filter(commitment_item__commitment=operacao)
    if situacao_operacao in Status.values:
        qs = qs.filter(status=situacao_operacao)
    elif situacao_operacao == "ENCERRADA":
        qs = qs.filter(commitment_item__commitment__closed_at__isnull=False)
    elif situacao_operacao == "ABERTO":
        qs = qs.filter(commitment_item__commitment__closed_at__isnull=True).exclude(
            status=Status.EXCLUIDA
        )
    if centro_custo:
        qs = qs.filter(
            cost_entries__cost_center=centro_custo,
            cost_entries__status=Status.CONFIRMADA,
        )
    if tipo_operacao:
        qs = qs.filter(
            operation_type="" if tipo_operacao == "SEM_TIPO" else tipo_operacao
        )
    return qs.distinct()


def rotulos(filtros):
    nomes = {
        "unidade": "Unidade",
        "fazenda": "Fazenda",
        "comprador": "Comprador",
        "produtor": "Produtor",
        "categoria": "Categoria",
        "operacao": "Operação",
        "centro_custo": "Centro de custo",
        "tipo_operacao": "Tipo de operação",
        "situacao_operacao": "Situação",
    }
    tipos = dict(OperationType.choices) | {"SEM_TIPO": "Sem classificação"}
    return [
        f"{nomes[k]}: {tipos.get(v,v) if k=='tipo_operacao' else dict(SITUACOES).get(v,v) if k=='situacao_operacao' else v}"
        for k, v in filtros.items()
        if v and k in nomes
    ]
