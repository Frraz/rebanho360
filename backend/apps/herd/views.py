"""Fino. Recebe request, chama service/selector, devolve template."""

import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import ListView, TemplateView

from apps.core import context as ctx
from apps.core import reversible
from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.herd import selectors, services
from apps.herd.forms import MovementEditForm, MovementForm, WeighingForm
from apps.herd.models import HerdMovement, Weighing
from apps.herd.permissions import LancaMovimentoMixin
from apps.properties.models import Farm


class PositionView(LoginRequiredMixin, TemplateView):
    """F1-10 — posição do rebanho: substitui o quadro-resumo das abas de
    fazenda e o consolidado que `GERAL` tentava ser."""

    template_name = "herd/position.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET

        farm = None
        if params.get("farm"):
            farm = Farm.objects.filter(pk=params["farm"]).first()

        season = ctx.current_season(self.request, ctx.current_company())
        until = params.get("until") or datetime.date.today().isoformat()

        linhas, total = selectors.posicao_do_rebanho(
            user=self.request.user, farm=farm, season=season, until=until
        )
        context.update(
            {
                "linhas": linhas,
                "total": total,
                "season": season,
                "until": until,
                "farm_selecionada": farm,
                "fazendas": ctx.available_farms(self.request.user),
            }
        )
        return context


class MovementCreateView(LancaMovimentoMixin, TemplateView):
    """F1-11 — a tela mais usada do sistema. Desenhada para o celular
    primeiro (docs/ux/01#formulário-de-campo)."""

    template_name = "herd/movement_form.html"

    def get(self, request, *args, **kwargs):
        form = MovementForm(user=request.user, initial={"date": datetime.date.today()})
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = MovementForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        dados = form.cleaned_data
        try:
            movimento = services.registrar_movimento(
                type=dados["type"],
                date=dados["date"],
                quantity=dados["quantity"],
                total_weight_kg=dados["total_weight_kg"],
                usuario=request.user,
                origin_farm=dados["origin_farm"],
                origin_lot=dados["origin_lot"],
                origin_category=dados["origin_category"],
                destination_farm=dados["destination_farm"],
                destination_lot=dados["destination_lot"],
                destination_category=dados["destination_category"],
                partner=dados["partner"],
                reason=dados["reason"],
                notes=dados["notes"],
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form})

        messages.success(
            request,
            f"✓ Movimentação {movimento.code} registrada. "
            f"{movimento.quantity} cabeças.",
        )
        return redirect(reverse("herd:lancar_movimento") + "?ok=1")


class MovementListView(LoginRequiredMixin, ListView):
    template_name = "herd/movement_list.html"
    context_object_name = "movimentos"
    paginate_by = 30

    def get_queryset(self):
        return selectors.listar_movimentos_para(self.request.user).select_related(
            "origin_farm", "destination_farm", "origin_category", "destination_category"
        )


def _get_movimento(request, pk) -> HerdMovement:
    """Movimento dentro do escopo do usuário: fora dele, 404 — nunca 403,
    que confirmaria que o registro existe (ADR 0003)."""
    return get_object_or_404(selectors.listar_movimentos_para(request.user), pk=pk)


def _recusar_se_gerado_por_documento(request, movimento):
    """Movimento gerado por compra ou venda não se edita direto: a correção
    é no documento, e o movimento acompanha (docs/regras-negocio/06)."""
    if movimento.origin_purchase_id:
        messages.error(
            request,
            f"Esta movimentação foi gerada pela compra "
            f"{movimento.origin_purchase.code}. Corrija ou exclua a compra — "
            "a movimentação acompanha.",
        )
        return redirect("purchases:detalhe", pk=movimento.origin_purchase_id)
    if movimento.origin_sale_id:
        messages.error(
            request,
            f"Esta movimentação foi gerada pela venda "
            f"{movimento.origin_sale.code}. Corrija ou exclua a venda — "
            "a movimentação acompanha.",
        )
        return redirect("sales:detalhe", pk=movimento.origin_sale_id)
    return None


class MovementDetailView(LoginRequiredMixin, TemplateView):
    template_name = "herd/movement_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movimento = _get_movimento(self.request, kwargs["pk"])
        context["movimento"] = movimento
        context["linhas"] = movimento.entries.select_related("farm", "lot", "category")
        context["pode_editar"] = pode_editar_confirmado(self.request.user)
        context["pode_excluir"] = pode_excluir_confirmado(self.request.user)
        return context


