"""Fino. Recebe request, chama service/selector, devolve template."""

import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.core import context as ctx
from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.views import ExclusaoComImpactoView
from apps.purchases import selectors, services
from apps.purchases.forms import PurchaseEditForm, PurchaseFilterForm, PurchaseForm
from apps.purchases.models import Purchase
from apps.purchases.permissions import (
    LancaCompraMixin,
    pode_confirmar_compra,
    pode_lancar_compra,
)


def _get_compra(request, pk) -> Purchase:
    return get_object_or_404(Purchase.objects.for_user(request.user), pk=pk)


def _initial_da_compra(compra: Purchase) -> dict:
    return {
        "date": compra.date,
        "seller": compra.seller_id,
        "destination_farm": compra.destination_farm_id,
        "category": compra.category_id,
        "head_count": compra.head_count,
        "total_weight_kg": compra.total_weight_kg,
        "animal_value": compra.animal_value,
        "freight_value": compra.freight_value,
        "commission_value": compra.commission_value,
        "tax_value": compra.tax_value,
        "lot": compra.lot_id,
        "entry_yield_percent": compra.entry_yield_percent,
        "payment_days": compra.payment_days,
        "payment_condition": compra.payment_condition_id,
        "partnership": compra.partnership,
        "notes": compra.notes,
    }


class PurchaseListView(LoginRequiredMixin, TemplateView):
    template_name = "purchases/purchase_list.html"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        season = ctx.current_season(self.request, ctx.current_company())
        farm = ctx.current_farm(self.request, user)
        filtro = PurchaseFilterForm(self.request.GET or None, user=user)
        dados = filtro.cleaned_data if filtro.is_valid() else {}
        qs = selectors.listar_compras_para(
            user,
            season=season,
            # O "Destino" do filtro vale mais que a fazenda do topo da tela.
            farm=dados.get("destino") or farm,
            situacao=dados.get("situacao", ""),
            registro=dados.get("registro", ""),
            vendedor=dados.get("vendedor"),
            data_de=dados.get("data_de"),
            data_ate=dados.get("data_ate"),
        )
        pagina = Paginator(qs, self.paginate_by).get_page(self.request.GET.get("page"))
        context.update(
            {
                "page_obj": pagina,
                "compras": pagina.object_list,
                "season": season,
                "filtro": filtro,
                "filtrando": bool(dados) and any(dados.values()),
                "pode_lancar": pode_lancar_compra(user),
            }
        )
        return context


class PurchaseCreateView(LancaCompraMixin, View):
    template_name = "purchases/purchase_form.html"

    def get(self, request):
        form = PurchaseForm(
            user=request.user,
            initial={
                "date": datetime.date.today(),
                "destination_farm": ctx.current_farm(request, request.user),
            },
        )
        return render(request, self.template_name, _contexto_form(form))

    def post(self, request):
        form = PurchaseForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, _contexto_form(form))

        acao = request.POST.get("acao", "rascunho")
        try:
            compra = services.criar_compra(usuario=request.user, **form.dados_limpos())
            if acao == "confirmar":
                services.confirmar_compra(compra, usuario=request.user)
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, _contexto_form(form))

        if acao == "confirmar":
            return _redirecionar_apos_confirmar(request, compra)
        messages.success(
            request, f"✓ Rascunho {compra.code} salvo. Nada foi lançado ainda."
        )
        return redirect("purchases:detalhe", pk=compra.pk)


def _contexto_form(form, **extra) -> dict:
    dados = {}
    if form.is_bound:
        dados = {k: form.data.get(k) for k in form.fields}
    elif form.initial:
        dados = form.initial
    return {"form": form, "previa": _calcular_previa(dados), **extra}


def _decimal(valor):
    try:
        return (
            Decimal(str(valor).replace(",", ".")) if valor not in (None, "") else None
        )
    except InvalidOperation:
        return None


def _calcular_previa(dados) -> dict:
    """Custo total e média por cabeça "ao digitar": o número vem do mesmo
    serviço que a tela de detalhe usa — o template não calcula."""
    try:
        cabecas = int(dados.get("head_count") or 0)
    except (TypeError, ValueError):
        cabecas = 0
    return services.calcular_custo_da_compra(
        head_count=cabecas,
        animal_value=_decimal(dados.get("animal_value")),
        freight_value=_decimal(dados.get("freight_value")),
        commission_value=_decimal(dados.get("commission_value")),
        tax_value=_decimal(dados.get("tax_value")),
        total_weight_kg=_decimal(dados.get("total_weight_kg")),
    )


def previa_custo(request):
    """Fragmento HTMX com custo total e média por cabeça."""
    return render(
        request,
        "purchases/_previa_custo.html",
        {"previa": _calcular_previa(request.GET)},
    )


def _redirecionar_apos_confirmar(request, compra):
    compra.refresh_from_db()
    messages.success(
        request,
        f"✓ Compra {compra.code} confirmada. {compra.head_count} cabeças deram "
        f"entrada no lote {compra.lot.code}.",
    )
    return redirect("purchases:detalhe", pk=compra.pk)


