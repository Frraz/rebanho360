"""Telas de complemento de frete, no contexto da operação de compra."""

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.core.exceptions import BusinessError
from apps.core.impact import analisar_impacto
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.views import ExclusaoComImpactoView
from apps.partners.models import Partner, PartnerRoleChoice
from apps.procurement import freight
from apps.procurement.models import Commitment, FreightSupplement
from apps.procurement.permissions import LancaNoCicloMixin, VeOCicloMixin


class FreightForm(forms.ModelForm):
    reason = forms.CharField(
        label="Motivo da correção",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    class Meta:
        model = FreightSupplement
        fields = ["carrier", "date", "due_date", "amount", "trucks", "truck", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount"].label = "Valor adicional do frete (R$)"
        self.fields["amount"].help_text = (
            "Informe somente o valor ainda não lançado. O frete já incluído no acerto permanece no custo da compra."
        )
        self.fields["carrier"].queryset = Partner.objects.filter(
            is_active=True, roles__role=PartnerRoleChoice.TRANSPORTADOR
        ).distinct()


class FreightFormView(LancaNoCicloMixin, View):
    def _context(self, request, pk, freight_pk=None):
        c = get_object_or_404(Commitment.objects.for_user(request.user), pk=pk)
        f = (
            get_object_or_404(
                FreightSupplement.objects.for_user(request.user),
                pk=freight_pk,
                commitment=c,
            )
            if freight_pk
            else None
        )
        compras = list(
            c.items.filter(purchase__status=Status.CONFIRMADA).select_related(
                "purchase", "category"
            )
        )

        class Distribution(forms.Form):
            purchase = forms.ChoiceField(
                label="Compra",
                choices=[
                    (str(i.purchase_id), f"{i.purchase.code} · {i.category.name}")
                    for i in compras
                ],
            )
            amount = forms.DecimalField(
                label="Valor distribuído (R$)",
                min_value=Decimal("0"),
                max_digits=14,
                decimal_places=2,
            )

        Factory = formset_factory(
            Distribution,
            extra=0,
            max_num=len(compras),
            validate_max=True,
            min_num=len(compras),
            validate_min=True,
        )
        initial = [
            {
                "purchase": i.purchase_id,
                "amount": (
                    dict(f.allocations.values_list("purchase_id", "amount")).get(
                        i.purchase_id, Decimal(0)
                    )
                    if f
                    else None
                ),
            }
            for i in compras
        ]
        form = FreightForm(
            request.POST if request.method == "POST" else None,
            instance=f,
            initial={} if f else {"date": timezone.localdate()},
        )
        linhas = (
            Factory(
                request.POST if request.method == "POST" else None,
                initial=initial,
                prefix="distribuicao",
            )
            if len(compras) > 1
            else None
        )
        return c, f, form, linhas

    def get(self, request, pk, freight_pk=None):
        c, f, form, linhas = self._context(request, pk, freight_pk)
        return render(
            request,
            "procurement/freight_form.html",
            {
                "compromisso": c,
                "frete": f,
                "form": form,
                "linhas": linhas,
                "impacto": analisar_impacto(f) if f else None,
            },
        )

    def post(self, request, pk, freight_pk=None):
        c, f, form, linhas = self._context(request, pk, freight_pk)
        valid = form.is_valid()
        if linhas is not None:
            valid = linhas.is_valid() and valid
        if valid:
            dados = {k: v for k, v in form.cleaned_data.items() if k in freight.CAMPOS}
            distribuicao = {}
            if linhas:
                for linha in linhas.cleaned_data:
                    key = int(linha["purchase"])
                    if key in distribuicao:
                        form.add_error(
                            None, "Uma compra aparece duas vezes na distribuição."
                        )
                        valid = False
                    distribuicao[key] = linha["amount"]
            if valid:
                try:
                    if f:
                        f = freight.editar(
                            f,
                            dados,
                            usuario=request.user,
                            motivo=form.cleaned_data.get("reason", ""),
                            distribuicao=distribuicao,
                        )
                    else:
                        f = freight.criar(
                            compromisso=c,
                            usuario=request.user,
                            distribuicao=distribuicao,
                            **dados,
                        )
                    return redirect("procurement:frete_detalhe", pk=f.pk)
                except BusinessError as exc:
                    form.add_error(None, str(exc))
        return render(
            request,
            "procurement/freight_form.html",
            {
                "compromisso": c,
                "frete": f,
                "form": form,
                "linhas": linhas,
                "impacto": analisar_impacto(f) if f else None,
            },
        )


class FreightDetailView(VeOCicloMixin, View):
    def get(self, request, pk):
        f = get_object_or_404(
            FreightSupplement.objects.for_user(request.user).select_related(
                "commitment", "carrier", "invoice"
            ),
            pk=pk,
        )
        from apps.procurement.permissions import pode_lancar_no_ciclo

        return render(
            request,
            "procurement/freight_detail.html",
            {
                "frete": f,
                "impacto": analisar_impacto(f),
                "pode_editar": pode_lancar_no_ciclo(request.user)
                and (
                    f.status == Status.RASCUNHO or pode_editar_confirmado(request.user)
                ),
                "pode_excluir": pode_excluir_confirmado(request.user),
                "pode_restaurar": f.status == Status.EXCLUIDA
                and pode_excluir_confirmado(request.user),
            },
        )


class FreightConfirmView(LancaNoCicloMixin, View):
    def post(self, request, pk):
        f = get_object_or_404(FreightSupplement.objects.for_user(request.user), pk=pk)
        try:
            freight.confirmar(f, usuario=request.user)
            messages.success(
                request,
                "Frete confirmado. Custos e título a pagar gerados; os animais foram preservados.",
            )
        except BusinessError as exc:
            messages.error(request, str(exc))
        return redirect("procurement:frete_detalhe", pk=pk)


class FreightDeleteView(ExclusaoComImpactoView):
    model = FreightSupplement

    def pode_excluir(self, registro):
        return pode_excluir_confirmado(self.request.user)

    def url_do_registro(self, registro):
        return reverse("procurement:frete_detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        freight.excluir(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )


class FreightRestoreView(LancaNoCicloMixin, View):
    def post(self, request, pk):
        frete = get_object_or_404(
            FreightSupplement.objects.for_user(request.user), pk=pk
        )
        try:
            freight.restaurar(frete, usuario=request.user)
            messages.success(
                request, "Complemento de frete restaurado com seus efeitos originais."
            )
        except BusinessError as exc:
            messages.error(request, str(exc))
        return redirect("procurement:frete_detalhe", pk=pk)
