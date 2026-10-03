"""Fino. Recebe request, chama service/selector, devolve template."""

import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
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
from apps.sales import carcass, selectors, services
from apps.sales.forms import SaleEditForm, SaleEntryForm
from apps.sales.models import Sale, SaleType
from apps.sales.permissions import (
    LancaVendaMixin,
    pode_confirmar_venda,
    pode_lancar_venda,
)


def _get_venda(request, pk) -> Sale:
    """Venda dentro do escopo do usuário: fora dele, 404 — nunca 403, que
    confirmaria que o registro existe (ADR 0003)."""
    return get_object_or_404(Sale.objects.for_user(request.user), pk=pk)


def _initial_da_venda(venda: Sale) -> dict:
    return {
        "type": venda.type,
        "date": venda.date,
        "buyer": venda.buyer_id,
        "farm": venda.farm_id,
        "lot": venda.lot_id,
        "category": venda.category_id,
        "head_count": venda.head_count,
        "total_weight_kg": venda.total_weight_kg,
        "carcass_weight_kg": venda.carcass_weight_kg,
        "total_value": venda.total_value,
        "sale_form": venda.sale_form,
        "payment_days": venda.payment_days,
        "partnership": venda.partnership,
        "notes": venda.notes,
    }


def _decimal(valor):
    try:
        return (
            Decimal(str(valor).replace(",", ".")) if valor not in (None, "") else None
        )
    except InvalidOperation:
        return None


def _calcular_previa(dados) -> carcass.IndicadoresDaVenda:
    """Os indicadores "ao digitar": o número vem do mesmo serviço que a
    tela de detalhe usa — o template não calcula."""
    try:
        cabecas = int(dados.get("head_count") or 0)
    except (TypeError, ValueError):
        cabecas = 0
    return carcass.calcular_carcaca(
        head_count=cabecas,
        total_weight_kg=_decimal(dados.get("total_weight_kg")),
        total_value=_decimal(dados.get("total_value")),
        carcass_weight_kg=(
            _decimal(dados.get("carcass_weight_kg"))
            if dados.get("type") != SaleType.VENDA
            else None
        ),
    )


def _contexto_form(form, **extra) -> dict:
    dados = {}
    if form.is_bound:
        dados = {k: form.data.get(k) for k in form.fields}
    elif form.initial:
        dados = form.initial
    return {"form": form, "previa": _calcular_previa(dados), **extra}


@login_required
def previa_indicadores(request):
    """Fragmento HTMX com os indicadores da venda em digitação."""
    return render(
        request,
        "sales/_previa.html",
        {
            "previa": _calcular_previa(request.GET),
            "e_venda_viva": request.GET.get("type") == SaleType.VENDA,
        },
    )


class SaleListView(LoginRequiredMixin, TemplateView):
    template_name = "sales/sale_list.html"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        season = ctx.current_season(self.request, ctx.current_company())
        farm = ctx.current_farm(self.request, user)
        situacao = self.request.GET.get("situacao", "")
        sem_carcaca = self.request.GET.get("sem_carcaca") == "1"
        qs = selectors.listar_vendas_para(
            user, season=season, farm=farm, situacao=situacao, sem_carcaca=sem_carcaca
        )
        pagina = Paginator(qs, self.paginate_by).get_page(self.request.GET.get("page"))
        vendas = list(pagina.object_list)
        context.update(
            {
                "page_obj": pagina,
                # Cada linha traz os indicadores do serviço — o template só mostra.
                "vendas": [(v, carcass.indicadores_da_venda(v)) for v in vendas],
                "season": season,
                "situacao": situacao,
                "sem_carcaca": sem_carcaca,
                "pode_lancar": pode_lancar_venda(user),
            }
        )
        return context


class SaleCreateView(LancaVendaMixin, View):
    template_name = "sales/sale_form.html"

    def get(self, request):
        form = SaleEntryForm(
            user=request.user,
            initial={
                "date": datetime.date.today(),
                "type": SaleType.ABATE,
                "farm": ctx.current_farm(request, request.user),
            },
        )
        return render(request, self.template_name, _contexto_form(form))

    def post(self, request):
        form = SaleEntryForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, _contexto_form(form))

        acao = request.POST.get("acao", "rascunho")
        try:
            venda = services.criar_venda(usuario=request.user, **form.dados_limpos())
            if acao == "confirmar":
                services.confirmar_venda(venda, usuario=request.user)
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, _contexto_form(form))

        if acao == "confirmar":
            return _redirecionar_apos_confirmar(request, venda)
        messages.success(
            request, f"✓ Rascunho {venda.code} salvo. Nada saiu do rebanho ainda."
        )
        return redirect("sales:detalhe", pk=venda.pk)


def _redirecionar_apos_confirmar(request, venda):
    venda.refresh_from_db()
    venda.lot.refresh_from_db()
    texto = (
        f"✓ Venda {venda.code} confirmada. {venda.head_count} cabeças saíram "
        f"do lote {venda.lot.code}."
    )
    if venda.lot.status == "ENCERRADO":
        texto += f" O lote {venda.lot.code} ficou sem animais e foi encerrado."
    messages.success(request, texto)
    return redirect("sales:detalhe", pk=venda.pk)


def _contexto_financeiro(venda: Sale, user) -> dict:
    """O bloco "Financeiro" da tela: o título a receber que a venda gerou e o
    botão para gerar, se ela já estava confirmada antes do financeiro."""
    from apps.finance.permissions import pode_gerenciar_titulos, pode_ver_titulos

    if not pode_ver_titulos(user):
        return {"ver_financeiro": False}
    titulos = list(venda.invoices.select_related("payee").order_by("id"))
    return {
        "ver_financeiro": True,
        "titulos": titulos,
        "pode_gerar_titulos": venda.status == Status.CONFIRMADA
        and not titulos
        and pode_gerenciar_titulos(user),
    }