def _contexto_financeiro(compra: Purchase, user) -> dict:
    """O bloco "Financeiro" da tela: os títulos que a compra gerou e o botão
    para gerar, se ela já estava confirmada antes do financeiro existir."""
    from apps.finance.permissions import pode_gerenciar_titulos, pode_ver_titulos

    if not pode_ver_titulos(user):
        return {"ver_financeiro": False}
    titulos = list(compra.invoices.select_related("payee").order_by("id"))
    return {
        "ver_financeiro": True,
        "titulos": titulos,
        "pode_gerar_titulos": compra.status == Status.CONFIRMADA
        and not titulos
        and pode_gerenciar_titulos(user),
        "pode_novo_titulo": compra.status == Status.CONFIRMADA
        and pode_gerenciar_titulos(user),
    }


class PurchaseDetailView(LoginRequiredMixin, TemplateView):
    template_name = "purchases/purchase_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        compra = _get_compra(self.request, kwargs["pk"])
        user = self.request.user
        movimento = compra.movements.order_by("-id").first()
        context.update(
            {
                "compra": compra,
                "custo": services.custo_da_compra(compra),
                "movimento": movimento,
                "custos_gerados": compra.cost_entries.select_related("cost_center"),
                "pode_confirmar": pode_confirmar_compra(user)
                and compra.status == Status.RASCUNHO,
                "pode_editar": (
                    pode_editar_confirmado(user)
                    if compra.status == Status.CONFIRMADA
                    else pode_lancar_compra(user) and compra.status == Status.RASCUNHO
                ),
                "pode_excluir": (
                    pode_excluir_confirmado(user)
                    if compra.status == Status.CONFIRMADA
                    else pode_lancar_compra(user) and compra.status == Status.RASCUNHO
                ),
                "pode_restaurar": pode_excluir_confirmado(user)
                and compra.status == Status.EXCLUIDA,
                **_contexto_financeiro(compra, user),
                "sugerir_pesagem": compra.status == Status.CONFIRMADA
                and compra.total_weight_kg is not None
                and compra.lot_id is not None,
            }
        )
        return context


class PurchaseConfirmView(LoginRequiredMixin, View):
    """GET mostra o que confirmar vai fazer; POST confirma."""

    template_name = "purchases/purchase_confirm.html"

    def get(self, request, pk):
        compra = _get_compra(request, pk)
        return render(
            request,
            self.template_name,
            {"compra": compra, "efeitos": compra.descrever_efeitos()},
        )

    def post(self, request, pk):
        compra = _get_compra(request, pk)
        try:
            services.confirmar_compra(compra, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
            return redirect("purchases:detalhe", pk=compra.pk)
        return _redirecionar_apos_confirmar(request, compra)


class PurchaseUpdateView(LoginRequiredMixin, View):
    template_name = "purchases/purchase_edit_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        compra = _get_compra(request, kwargs["pk"])
        pode = (
            pode_editar_confirmado(request.user)
            if compra.status == Status.CONFIRMADA
            else pode_lancar_compra(request.user) and compra.status == Status.RASCUNHO
        )
        if not pode:
            messages.error(request, "Esta compra não pode ser editada por você agora.")
            return redirect("purchases:detalhe", pk=compra.pk)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        compra = _get_compra(request, pk)
        form = PurchaseEditForm(user=request.user, initial=_initial_da_compra(compra))
        return render(request, self.template_name, _contexto_form(form, compra=compra))

    def post(self, request, pk):
        compra = _get_compra(request, pk)
        form = PurchaseEditForm(request.POST, user=request.user)
        contexto = lambda: _contexto_form(form, compra=compra)  # noqa: E731
        if not form.is_valid():
            return render(request, self.template_name, contexto())

        dados = form.dados_limpos()
        motivo = dados.pop("edit_reason", "")
        confirmada = compra.status == Status.CONFIRMADA
        if confirmada and not motivo.strip():
            form.add_error("edit_reason", "Informe o motivo da correção.")
            return render(request, self.template_name, contexto())

        try:
            if confirmada:
                services.editar_compra(
                    compra, dados, usuario=request.user, motivo=motivo
                )
            else:
                services.editar_rascunho(compra, dados, usuario=request.user)
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto())

        messages.success(request, f"✓ Compra {compra.code} corrigida.")
        return redirect("purchases:detalhe", pk=compra.pk)


class PurchaseDeleteView(ExclusaoComImpactoView):
    model = Purchase

    def url_do_registro(self, registro):
        return reverse("purchases:detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        services.excluir_compra(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )

    def get(self, request, pk):
        # Rascunho se exclui por quem lança; confirmada, por gestor/admin.
        compra = self.get_registro(pk)
        if compra.status == Status.RASCUNHO and pode_lancar_compra(request.user):
            return render(request, self.template_name, self._contexto(compra))
        return super().get(request, pk)

    def post(self, request, pk):
        compra = self.get_registro(pk)
        if compra.status == Status.RASCUNHO and pode_lancar_compra(request.user):
            return self._excluir(request, compra)
        return super().post(request, pk)

    def _excluir(self, request, compra):
        motivo = request.POST.get("motivo", "")
        try:
            self.executar_exclusao(compra, motivo=motivo, cascata=False)
        except (BusinessError, DependencyError, BlockingDependencyError) as exc:
            return render(
                request,
                self.template_name,
                self._contexto(compra, motivo=motivo, erro=str(exc)),
            )
        messages.success(request, f"✓ Compra {compra.code} excluída.")
        return redirect(self.url_do_registro(compra))


class PurchaseRestoreView(LoginRequiredMixin, View):
    def post(self, request, pk):
        compra = _get_compra(request, pk)
        try:
            services.restaurar_compra(compra, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Compra {compra.code} restaurada.")
        return redirect("purchases:detalhe", pk=compra.pk)
