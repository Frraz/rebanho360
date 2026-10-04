"""Fino. Recebe request, chama service/selector, devolve template."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.mixins import ScopedQuerysetMixin
from apps.livestock import selectors, services
from apps.livestock.forms import AnimalCategoryForm, BreedForm, LotForm
from apps.livestock.models import AnimalCategory, Breed, Lot
from apps.livestock.permissions import GerenciaLivestockMixin, GerenciaLoteMixin


class _SalvarComAuditoriaMixin:
    def form_valid(self, form):
        criando = form.instance.pk is None
        self.object = form.save(commit=False)
        services.salvar_cadastro(
            self.object, usuario=self.request.user, criando=criando
        )
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class AnimalCategoryListView(GerenciaLivestockMixin, ListView):
    template_name = "livestock/category_list.html"
    context_object_name = "categorias"

    def get_queryset(self):
        return selectors.listar_categorias()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sugestoes"] = {
            categoria.pk: selectors.sugerir_proxima_categoria(categoria)
            for categoria in context["categorias"]
        }
        return context


class AnimalCategoryCreateView(
    GerenciaLivestockMixin, _SalvarComAuditoriaMixin, CreateView
):
    model = AnimalCategory
    form_class = AnimalCategoryForm
    template_name = "livestock/category_form.html"
    success_url = reverse_lazy("livestock:categoria_lista")
    success_message = "✓ Categoria cadastrada."


class AnimalCategoryUpdateView(
    GerenciaLivestockMixin, _SalvarComAuditoriaMixin, UpdateView
):
    model = AnimalCategory
    form_class = AnimalCategoryForm
    template_name = "livestock/category_form.html"
    success_url = reverse_lazy("livestock:categoria_lista")
    success_message = "✓ Categoria atualizada."


class BreedListView(GerenciaLivestockMixin, ListView):
    template_name = "livestock/breed_list.html"
    context_object_name = "racas"

    def get_queryset(self):
        return selectors.listar_racas()


class BreedCreateView(GerenciaLivestockMixin, _SalvarComAuditoriaMixin, CreateView):
    model = Breed
    form_class = BreedForm
    template_name = "livestock/breed_form.html"
    success_url = reverse_lazy("livestock:raca_lista")
    success_message = "✓ Raça cadastrada."


class BreedUpdateView(GerenciaLivestockMixin, _SalvarComAuditoriaMixin, UpdateView):
    model = Breed
    form_class = BreedForm
    template_name = "livestock/breed_form.html"
    success_url = reverse_lazy("livestock:raca_lista")
    success_message = "✓ Raça atualizada."


class LotListView(ScopedQuerysetMixin, ListView):
    """Ver os lotes é de todo usuário com acesso à fazenda — criar/editar
    é que é restrito (`GerenciaLoteMixin`)."""

    model = Lot
    template_name = "livestock/lot_list.html"
    context_object_name = "lotes"
    # Cada página pede 50 lotes ao banco; a lista inteira nunca vem de uma vez.
    paginate_by = 50

    def get_queryset(self):
        return selectors.listar_lotes_para(self.request.user)


class LotCreateView(GerenciaLoteMixin, CreateView):
    model = Lot
    form_class = LotForm
    template_name = "livestock/lot_form.html"
    success_url = reverse_lazy("livestock:lote_lista")

    def form_valid(self, form):
        lot = form.save(commit=False)
        services.criar_lote(lot, usuario=self.request.user)
        self.object = lot
        messages.success(self.request, f"✓ Lote {lot.code} criado.")
        return redirect(self.get_success_url())


class LotUpdateView(GerenciaLoteMixin, UpdateView):
    model = Lot
    form_class = LotForm
    template_name = "livestock/lot_form.html"
    success_url = reverse_lazy("livestock:lote_lista")

    def get_queryset(self):
        return Lot.objects.for_user(self.request.user)

    def form_valid(self, form):
        lot = form.save(commit=False)
        services.editar_lote(lot, usuario=self.request.user)
        messages.success(self.request, f"✓ Lote {lot.code} atualizado.")
        return redirect(self.get_success_url())


class LotDetailView(LoginRequiredMixin, DetailView):
    """F1-13 — a tela central do sistema (docs/fluxos/01#a-tela-central-o-lote).
    Os avisos de dado faltando são o ponto: "—" em vez de zero."""

    model = Lot
    template_name = "livestock/lot_detail.html"
    context_object_name = "lote"

    def get_queryset(self):
        return Lot.objects.for_user(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bruto = self.request.GET.get("rendimento_entrada", "").replace(",", ".")
        try:
            rendimento_entrada = Decimal(bruto) if bruto else None
        except InvalidOperation:
            rendimento_entrada = None
        context["detalhe"] = selectors.detalhe_do_lote(
            self.object, rendimento_entrada=rendimento_entrada
        )
        context["rendimento_informado"] = bruto if rendimento_entrada else ""
        return context


def sugestao_evolucao(request, pk):
    """Endpoint HTMX: devolve a categoria sugerida para evolução — nunca
    aplica automaticamente, só preenche a sugestão no formulário."""
    categoria = get_object_or_404(AnimalCategory, pk=pk)
    sugerida = selectors.sugerir_proxima_categoria(categoria)
    return JsonResponse({"id": sugerida.pk, "name": sugerida.name} if sugerida else {})