class SaleDetailView(LoginRequiredMixin, TemplateView):
    template_name = "sales/sale_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        venda = _get_venda(self.request, kwargs["pk"])
        user = self.request.user
        confirmada = venda.status == Status.CONFIRMADA
        rascunho = venda.status == Status.RASCUNHO
        context.update(
            {
                "venda": venda,
                "indicadores": carcass.indicadores_da_venda(venda),
                "alertas": services.alertas_da_venda(venda),
                "movimento": venda.movements.order_by("-id").first(),
                **_contexto_financeiro(venda, user),
                "pode_confirmar": pode_confirmar_venda(user) and rascunho,
                "pode_editar": (
                    pode_editar_confirmado(user)
                    if confirmada
                    else pode_lancar_venda(user) and rascunho
                ),
                "pode_excluir": (
                    pode_excluir_confirmado(user)
                    if confirmada
                    else pode_lancar_venda(user) and rascunho
                ),
                "pode_restaurar": pode_excluir_confirmado(user)
                and venda.status == Status.EXCLUIDA,
            }
        )
        return context


class SaleConfirmView(LoginRequiredMixin, View):
    """GET mostra o que confirmar vai fazer; POST confirma."""

    template_name = "sales/sale_confirm.html"

    def get(self, request, pk):
        venda = _get_venda(request, pk)
        return render(
            request,
            self.template_name,
            {
                "venda": venda,
                "efeitos": _efeitos_da_confirmacao(venda),
                "alertas": services.alertas_da_venda(venda),
            },
        )

    def post(self, request, pk):
        venda = _get_venda(request, pk)
        try:
            services.confirmar_venda(venda, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
            return redirect("sales:detalhe", pk=venda.pk)
        return _redirecionar_apos_confirmar(request, venda)


def _efeitos_da_confirmacao(venda: Sale) -> list[str]:
    from apps.finance.services import descrever_titulos_da_origem

    efeitos = [
        f"{venda.head_count} cabeças de {venda.category} saem do lote "
        f"{venda.lot.code} ({venda.farm})"
    ]
    return (
        efeitos
        + ["se o lote ficar sem animais, ele é encerrado"]
        + descrever_titulos_da_origem(venda)
    )


class SaleUpdateView(LoginRequiredMixin, View):
    template_name = "sales/sale_edit_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        venda = _get_venda(request, kwargs["pk"])
        pode = (
            pode_editar_confirmado(request.user)
            if venda.status == Status.CONFIRMADA
            else pode_lancar_venda(request.user) and venda.status == Status.RASCUNHO
        )
        if not pode:
            messages.error(request, "Esta venda não pode ser editada por você agora.")
            return redirect("sales:detalhe", pk=venda.pk)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        venda = _get_venda(request, pk)
        form = SaleEditForm(user=request.user, initial=_initial_da_venda(venda))
        return render(request, self.template_name, _contexto_form(form, venda=venda))

    def post(self, request, pk):
        venda = _get_venda(request, pk)
        form = SaleEditForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(
                request, self.template_name, _contexto_form(form, venda=venda)
            )

        dados = form.dados_limpos()
        motivo = dados.pop("edit_reason", "")
        confirmada = venda.status == Status.CONFIRMADA
        if confirmada and not motivo.strip():
            form.add_error("edit_reason", "Informe o motivo da correção.")
            return render(
                request, self.template_name, _contexto_form(form, venda=venda)
            )

        try:
            if confirmada:
                services.editar_venda(venda, dados, usuario=request.user, motivo=motivo)
            else:
                services.editar_rascunho(venda, dados, usuario=request.user)
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(
                request, self.template_name, _contexto_form(form, venda=venda)
            )

        messages.success(request, f"✓ Venda {venda.code} corrigida.")
        return redirect("sales:detalhe", pk=venda.pk)


class SaleDeleteView(ExclusaoComImpactoView):
    model = Sale

    def url_do_registro(self, registro):
        return reverse("sales:detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        services.excluir_venda(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )

    def get(self, request, pk):
        # Rascunho se exclui por quem lança; confirmada, por gestor/admin.
        venda = self.get_registro(pk)
        if venda.status == Status.RASCUNHO and pode_lancar_venda(request.user):
            return render(request, self.template_name, self._contexto(venda))
        return super().get(request, pk)

    def post(self, request, pk):
        venda = self.get_registro(pk)
        if venda.status == Status.RASCUNHO and pode_lancar_venda(request.user):
            return self._excluir(request, venda)
        return super().post(request, pk)

    def _excluir(self, request, venda):
        motivo = request.POST.get("motivo", "")
        try:
            self.executar_exclusao(venda, motivo=motivo, cascata=False)
        except (BusinessError, DependencyError, BlockingDependencyError) as exc:
            return render(
                request,
                self.template_name,
                self._contexto(venda, motivo=motivo, erro=str(exc)),
            )
        messages.success(request, f"✓ Venda {venda.code} excluída.")
        return redirect(self.url_do_registro(venda))


class SaleRestoreView(LoginRequiredMixin, View):
    def post(self, request, pk):
        venda = _get_venda(request, pk)
        try:
            services.restaurar_venda(venda, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Venda {venda.code} restaurada.")
        return redirect("sales:detalhe", pk=venda.pk)
