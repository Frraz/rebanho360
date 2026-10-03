"""Fino: recebe request, chama o serviço, devolve tela. Fora do escopo de
fazenda, 404 — nunca 403 (ADR 0003)."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.core import context as ctx
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.views import ExclusaoComImpactoView
from apps.herd.permissions import LancaMovimentoMixin, pode_lancar_movimento
from apps.reproduction import indicators, services
from apps.reproduction.forms import (
    BreedingCycleEditForm,
    BreedingCycleForm,
    iniciais_do_ciclo,
)
from apps.reproduction.models import GRUPOS, BreedingCycle

ERROS = (BusinessError, BlockingDependencyError)


def _ciclo(request, pk) -> BreedingCycle:
    return get_object_or_404(
        BreedingCycle.objects.for_user(request.user).select_related("farm", "season"),
        pk=pk,
    )


class CicloListView(LoginRequiredMixin, TemplateView):
    template_name = "reproduction/ciclo_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        ciclos = BreedingCycle.objects.for_user(user).select_related("farm", "season")
        farm = ctx.current_farm(self.request, user)
        if farm is not None:
            ciclos = ciclos.filter(farm=farm)
        linhas = []
        for c in ciclos:
            ind = indicators.indicadores_do_ciclo(c)
            linhas.append({"ciclo": c, "ind": ind})
        context.update({"linhas": linhas, "pode_lancar": pode_lancar_movimento(user)})
        return context


class CicloNovoView(LancaMovimentoMixin, View):
    template_name = "reproduction/ciclo_form.html"

    def get(self, request):
        season = ctx.current_season(request, ctx.current_company())
        form = BreedingCycleForm(
            user=request.user,
            initial={
                "farm": ctx.current_farm(request, request.user),
                "season": season.pk if season else None,
            },
        )
        return render(request, self.template_name, {"form": form, "grupos": GRUPOS})

    def post(self, request):
        form = BreedingCycleForm(request.POST, user=request.user)
        contexto = {"form": form, "grupos": GRUPOS}
        if not form.is_valid():
            return render(request, self.template_name, contexto)
        try:
            ciclo = services.registrar_ciclo(usuario=request.user, **form.cleaned_data)
        except ERROS as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(
            request,
            f"✓ Ciclo {ciclo.code} registrado. Os índices saem dos números que você informou.",
        )
        return redirect("reproduction:detalhe", pk=ciclo.pk)


class CicloDetalheView(LoginRequiredMixin, TemplateView):
    template_name = "reproduction/ciclo_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        c = _ciclo(self.request, kwargs["pk"])
        context.update(
            {
                "ciclo": c,
                "ind": indicators.indicadores_do_ciclo(c),
                "grupos": [
                    (rotulo, getattr(c, exp), getattr(c, pre))
                    for exp, pre, rotulo in GRUPOS
                ],
                "pode_editar": c.status != Status.EXCLUIDA
                and pode_editar_confirmado(user),
                "pode_excluir": c.status != Status.EXCLUIDA
                and pode_excluir_confirmado(user),
                "pode_restaurar": c.status == Status.EXCLUIDA
                and pode_excluir_confirmado(user),
            }
        )
        return context


class CicloEditarView(LoginRequiredMixin, View):
    template_name = "reproduction/ciclo_form.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not pode_editar_confirmado(request.user):
            messages.error(request, "Você não tem permissão para editar este ciclo.")
            return redirect("reproduction:detalhe", pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        c = _ciclo(request, pk)
        form = BreedingCycleEditForm(user=request.user, initial=iniciais_do_ciclo(c))
        return render(
            request, self.template_name, {"form": form, "grupos": GRUPOS, "ciclo": c}
        )

    def post(self, request, pk):
        c = _ciclo(request, pk)
        form = BreedingCycleEditForm(
            request.POST, user=request.user, initial=iniciais_do_ciclo(c)
        )
        contexto = {"form": form, "grupos": GRUPOS, "ciclo": c}
        if not form.is_valid():
            return render(request, self.template_name, contexto)
        dados = {
            k: v
            for k, v in form.cleaned_data.items()
            if k not in ("farm", "season", "edit_reason")
        }
        try:
            services.editar_ciclo(
                c, dados, usuario=request.user, motivo=form.cleaned_data["edit_reason"]
            )
        except ERROS as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(request, f"✓ Ciclo {c.code} corrigido.")
        return redirect("reproduction:detalhe", pk=c.pk)


class CicloExcluirView(ExclusaoComImpactoView):
    model = BreedingCycle
    titulo = "Excluir ciclo reprodutivo"

    def url_do_registro(self, registro):
        return reverse("reproduction:detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        services.excluir_ciclo(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )


class CicloRestaurarView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        c = _ciclo(request, pk)
        try:
            services.restaurar_ciclo(c, usuario=request.user)
        except ERROS as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Ciclo {c.code} restaurado.")
        return redirect("reproduction:detalhe", pk=c.pk)