class MovementUpdateView(LoginRequiredMixin, TemplateView):
    template_name = "herd/movement_edit_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        movimento = _get_movimento(request, kwargs["pk"])
        if not pode_editar_confirmado(request.user):
            messages.error(
                request, "Você não tem permissão para editar este lançamento."
            )
            return redirect("herd:movimento_detalhe", pk=kwargs["pk"])
        if (recusa := _recusar_se_gerado_por_documento(request, movimento)) is not None:
            return recusa
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        movimento = _get_movimento(request, kwargs["pk"])
        form = MovementEditForm(
            user=request.user, initial=_movimento_para_form(movimento)
        )
        return render(
            request, self.template_name, {"form": form, "movimento": movimento}
        )

    def post(self, request, *args, **kwargs):
        movimento = _get_movimento(request, kwargs["pk"])
        form = MovementEditForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(
                request, self.template_name, {"form": form, "movimento": movimento}
            )

        dados = form.cleaned_data
        campos = {
            "type": dados["type"],
            "date": dados["date"],
            "quantity": dados["quantity"],
            "total_weight_kg": dados["total_weight_kg"],
            "origin_farm": dados["origin_farm"],
            "origin_lot": dados["origin_lot"],
            "origin_category": dados["origin_category"],
            "destination_farm": dados["destination_farm"],
            "destination_lot": dados["destination_lot"],
            "destination_category": dados["destination_category"],
            "partner": dados["partner"],
            "reason": dados["reason"],
            "notes": dados["notes"],
        }
        try:
            reversible.editar(
                movimento,
                campos,
                usuario=request.user,
                motivo=dados["edit_reason"],
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(
                request, self.template_name, {"form": form, "movimento": movimento}
            )

        messages.success(request, f"✓ Movimentação {movimento.code} corrigida.")
        return redirect("herd:movimento_detalhe", pk=movimento.pk)


def _movimento_para_form(movimento):
    return {
        "type": movimento.type,
        "date": movimento.date,
        "quantity": movimento.quantity,
        "total_weight_kg": movimento.total_weight_kg,
        "origin_farm": movimento.origin_farm_id,
        "origin_lot": movimento.origin_lot_id,
        "origin_category": movimento.origin_category_id,
        "destination_farm": movimento.destination_farm_id,
        "destination_lot": movimento.destination_lot_id,
        "destination_category": movimento.destination_category_id,
        "partner": movimento.partner_id,
        "reason": movimento.reason,
        "notes": movimento.notes,
    }


class MovementDeleteView(LoginRequiredMixin, TemplateView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        movimento = _get_movimento(request, kwargs["pk"])
        if not pode_excluir_confirmado(request.user):
            messages.error(
                request, "Você não tem permissão para excluir este lançamento."
            )
            return redirect("herd:movimento_detalhe", pk=movimento.pk)
        if (recusa := _recusar_se_gerado_por_documento(request, movimento)) is not None:
            return recusa

        motivo = request.POST.get("motivo", "")
        try:
            reversible.excluir(movimento, usuario=request.user, motivo=motivo)
        except DependencyError as exc:
            messages.error(
                request,
                "Este lançamento tem dependentes: "
                + ", ".join(str(d) for d in exc.dependents),
            )
        except BlockingDependencyError as exc:
            messages.error(request, str(exc))
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Movimentação {movimento.code} excluída.")
        return redirect("herd:movimento_detalhe", pk=movimento.pk)


class MovementRestoreView(LoginRequiredMixin, TemplateView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        movimento = _get_movimento(request, kwargs["pk"])
        if not pode_excluir_confirmado(request.user):
            messages.error(
                request, "Você não tem permissão para restaurar este lançamento."
            )
            return redirect("herd:movimento_detalhe", pk=movimento.pk)
        if (recusa := _recusar_se_gerado_por_documento(request, movimento)) is not None:
            return recusa

        try:
            reversible.restaurar(movimento, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Movimentação {movimento.code} restaurada.")
        return redirect("herd:movimento_detalhe", pk=movimento.pk)


class WeighingCreateView(LancaMovimentoMixin, TemplateView):
    """F1-14 — registrar pesagem. Não altera saldo, só peso; peso médio é
    calculado, nunca digitado."""

    template_name = "herd/weighing_form.html"

    def get(self, request, *args, **kwargs):
        # Valores iniciais pela querystring: a compra com peso leva até aqui
        # já preenchida (docs/regras-negocio/03#peso-na-compra).
        inicial = {"date": datetime.date.today()}
        for campo in ("date", "farm", "lot", "reason", "head_count", "total_weight_kg"):
            if request.GET.get(campo):
                inicial[campo] = request.GET[campo]
        form = WeighingForm(user=request.user, initial=inicial)
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = WeighingForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        dados = form.cleaned_data
        try:
            pesagem = services.registrar_pesagem(
                date=dados["date"],
                farm=dados["farm"],
                lot=dados["lot"],
                reason=dados["reason"],
                head_count=dados["head_count"],
                total_weight_kg=dados["total_weight_kg"],
                usuario=request.user,
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form})

        messages.success(
            request,
            f"✓ Pesagem registrada. Peso médio: {pesagem.average_weight_kg} kg.",
        )
        return redirect(reverse("livestock:lote_detalhe", args=[pesagem.lot_id]))


class WeighingListView(LoginRequiredMixin, ListView):
    template_name = "herd/weighing_list.html"
    context_object_name = "pesagens"
    paginate_by = 30

    def get_queryset(self):
        return Weighing.objects.for_user(self.request.user).select_related(
            "farm", "lot"
        )


class ReconciliationView(LoginRequiredMixin, TemplateView):
    """F1-15 — conciliação de transferências. Alimenta o painel de
    pendências (docs/fluxos/01#pendências-do-rebanho-na-tela)."""

    template_name = "herd/reconciliation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pendencias"] = selectors.conciliar_transferencias()
        return context


def lotes_da_fazenda(request):
    """Fragmento HTMX: opções de lote para a fazenda escolhida — a
    seleção de fazenda troca o que aparece aqui (cascading select)."""
    campo_destino = request.GET.get("campo", "origin_lot")
    farm_id = (
        request.GET.get("farm_id")
        or request.GET.get("origin_farm")
        or request.GET.get("destination_farm")
        or request.GET.get("farm")
    )
    lotes = selectors.lotes_da_fazenda(request.user, farm_id)
    return render(
        request,
        "herd/_opcoes_lote.html",
        {"lotes": lotes, "campo": campo_destino},
    )
