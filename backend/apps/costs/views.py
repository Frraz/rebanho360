"""Fino. Recebe request, chama service/selector, devolve template."""

import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from apps.core import context as ctx
from apps.core.exceptions import BusinessError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.views import ExclusaoComImpactoView
from apps.costs import selectors, services
from apps.costs.forms import (
    CostCenterForm,
    CostEntryEditForm,
    CostEntryForm,
    CostFilterForm,
)
from apps.costs.models import CostCenter, CostEntry
from apps.costs.permissions import (
    GerenciaCentroDeCustoMixin,
    LancaCustoMixin,
    pode_lancar_custo,
)


class _SalvarComAuditoriaMixin:
    def form_valid(self, form):
        criando = form.instance.pk is None
        self.object = form.save(commit=False)
        services.salvar_cadastro(
            self.object, usuario=self.request.user, criando=criando
        )
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class CostCenterListView(LoginRequiredMixin, ListView):
    template_name = "costs/center_list.html"
    context_object_name = "centros"

    def get_queryset(self):
        return selectors.listar_centros()


class CostCenterCreateView(
    GerenciaCentroDeCustoMixin, _SalvarComAuditoriaMixin, CreateView
):
    model = CostCenter
    form_class = CostCenterForm
    template_name = "costs/center_form.html"
    success_url = reverse_lazy("costs:centro_lista")
    success_message = "✓ Centro de custo cadastrado."


class CostCenterUpdateView(
    GerenciaCentroDeCustoMixin, _SalvarComAuditoriaMixin, UpdateView
):
    model = CostCenter
    form_class = CostCenterForm
    template_name = "costs/center_form.html"
    success_url = reverse_lazy("costs:centro_lista")
    success_message = "✓ Centro de custo atualizado."


class CostListView(LoginRequiredMixin, TemplateView):
    template_name = "costs/entry_list.html"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        season = ctx.current_season(self.request, ctx.current_company())
        form = CostFilterForm(self.request.GET or None, user=user)
        filtros = form.cleaned_data if form.is_valid() else {}

        farm = filtros.get("farm") or ctx.current_farm(self.request, user)
        qs = selectors.listar_custos_para(
            user,
            season=season,
            farm=farm,
            cost_center=filtros.get("cost_center"),
            cost_class=filtros.get("cost_class"),
            texto=filtros.get("q", ""),
            situacao=filtros.get("situacao") or "CONFIRMADA",
        )
        pagina = Paginator(qs, self.paginate_by).get_page(self.request.GET.get("page"))
        context.update(
            {
                "filtro": form,
                "page_obj": pagina,
                "custos": pagina.object_list,
                "total": selectors.total_dos_custos(qs),
                "season": season,
                "pode_lancar": pode_lancar_custo(user),
            }
        )
        return context


class CostCreateView(LancaCustoMixin, View):
    template_name = "costs/entry_form.html"

    def get(self, request):
        form = CostEntryForm(
            user=request.user,
            initial={
                "date": datetime.date.today(),
                "cost_class": _classe_padrao(),
                "farm": ctx.current_farm(request, request.user),
            },
        )
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = CostEntryForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        dados = form.cleaned_data
        try:
            custo = services.registrar_custo(
                date=dados["date"],
                farm=dados["farm"],
                cost_center=dados["cost_center"],
                cost_class=dados["cost_class"],
                amount=dados["amount"],
                description=dados["description"],
                payer=dados["payer"],
                lot=dados["lot"],
                notes=dados["notes"],
                usuario=request.user,
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form})

        messages.success(
            request,
            f"✓ Custo lançado: R$ {custo.amount} em {custo.cost_center} "
            f"({custo.farm}). Que tal lançar o próximo?",
        )
        return redirect(reverse("costs:novo") + "?ok=1")


def _classe_padrao():
    from apps.costs.models import CostClass

    return CostClass.objects.filter(name="CUSTEIO").first()


def _get_custo(request, pk) -> CostEntry:
    return get_object_or_404(CostEntry.objects.for_user(request.user), pk=pk)


class CostDetailView(LoginRequiredMixin, TemplateView):
    template_name = "costs/entry_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        custo = _get_custo(self.request, kwargs["pk"])
        context.update(
            {
                "custo": custo,
                "gerado_por_compra": custo.source_purchase_id is not None,
                "pode_editar": pode_editar_confirmado(self.request.user),
                "pode_excluir": pode_excluir_confirmado(self.request.user),
            }
        )
        return context


class CostUpdateView(LoginRequiredMixin, View):
    template_name = "costs/entry_edit_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        custo = _get_custo(request, kwargs["pk"])
        if not pode_editar_confirmado(request.user):
            messages.error(request, "Você não tem permissão para editar este custo.")
            return redirect("costs:detalhe", pk=custo.pk)
        if custo.source_purchase_id:
            messages.error(
                request,
                f"Este custo foi gerado pela compra {custo.source_purchase.code}. "
                "Corrija a compra — os custos acompanham.",
            )
            return redirect("costs:detalhe", pk=custo.pk)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        custo = _get_custo(request, pk)
        form = CostEntryEditForm(
            user=request.user,
            initial={
                "date": custo.date,
                "farm": custo.farm_id,
                "cost_center": custo.cost_center_id,
                "cost_class": custo.cost_class_id,
                "amount": custo.amount,
                "description": custo.description,
                "payer": custo.payer_id,
                "lot": custo.lot_id,
                "notes": custo.notes,
            },
        )
        return render(request, self.template_name, {"form": form, "custo": custo})

    def post(self, request, pk):
        custo = _get_custo(request, pk)
        form = CostEntryEditForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "custo": custo})

        dados = form.cleaned_data
        try:
            services.editar_custo(
                custo,
                {k: v for k, v in dados.items() if k != "edit_reason"},
                usuario=request.user,
                motivo=dados["edit_reason"],
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form, "custo": custo})

        messages.success(request, "✓ Custo corrigido.")
        return redirect("costs:detalhe", pk=custo.pk)


class CostDeleteView(ExclusaoComImpactoView):
    model = CostEntry
    titulo = "Excluir"

    def url_do_registro(self, registro):
        return reverse("costs:detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        services.excluir_custo(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )


class CostRestoreView(LoginRequiredMixin, View):
    def post(self, request, pk):
        custo = _get_custo(request, pk)
        try:
            services.restaurar_custo(custo, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "✓ Custo restaurado.")
        return redirect("costs:detalhe", pk=custo.pk)
