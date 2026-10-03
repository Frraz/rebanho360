"""Fino. Recebe request, chama service/selector, devolve template."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.partners import selectors, services
from apps.partners.forms import BankAccountForm, PartnerForm
from apps.partners.models import BankAccount, Partner
from apps.partners.permissions import GerenciaParceiroMixin


class PartnerListView(GerenciaParceiroMixin, ListView):
    template_name = "partners/partner_list.html"
    context_object_name = "parceiros"

    def get_queryset(self):
        termo = self.request.GET.get("q", "")
        if termo:
            return selectors.buscar_parceiros(termo, limite=50)
        return selectors.listar_parceiros()


class PartnerSearchView(GerenciaParceiroMixin, ListView):
    """Combobox com busca (docs/ux/01) — devolve só o fragmento de
    resultados, para HTMX trocar no DOM."""

    template_name = "partners/_resultado_busca.html"
    context_object_name = "parceiros"

    def get_queryset(self):
        return selectors.buscar_parceiros(self.request.GET.get("q", ""))


class PartnerCreateView(GerenciaParceiroMixin, CreateView):
    model = Partner
    form_class = PartnerForm
    template_name = "partners/partner_form.html"

    def form_valid(self, form):
        partner = form.save(commit=False)
        services.salvar_parceiro(
            partner,
            form.cleaned_data["roles"],
            usuario=self.request.user,
            criando=True,
        )
        messages.success(self.request, "✓ Parceiro cadastrado.")
        return redirect(reverse("partners:detalhe", args=[partner.pk]))


class PartnerUpdateView(GerenciaParceiroMixin, UpdateView):
    model = Partner
    form_class = PartnerForm
    template_name = "partners/partner_form.html"

    def form_valid(self, form):
        partner = form.save(commit=False)
        services.salvar_parceiro(
            partner,
            form.cleaned_data["roles"],
            usuario=self.request.user,
            criando=False,
        )
        messages.success(self.request, "✓ Parceiro atualizado.")
        return redirect(reverse("partners:detalhe", args=[partner.pk]))


class PartnerDetailView(GerenciaParceiroMixin, DetailView):
    model = Partner
    template_name = "partners/partner_detail.html"
    context_object_name = "parceiro"


class BankAccountCreateView(GerenciaParceiroMixin, TemplateView):
    template_name = "partners/bank_account_form.html"

    def get_partner(self):
        return get_object_or_404(Partner, pk=self.kwargs["partner_pk"])

    def get(self, request, *args, **kwargs):
        form = BankAccountForm()
        return self.render_to_response({"form": form, "parceiro": self.get_partner()})

    def post(self, request, *args, **kwargs):
        partner = self.get_partner()
        form = BankAccountForm(request.POST)
        if form.is_valid():
            conta = form.save(commit=False)
            conta.partner = partner
            services.salvar_conta_bancaria(
                conta,
                usuario=request.user,
                criando=True,
                motivo=form.cleaned_data["reason"],
            )
            messages.success(request, "✓ Conta bancária cadastrada.")
            return redirect(reverse("partners:detalhe", args=[partner.pk]))
        return self.render_to_response({"form": form, "parceiro": partner})


class BankAccountUpdateView(GerenciaParceiroMixin, TemplateView):
    template_name = "partners/bank_account_form.html"

    def get_object(self):
        return get_object_or_404(BankAccount, pk=self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        conta = self.get_object()
        form = BankAccountForm(instance=conta)
        return self.render_to_response({"form": form, "parceiro": conta.partner})

    def post(self, request, *args, **kwargs):
        conta = self.get_object()
        form = BankAccountForm(request.POST, instance=conta)
        if form.is_valid():
            conta = form.save(commit=False)
            services.salvar_conta_bancaria(
                conta,
                usuario=request.user,
                criando=False,
                motivo=form.cleaned_data["reason"],
            )
            messages.success(request, "✓ Conta bancária atualizada.")
            return redirect(reverse("partners:detalhe", args=[conta.partner.pk]))
        return self.render_to_response({"form": form, "parceiro": conta.partner})
