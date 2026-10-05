"""Fino. Recebe request, chama service/selector, devolve template."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView
from django.views.generic.edit import FormView

from apps.core import context as ctx
from apps.core.mixins import ScopedQuerysetMixin
from apps.properties import selectors, services
from apps.properties.forms import FarmForm, PaddockForm
from apps.properties.models import Farm, Paddock
from apps.properties.permissions import GerenciaFazendaMixin


class _SalvarComAuditoriaMixin:
    def form_valid(self, form):
        criando = form.instance.pk is None
        self.object = form.save(commit=False)
        services.salvar_cadastro(
            self.object, usuario=self.request.user, criando=criando
        )
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class FarmListView(GerenciaFazendaMixin, ListView):
    model = Farm
    template_name = "properties/farm_list.html"
    context_object_name = "fazendas"

    def get_queryset(self):
        return selectors.listar_fazendas()


class FarmCreateView(GerenciaFazendaMixin, _SalvarComAuditoriaMixin, CreateView):
    model = Farm
    form_class = FarmForm
    template_name = "properties/farm_form.html"
    success_url = reverse_lazy("properties:fazenda_lista")
    success_message = "✓ Fazenda cadastrada."


class FarmUpdateView(GerenciaFazendaMixin, _SalvarComAuditoriaMixin, UpdateView):
    model = Farm
    form_class = FarmForm
    template_name = "properties/farm_form.html"
    success_url = reverse_lazy("properties:fazenda_lista")
    success_message = "✓ Fazenda atualizada."


class PaddockListView(ScopedQuerysetMixin, ListView):
    """Lista escopada: só os pastos das fazendas que o usuário acessa."""

    model = Paddock
    template_name = "properties/paddock_list.html"
    context_object_name = "pastos"

    def get_queryset(self):
        return selectors.listar_pastos_para(self.request.user)


class PaddockCreateView(GerenciaFazendaMixin, _SalvarComAuditoriaMixin, CreateView):
    model = Paddock
    form_class = PaddockForm
    template_name = "properties/paddock_form.html"
    success_url = reverse_lazy("properties:pasto_lista")
    success_message = "✓ Área/pasto cadastrada."


class PaddockUpdateView(GerenciaFazendaMixin, UpdateView):
    model = Paddock
    form_class = PaddockForm
    template_name = "properties/paddock_form.html"
    success_url = reverse_lazy("properties:pasto_lista")

    def get_queryset(self):
        return Paddock.objects.for_user(self.request.user)

    def form_valid(self, form):
        criando = False
        self.object = form.save(commit=False)
        services.salvar_cadastro(
            self.object, usuario=self.request.user, criando=criando
        )
        messages.success(self.request, "✓ Área/pasto atualizada.")
        return redirect(self.get_success_url())


class TrocarFazendaView(LoginRequiredMixin, FormView):
    """Seletor de fazenda do contexto fixo no topo — filtra telas, não é
    checagem de permissão (essa já é feita por `ScopedManager`/escopo)."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        farm_id = request.POST.get("farm_id")
        farm = None
        if farm_id:
            farm = ctx.available_farms(request.user).filter(pk=farm_id).first()
        ctx.set_current_farm(request, farm)
        return redirect(ctx.destino_seguro(request, reverse("dashboards:inicio")))
