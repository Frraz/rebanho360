"""Fino. Recebe request, chama service/selector, devolve template."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView
from django.views.generic.edit import FormView

from apps.core import context as ctx
from apps.core.exceptions import BusinessError
from apps.organizations import selectors, services
from apps.organizations.forms import BusinessUnitForm, CompanyForm, SeasonForm
from apps.organizations.models import BusinessUnit, Company, Season
from apps.organizations.permissions import GerenciaOrganizacaoMixin, pode_reabrir_safra


class _SalvarComAuditoriaMixin:
    """`CreateView`/`UpdateView` que grava via `services.salvar_cadastro`
    em vez de `form.save()` direto — toda escrita destes cadastros fica
    auditada."""

    def form_valid(self, form):
        criando = form.instance.pk is None
        self.object = form.save(commit=False)
        services.salvar_cadastro(
            self.object, usuario=self.request.user, criando=criando
        )
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class CompanyListView(GerenciaOrganizacaoMixin, ListView):
    model = Company
    template_name = "organizations/company_list.html"
    context_object_name = "empresas"

    def get_queryset(self):
        return selectors.listar_empresas()


class CompanyCreateView(GerenciaOrganizacaoMixin, _SalvarComAuditoriaMixin, CreateView):
    model = Company
    form_class = CompanyForm
    template_name = "organizations/company_form.html"
    success_url = reverse_lazy("organizations:empresa_lista")
    success_message = "✓ Empresa cadastrada."


class CompanyUpdateView(GerenciaOrganizacaoMixin, _SalvarComAuditoriaMixin, UpdateView):
    model = Company
    form_class = CompanyForm
    template_name = "organizations/company_form.html"
    success_url = reverse_lazy("organizations:empresa_lista")
    success_message = "✓ Empresa atualizada."


class BusinessUnitListView(GerenciaOrganizacaoMixin, ListView):
    template_name = "organizations/business_unit_list.html"
    context_object_name = "unidades"

    def get_queryset(self):
        return selectors.listar_unidades()


class BusinessUnitCreateView(
    GerenciaOrganizacaoMixin, _SalvarComAuditoriaMixin, CreateView
):
    form_class = BusinessUnitForm
    template_name = "organizations/business_unit_form.html"
    success_url = reverse_lazy("organizations:unidade_lista")
    success_message = "✓ Unidade cadastrada."


class BusinessUnitUpdateView(
    GerenciaOrganizacaoMixin, _SalvarComAuditoriaMixin, UpdateView
):
    model = BusinessUnit
    form_class = BusinessUnitForm
    template_name = "organizations/business_unit_form.html"
    success_url = reverse_lazy("organizations:unidade_lista")
    success_message = "✓ Unidade atualizada."


class SeasonListView(GerenciaOrganizacaoMixin, ListView):
    template_name = "organizations/season_list.html"
    context_object_name = "safras"

    def get_queryset(self):
        return selectors.listar_safras()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pode_reabrir"] = pode_reabrir_safra(self.request.user)
        return context


class SeasonCreateView(GerenciaOrganizacaoMixin, _SalvarComAuditoriaMixin, CreateView):
    form_class = SeasonForm
    template_name = "organizations/season_form.html"
    success_url = reverse_lazy("organizations:safra_lista")
    success_message = "✓ Safra cadastrada."


class SeasonUpdateView(GerenciaOrganizacaoMixin, _SalvarComAuditoriaMixin, UpdateView):
    model = Season
    form_class = SeasonForm
    template_name = "organizations/season_form.html"
    success_url = reverse_lazy("organizations:safra_lista")
    success_message = "✓ Safra atualizada."


class SeasonSetCurrentView(GerenciaOrganizacaoMixin, FormView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        season = get_object_or_404(Season, pk=kwargs["pk"])
        services.marcar_como_corrente(season, usuario=request.user)
        ctx.set_current_season(request, season)
        messages.success(request, f"✓ {season.name} agora é a safra corrente.")
        return redirect("organizations:safra_lista")


class SeasonCloseView(GerenciaOrganizacaoMixin, FormView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        season = get_object_or_404(Season, pk=kwargs["pk"])
        try:
            services.encerrar_safra(season, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Safra {season.name} encerrada.")
        return redirect("organizations:safra_lista")


class SeasonReopenView(LoginRequiredMixin, FormView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        if not pode_reabrir_safra(request.user):
            messages.error(request, "Só o administrador pode reabrir uma safra.")
            return redirect("organizations:safra_lista")
        season = get_object_or_404(Season, pk=kwargs["pk"])
        try:
            services.reabrir_safra(season, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Safra {season.name} reaberta.")
        return redirect("organizations:safra_lista")


class TrocarSafraView(LoginRequiredMixin, FormView):
    """Seletor de safra do contexto fixo no topo — persiste na sessão."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        season_id = request.POST.get("season_id")
        company = ctx.current_company()
        season = ctx.available_seasons(company).filter(pk=season_id).first()
        ctx.set_current_season(request, season)
        return redirect(ctx.destino_seguro(request, reverse("dashboards:inicio")))
