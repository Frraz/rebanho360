"""Fino. Recebe request, chama service/selector, devolve template.

Registro fora do escopo de fazenda devolve 404, nunca 403 (ADR 0003): o
`ScopedManager` leva o escopo pelo compromisso, e item/carga/linha passam por
quem os contém.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.commercial import selectors as comercial
from apps.commercial.commission import escolher_regra
from apps.core import context as ctx
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.views import ExclusaoComImpactoView
from apps.documents.permissions import pode_ver_documento
from apps.livestock.models import Lot
from apps.procurement import (
    closing,
    commitments,
    contract,
    grading,
    receivings,
    selectors,
    settlement,
    trips,
)
from apps.procurement.forms import (
    AllocationFormSet,
    BuyerFormSet,
    CommissionForm,
    CommitmentEditForm,
    CommitmentForm,
    EncerrarOperacaoForm,
    FiscalNoteFormSet,
    GradingLineFormSet,
    ItemFormSet,
    LoadFormSet,
    ReabrirOperacaoForm,
    ReasonForm,
    ReceivingForm,
    ReceivingLineFormSet,
    SettlementLineFormSet,
    TripEditForm,
    TripForm,
    cargas_iniciais,
    compradores_do_formset,
    compradores_iniciais,
    entradas_do_formset,
    itens_iniciais,
    linhas_de_recebimento_iniciais,
    linhas_de_romaneio_iniciais,
    linhas_do_acerto_iniciais,
    notas_iniciais,
)
from apps.procurement.models import (
    Commission,
    Commitment,
    CommitmentItem,
    PriceBasis,
    Receiving,
    Settlement,
    Trip,
)
from apps.procurement.permissions import (
    AprovaOCompromissoMixin,
    LancaNoCicloMixin,
    VeOCicloMixin,
    pode_aprovar_o_acerto,
    pode_aprovar_o_compromisso,
    pode_encerrar_a_operacao,
    pode_lancar_no_ciclo,
)
from apps.procurement.settlement import calcular_acerto

ERROS_DE_NEGOCIO = (BusinessError, BlockingDependencyError)


# --------------------------------------------------------------------------
# Busca com escopo
# --------------------------------------------------------------------------


def _compromisso(request, pk) -> Commitment:
    return get_object_or_404(Commitment.objects.for_user(request.user), pk=pk)


def _item(request, pk) -> CommitmentItem:
    compromissos = Commitment.objects.for_user(request.user)
    return get_object_or_404(
        CommitmentItem.objects.select_related("commitment", "category"),
        pk=pk,
        commitment__in=compromissos,
    )


def _viagem(request, pk) -> Trip:
    return get_object_or_404(
        Trip.objects.for_user(request.user).select_related("commitment", "carrier"),
        pk=pk,
    )


def _recebimento(request, pk) -> Receiving:
    return get_object_or_404(
        Receiving.objects.for_user(request.user).select_related("trip__commitment"),
        pk=pk,
    )


def _acerto(request, pk) -> Settlement:
    return get_object_or_404(
        Settlement.objects.for_user(request.user).select_related("commitment"), pk=pk
    )


def _pode_editar(user, registro) -> bool:
    if registro.status == Status.CONFIRMADA:
        return pode_editar_confirmado(user)
    return registro.status == Status.RASCUNHO and pode_lancar_no_ciclo(user)


def _pode_excluir(user, registro) -> bool:
    if registro.status == Status.CONFIRMADA:
        return pode_excluir_confirmado(user)
    return registro.status == Status.RASCUNHO and pode_lancar_no_ciclo(user)


# --------------------------------------------------------------------------
# Exclusão e restauração (compartilhadas)
# --------------------------------------------------------------------------


class ExclusaoDoCicloView(ExclusaoComImpactoView):
    """Exclusão com análise de impacto. Rascunho se exclui por quem lança;
    registro confirmado, por gestor ou administrador (pendência #9)."""

    def pode_excluir(self, registro) -> bool:
        return _pode_excluir(self.request.user, registro)


class CompromissoExcluirView(ExclusaoDoCicloView):
    model = Commitment

    def url_do_registro(self, registro):
        return reverse("procurement:compromisso_detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        commitments.excluir_compromisso(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )


class ViagemExcluirView(ExclusaoDoCicloView):
    model = Trip

    def url_do_registro(self, registro):
        return reverse("procurement:viagem_detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        trips.excluir_viagem(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )


class RecebimentoExcluirView(ExclusaoDoCicloView):
    model = Receiving

    def url_do_registro(self, registro):
        return reverse("procurement:recebimento_detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        receivings.excluir_recebimento(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )


class AcertoExcluirView(ExclusaoDoCicloView):
    model = Settlement

    def url_do_registro(self, registro):
        return reverse("procurement:acerto_detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        closing.excluir_acerto(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )


class AcertoReabrirView(ExclusaoComImpactoView):
    """Reabertura formal: a mesma tela de impacto da exclusão, com os verbos
    certos. Baixa de título, nota fiscal e safra encerrada aparecem como
    bloqueio, cada um com o caminho."""

    model = Settlement
    titulo = "Reabrir acerto"

    def pode_excluir(self, registro) -> bool:
        return pode_aprovar_o_acerto(self.request.user)

    def url_do_registro(self, registro):
        return reverse("procurement:acerto_detalhe", args=[registro.pk])

    def _contexto(self, registro, **extra):
        return super()._contexto(
            registro,
            verbo="Reabrir acerto",
            verbo_infinitivo="reabrir",
            motivo_de="da reabertura",
            **extra,
        )

    def executar_exclusao(self, registro, *, motivo, cascata):
        closing.reabrir_acerto(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )

    def get(self, request, pk):
        registro = self.get_registro(pk)
        if registro.status != Status.CONFIRMADA:
            messages.error(request, "Só se reabre um acerto aprovado.")
            return redirect(self.url_do_registro(registro))
        return super().get(request, pk)

    def post(self, request, pk):
        registro = self.get_registro(pk)
        if registro.status != Status.CONFIRMADA:
            messages.error(request, "Só se reabre um acerto aprovado.")
            return redirect(self.url_do_registro(registro))
        resposta = super().post(request, pk)
        if resposta.status_code == 302:
            messages.success(
                request,
                f"✓ Acerto {registro.code} reaberto. As compras e o que elas "
                "geraram foram desfeitos; corrija e aprove de novo.",
            )
        return resposta


def _restaurar(request, registro, servico, rotulo_do_registro):
    try:
        servico(registro, usuario=request.user)
    except ERROS_DE_NEGOCIO as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"✓ {rotulo_do_registro} restaurado.")


class CompromissoRestaurarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        c = _compromisso(request, pk)
        _restaurar(
            request, c, commitments.restaurar_compromisso, f"Compromisso {c.code}"
        )
        return redirect("procurement:compromisso_detalhe", pk=c.pk)


class ViagemRestaurarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        v = _viagem(request, pk)
        _restaurar(request, v, trips.restaurar_viagem, f"Viagem {v.code}")
        return redirect("procurement:viagem_detalhe", pk=v.pk)


class RecebimentoRestaurarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        r = _recebimento(request, pk)
        _restaurar(
            request, r, receivings.restaurar_recebimento, f"Recebimento {r.code}"
        )
        return redirect("procurement:recebimento_detalhe", pk=r.pk)


class AcertoRestaurarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        a = _acerto(request, pk)
        _restaurar(request, a, closing.restaurar_acerto, f"Acerto {a.code}")
        return redirect("procurement:acerto_detalhe", pk=a.pk)


# --------------------------------------------------------------------------
# Compromisso
# --------------------------------------------------------------------------


def _lotes_do_usuario(user):
    return Lot.objects.for_user(user).exclude(status="EXCLUIDO").order_by("code")


class CompromissoListView(VeOCicloMixin, TemplateView):
    template_name = "procurement/compromisso_list.html"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        season = ctx.current_season(self.request, ctx.current_company())
        farm = ctx.current_farm(self.request, user)
        situacao = self.request.GET.get("situacao", "")
        qs = selectors.listar_compromissos_para(
            user, season=season, farm=farm, situacao=situacao
        )
        pagina = Paginator(qs, self.paginate_by).get_page(self.request.GET.get("page"))
        etapas = selectors.etapas_dos_compromissos(pagina.object_list)
        linhas = [{"compromisso": c, "etapa": etapas[c.pk]} for c in pagina.object_list]
        context.update(
            {
                "page_obj": pagina,
                "linhas": linhas,
                "season": season,
                "situacao": situacao,
                "pode_lancar": pode_lancar_no_ciclo(user),
            }
        )
        return context


def _formset_de_compradores(*, initial=None, data=None):
    return BuyerFormSet(data, initial=initial, prefix="compradores")


def _formset_de_itens(request, *, initial=None, data=None):
    return ItemFormSet(
        data,
        initial=initial,
        prefix="itens",
        form_kwargs={"farm_lots": _lotes_do_usuario(request.user)},
    )


def _contexto_do_compromisso(form, formset, compradores, *, user=None, **extra):
    return {
        "form": form,
        "formset": formset,
        "compradores": compradores,
        "pode_aprovar": user is not None and pode_aprovar_o_compromisso(user),
        **extra,
    }


class CompromissoNovoView(LancaNoCicloMixin, View):
    template_name = "procurement/compromisso_form.html"

    def get(self, request):
        form = CommitmentForm(
            user=request.user,
            initial={
                "date": datetime.date.today(),
                "destination_farm": ctx.current_farm(request, request.user),
            },
        )
        formset = _formset_de_itens(request, initial=[{"entry_yield_percent": 50}])
        compradores = _formset_de_compradores(initial=[{}])
        return render(
            request,
            self.template_name,
            _contexto_do_compromisso(form, formset, compradores, user=request.user),
        )

    def post(self, request):
        form = CommitmentForm(request.POST, user=request.user)
        formset = _formset_de_itens(request, data=request.POST)
        compradores = _formset_de_compradores(data=request.POST)
        contexto = _contexto_do_compromisso(
            form, formset, compradores, user=request.user
        )
        if not (form.is_valid() & formset.is_valid() & compradores.is_valid()):
            return render(request, self.template_name, contexto)

        acao = request.POST.get("acao", "rascunho")
        if acao == "aprovar" and not pode_aprovar_o_compromisso(request.user):
            # Recusa antes de criar: o rascunho não nasce pela metade.
            form.add_error(
                None,
                "Você não tem permissão para aprovar compromissos. Salve em "
                "negociação: a aprovação é de administrador ou gestor.",
            )
            return render(request, self.template_name, contexto)
        try:
            compromisso = commitments.criar_compromisso(
                usuario=request.user,
                itens=entradas_do_formset(formset),
                compradores=compradores_do_formset(compradores),
                **form.dados_limpos(),
            )
            if acao == "aprovar":
                commitments.aprovar_compromisso(compromisso, usuario=request.user)
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)

        if acao == "aprovar":
            messages.success(
                request,
                f"✓ Compromisso {compromisso.code} aprovado. Próximo passo: "
                "programar a viagem.",
            )
        else:
            messages.success(
                request,
                f"✓ Compromisso {compromisso.code} salvo em negociação. "
                "Nada foi lançado ainda.",
            )
        return redirect("procurement:compromisso_detalhe", pk=compromisso.pk)


class CompromissoEditarView(LancaNoCicloMixin, View):
    template_name = "procurement/compromisso_form.html"

    def _initial(self, c):
        return {
            campo: (
                getattr(c, f"{campo}_id", None)
                if campo in ("seller", "destination_farm", "payment_condition")
                else getattr(c, campo)
            )
            for campo in commitments.CAMPOS_EDITAVEIS
            if campo != "commissioned"
        }

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            c = _compromisso(request, kwargs["pk"])
            if not _pode_editar(request.user, c):
                messages.error(
                    request, "Este compromisso não pode ser editado por você agora."
                )
                return redirect("procurement:compromisso_detalhe", pk=c.pk)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        c = _compromisso(request, pk)
        form = CommitmentEditForm(user=request.user, initial=self._initial(c))
        formset = _formset_de_itens(request, initial=itens_iniciais(c))
        compradores = _formset_de_compradores(initial=compradores_iniciais(c) or [{}])
        return render(
            request,
            self.template_name,
            _contexto_do_compromisso(form, formset, compradores, compromisso=c),
        )

    def post(self, request, pk):
        c = _compromisso(request, pk)
        form = CommitmentEditForm(request.POST, user=request.user)
        formset = _formset_de_itens(request, data=request.POST)
        compradores = _formset_de_compradores(data=request.POST)
        contexto = _contexto_do_compromisso(form, formset, compradores, compromisso=c)
        if not (form.is_valid() & formset.is_valid() & compradores.is_valid()):
            return render(request, self.template_name, contexto)

        dados = form.dados_limpos()
        motivo = form.cleaned_data.get("edit_reason", "")
        if c.status == Status.CONFIRMADA and not motivo.strip():
            form.add_error("edit_reason", "Informe o motivo da correção.")
            return render(request, self.template_name, contexto)
        try:
            commitments.editar_compromisso(
                c,
                dados,
                entradas_do_formset(formset),
                usuario=request.user,
                motivo=motivo,
                compradores=compradores_do_formset(compradores),
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(request, f"✓ Compromisso {c.code} corrigido.")
        return redirect("procurement:compromisso_detalhe", pk=c.pk)


class CompromissoDetalheView(VeOCicloMixin, TemplateView):
    template_name = "procurement/compromisso_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        c = _compromisso(self.request, kwargs["pk"])
        calculo = calcular_acerto(c)
        viagens = list(
            c.trips.exclude(status=Status.EXCLUIDA)
            .select_related("carrier")
            .prefetch_related("loads", "receivings")
            .order_by("pickup_date", "id")
        )
        linhas_de_viagem = []
        for v in viagens:
            frete = trips.frete_da_viagem(v)
            recebimento = v.receivings.exclude(status=Status.EXCLUIDA).first()
            linhas_de_viagem.append(
                {
                    "viagem": v,
                    "frete": frete,
                    "cabecas": trips.cabecas_da_viagem(v),
                    "recebimento": recebimento,
                    "quebra": (
                        receivings.quebra_da_viagem(recebimento)
                        if recebimento
                        else None
                    ),
                    "avisos": trips.avisos_da_viagem(v),
                }
            )
        comissao = commitments.comissao_do(c)
        acerto = selectors.acerto_ativo(c)
        valores_da_comissao = {x.commission.pk: x for x in calculo.comissoes}
        comissoes = [
            {
                "comissao": x,
                "valor": valores_da_comissao.get(x.pk),
            }
            for x in commitments.comissoes_do(c)
        ]
        aprovado = c.status == Status.CONFIRMADA
        context.update(
            {
                "compromisso": c,
                "etapa": selectors.etapa_do_compromisso(c),
                "situacao_financeira": selectors.situacao_financeira(c),
                "calculo": calculo,
                "itens": calculo.itens,
                "viagens": linhas_de_viagem,
                "comissao": comissao,
                "comissoes": comissoes,
                "acerto": acerto,
                "pode_encerrar": aprovado
                and not c.encerrada
                and acerto is not None
                and acerto.status == Status.CONFIRMADA
                and pode_encerrar_a_operacao(user),
                "pode_reabrir_operacao": c.encerrada and pode_encerrar_a_operacao(user),
                "pode_lancar": pode_lancar_no_ciclo(user),
                "pode_aprovar": c.status == Status.RASCUNHO
                and pode_aprovar_o_compromisso(user),
                "pode_editar": _pode_editar(user, c),
                "pode_excluir": _pode_excluir(user, c),
                "pode_restaurar": c.status == Status.EXCLUIDA
                and pode_excluir_confirmado(user),
                "pode_programar": aprovado
                and acerto is None
                and pode_lancar_no_ciclo(user),
                "pode_abrir_acerto": aprovado
                and acerto is None
                and pode_lancar_no_ciclo(user),
                "acerto_aprovado": acerto is not None
                and acerto.status == Status.CONFIRMADA,
                "bases": PriceBasis,
                "contratos": [
                    d
                    for d in contract.contratos_do_compromisso(c)
                    if pode_ver_documento(user, d)
                ],
                "pode_gerar_contrato": aprovado,
            }
        )
        return context


class ContratoGerarView(VeOCicloMixin, View):
    """POST: gerar um documento é gravar. O PDF só é servido pela view
    autenticada de `documents`."""

    http_method_names = ["post"]

    def post(self, request, pk):
        c = _compromisso(request, pk)
        try:
            documento = contract.gerar_contrato(c, usuario=request.user)
        except ERROS_DE_NEGOCIO as exc:
            messages.error(request, str(exc))
            return redirect("procurement:compromisso_detalhe", pk=c.pk)
        return redirect("documents:detalhe", document_id=documento.document_id)


class CompromissoAprovarView(AprovaOCompromissoMixin, View):
    template_name = "procurement/compromisso_aprovar.html"

    def _efeitos(self, c):
        regra = escolher_regra(
            comissionado=c.commissioned,
            categoria=commitments._categoria_unica(c),
            data=c.date,
        )
        efeitos = [
            "o compromisso fica aprovado e libera viagem, recebimento e acerto",
        ]
        if regra is not None:
            efeitos.append(
                f"a regra de comissão vigente ({regra}) é gravada neste compromisso: "
                "mudar o cadastro depois não o altera"
            )
        else:
            efeitos.append(
                "nenhuma regra de comissão vale hoje: a comissão ficará em branco "
                "e pode ser informada neste compromisso"
            )
        return efeitos

    def get(self, request, pk):
        c = _compromisso(request, pk)
        return render(
            request, self.template_name, {"compromisso": c, "efeitos": self._efeitos(c)}
        )

    def post(self, request, pk):
        c = _compromisso(request, pk)
        try:
            commitments.aprovar_compromisso(c, usuario=request.user)
        except ERROS_DE_NEGOCIO as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"✓ Compromisso {c.code} aprovado. Próximo passo: programar a viagem.",
            )
        return redirect("procurement:compromisso_detalhe", pk=c.pk)


class ComissaoDefinirView(LancaNoCicloMixin, View):
    """Comissão de **um** comprador: corrige a existente (`?comprador=<id>`) ou
    informa a de um comprador novo."""

    template_name = "procurement/comissao_form.html"

    def _contexto(self, form, c):
        return {
            "form": form,
            "titulo": f"Comissão de {c.code}",
            "ajuda": "comissao",
            "subtitulo": (
                "Vale só para este compromisso. Corrigir a que já existe exige "
                "motivo; escolher outro comprador o acrescenta."
            ),
            "voltar": reverse("procurement:compromisso_detalhe", args=[c.pk]),
            "voltar_rotulo": c.code,
        }

    def _atual(self, request, c):
        quem = request.GET.get("comprador")
        comissoes = commitments.comissoes_do(c)
        if quem and quem.isdigit():
            return next((x for x in comissoes if x.payee_id == int(quem)), None)
        return commitments.comissao_do(c) if not quem else None

    def get(self, request, pk):
        c = _compromisso(request, pk)
        atual = self._atual(request, c)
        initial = (
            {
                "payee": atual.payee_id,
                "type": atual.type,
                "value": atual.value,
                "extra_amount": atual.extra_amount,
                "due_date": atual.due_date,
            }
            if atual
            else {"payee": None, "type": "PERCENTUAL"}
        )
        return render(
            request,
            self.template_name,
            self._contexto(CommissionForm(initial=initial), c),
        )

    def post(self, request, pk):
        c = _compromisso(request, pk)
        form = CommissionForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._contexto(form, c))
        d = form.cleaned_data
        try:
            commitments.definir_comissao(
                c,
                tipo=d["type"],
                valor=d["value"],
                extra=d["extra_amount"] or 0,
                favorecido=d["payee"],
                vencimento=d["due_date"],
                usuario=request.user,
                motivo=d["reason"],
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, self._contexto(form, c))
        messages.success(request, f"✓ Comissão de {d['payee']} atualizada.")
        return redirect("procurement:compromisso_detalhe", pk=c.pk)


class CompradorRetirarView(LancaNoCicloMixin, View):
    """Tira um comprador (e a comissão dele) do compromisso aprovado."""

    template_name = "procurement/comissao_form.html"

    def _contexto(self, form, c, comissao):
        return {
            "form": form,
            "titulo": f"Retirar {comissao.payee or 'comprador'} de {c.code}",
            "subtitulo": "A comissão dele sai do compromisso. Fica na auditoria.",
            "voltar": reverse("procurement:compromisso_detalhe", args=[c.pk]),
            "voltar_rotulo": c.code,
            "salvar": "Retirar comprador",
        }

    def _comissao(self, c, comissao_id):
        return get_object_or_404(Commission, pk=comissao_id, commitment=c)

    def get(self, request, pk, comissao_id):
        c = _compromisso(request, pk)
        comissao = self._comissao(c, comissao_id)
        return render(
            request,
            self.template_name,
            self._contexto(ReabrirOperacaoForm(), c, comissao),
        )

    def post(self, request, pk, comissao_id):
        c = _compromisso(request, pk)
        comissao = self._comissao(c, comissao_id)
        form = ReabrirOperacaoForm(request.POST)
        if not form.is_valid():
            return render(
                request, self.template_name, self._contexto(form, c, comissao)
            )
        try:
            commitments.retirar_comprador(
                c, comissao, usuario=request.user, motivo=form.cleaned_data["reason"]
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(
                request, self.template_name, self._contexto(form, c, comissao)
            )
        messages.success(request, "✓ Comprador retirado do compromisso.")
        return redirect("procurement:compromisso_detalhe", pk=c.pk)


class OperacaoEncerrarView(LancaNoCicloMixin, View):
    """Encerramento **manual** da operação (cliente, 2026-10-03)."""

    template_name = "procurement/comissao_form.html"

    def _contexto(self, form, c):
        return {
            "form": form,
            "titulo": f"Encerrar a operação {c.code}",
            "subtitulo": (
                "O sistema não encerra sozinho: quem decide é você. Depois de "
                "encerrada, a operação não recebe mais lançamentos — dá para "
                "reabri-la, com motivo."
            ),
            "voltar": reverse("procurement:compromisso_detalhe", args=[c.pk]),
            "voltar_rotulo": c.code,
            "salvar": "Encerrar operação",
        }

    def get(self, request, pk):
        c = _compromisso(request, pk)
        return render(
            request, self.template_name, self._contexto(EncerrarOperacaoForm(), c)
        )

    def post(self, request, pk):
        c = _compromisso(request, pk)
        form = EncerrarOperacaoForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._contexto(form, c))
        try:
            commitments.encerrar_operacao(
                c, usuario=request.user, observacao=form.cleaned_data["note"]
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, self._contexto(form, c))
        messages.success(request, f"✓ Operação {c.code} encerrada.")
        return redirect("procurement:compromisso_detalhe", pk=c.pk)


class OperacaoReabrirView(LancaNoCicloMixin, View):
    template_name = "procurement/comissao_form.html"

    def _contexto(self, form, c):
        return {
            "form": form,
            "titulo": f"Reabrir a operação {c.code}",
            "subtitulo": "Volta a receber lançamentos. O motivo fica na auditoria.",
            "voltar": reverse("procurement:compromisso_detalhe", args=[c.pk]),
            "voltar_rotulo": c.code,
            "salvar": "Reabrir operação",
        }

    def get(self, request, pk):
        c = _compromisso(request, pk)
        return render(
            request, self.template_name, self._contexto(ReabrirOperacaoForm(), c)
        )

    def post(self, request, pk):
        c = _compromisso(request, pk)
        form = ReabrirOperacaoForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._contexto(form, c))
        try:
            commitments.reabrir_operacao(
                c, usuario=request.user, motivo=form.cleaned_data["reason"]
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, self._contexto(form, c))
        messages.success(request, f"✓ Operação {c.code} reaberta.")
        return redirect("procurement:compromisso_detalhe", pk=c.pk)


# --------------------------------------------------------------------------
# Viagem
# --------------------------------------------------------------------------


def _formset_de_cargas(compromisso, *, initial=None, data=None):
    return LoadFormSet(
        data,
        initial=initial,
        prefix="cargas",
        form_kwargs={"itens": compromisso.items.select_related("category")},
    )


class ViagemNovaView(LancaNoCicloMixin, View):
    template_name = "procurement/viagem_form.html"

    def get(self, request, pk):
        c = _compromisso(request, pk)
        form = TripForm(
            initial={
                "pickup_date": c.pickup_date or datetime.date.today(),
                "distance_km": c.distance_km,
            }
        )
        itens = list(c.items.order_by("number"))
        initial = [{"item": i.pk, "planned_qty": i.head_count} for i in itens][:1] or [
            {}
        ]
        formset = _formset_de_cargas(c, initial=initial)
        return render(
            request,
            self.template_name,
            {"form": form, "formset": formset, "compromisso": c},
        )

    def post(self, request, pk):
        c = _compromisso(request, pk)
        form = TripForm(request.POST)
        formset = _formset_de_cargas(c, data=request.POST)
        contexto = {"form": form, "formset": formset, "compromisso": c}
        if not (form.is_valid() & formset.is_valid()):
            return render(request, self.template_name, contexto)
        try:
            viagem = trips.criar_viagem(
                usuario=request.user,
                compromisso=c,
                cargas=entradas_do_formset(formset),
                **form.dados_limpos(),
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(
            request,
            f"✓ Viagem {viagem.code} lançada. Quando o gado chegar, registre o recebimento.",
        )
        return redirect("procurement:viagem_detalhe", pk=viagem.pk)


class ViagemDetalheView(VeOCicloMixin, TemplateView):
    template_name = "procurement/viagem_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        v = _viagem(self.request, kwargs["pk"])
        recebimento = v.receivings.exclude(status=Status.EXCLUIDA).first()
        context.update(
            {
                "viagem": v,
                "compromisso": v.commitment,
                "cargas": v.loads.select_related("item__category"),
                "frete": trips.frete_da_viagem(v),
                "avisos": trips.avisos_da_viagem(v),
                "recebimento": recebimento,
                "pode_receber": v.status == Status.CONFIRMADA
                and recebimento is None
                and pode_lancar_no_ciclo(user),
                "pode_editar": _pode_editar(user, v),
                "pode_excluir": _pode_excluir(user, v),
                "pode_restaurar": v.status == Status.EXCLUIDA
                and pode_excluir_confirmado(user),
            }
        )
        return context


class ViagemEditarView(LancaNoCicloMixin, View):
    template_name = "procurement/viagem_form.html"

    def _initial(self, v):
        return {
            "pickup_date": v.pickup_date,
            "carrier": v.carrier_id,
            "driver_name": v.driver_name,
            "vehicle": v.vehicle,
            "vehicle_plate": v.vehicle_plate,
            "adf_number": v.adf_number,
            "freight_due_date": v.freight_due_date,
            "distance_km": v.distance_km,
            "freight_criterion": v.freight_criterion,
            "freight_rate": v.freight_rate,
            "freight_actual": v.freight_actual,
            "notes": v.notes,
        }

    def get(self, request, pk):
        v = _viagem(request, pk)
        if not _pode_editar(request.user, v):
            messages.error(request, "Esta viagem não pode ser editada por você agora.")
            return redirect("procurement:viagem_detalhe", pk=v.pk)
        form = TripEditForm(initial=self._initial(v))
        formset = _formset_de_cargas(v.commitment, initial=cargas_iniciais(v))
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "compromisso": v.commitment,
                "viagem": v,
            },
        )

    def post(self, request, pk):
        v = _viagem(request, pk)
        form = TripEditForm(request.POST)
        formset = _formset_de_cargas(v.commitment, data=request.POST)
        contexto = {
            "form": form,
            "formset": formset,
            "compromisso": v.commitment,
            "viagem": v,
        }
        if not (form.is_valid() & formset.is_valid()):
            return render(request, self.template_name, contexto)
        motivo = form.cleaned_data.get("edit_reason", "")
        if not motivo.strip():
            form.add_error("edit_reason", "Informe o motivo da correção.")
            return render(request, self.template_name, contexto)
        try:
            trips.editar_viagem(
                v,
                form.dados_limpos(),
                entradas_do_formset(formset),
                usuario=request.user,
                motivo=motivo,
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(request, f"✓ Viagem {v.code} corrigida.")
        return redirect("procurement:viagem_detalhe", pk=v.pk)


# --------------------------------------------------------------------------
# Recebimento
# --------------------------------------------------------------------------


def _formset_de_recebimento(viagem, *, initial=None, data=None):
    return ReceivingLineFormSet(
        data,
        initial=initial,
        prefix="linhas",
        form_kwargs={"cargas": viagem.loads.select_related("item__category")},
    )


class RecebimentoNovoView(LancaNoCicloMixin, View):
    template_name = "procurement/recebimento_form.html"

    def get(self, request, pk):
        v = _viagem(request, pk)
        form = ReceivingForm(initial={"date": datetime.date.today()})
        initial = [
            {"load": c.pk, "received_qty": c.shipped_qty}
            for c in v.loads.order_by("item__number")
        ]
        formset = _formset_de_recebimento(v, initial=initial)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "viagem": v,
                "compromisso": v.commitment,
            },
        )

    def post(self, request, pk):
        v = _viagem(request, pk)
        form = ReceivingForm(request.POST)
        formset = _formset_de_recebimento(v, data=request.POST)
        contexto = {
            "form": form,
            "formset": formset,
            "viagem": v,
            "compromisso": v.commitment,
        }
        if not (form.is_valid() & formset.is_valid()):
            return render(request, self.template_name, contexto)
        try:
            recebimento = receivings.criar_recebimento(
                usuario=request.user,
                viagem=v,
                date=form.cleaned_data["date"],
                notes=form.cleaned_data["notes"],
                trip_loss_percent=form.cleaned_data["trip_loss_percent"],
                linhas=entradas_do_formset(formset),
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        cabecas = receivings.cabecas_recebidas(recebimento)
        messages.success(
            request,
            f"✓ Recebimento {recebimento.code} registrado: {cabecas} cabeças. "
            "Próximo passo: lançar o romaneio e abrir o acerto.",
        )
        return redirect("procurement:recebimento_detalhe", pk=recebimento.pk)


class RecebimentoDetalheView(VeOCicloMixin, TemplateView):
    template_name = "procurement/recebimento_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        r = _recebimento(self.request, kwargs["pk"])
        linhas = [
            {"linha": ln, "diferenca": receivings.diferenca_de_cabecas(ln)}
            for ln in r.lines.select_related(
                "load__item__category", "received_category"
            )
        ]
        context.update(
            {
                "recebimento": r,
                "viagem": r.trip,
                "compromisso": r.trip.commitment,
                "linhas": linhas,
                "cabecas": receivings.cabecas_recebidas(r),
                "quebra": receivings.quebra_da_viagem(r),
                "pode_editar": _pode_editar(user, r),
                "pode_excluir": _pode_excluir(user, r),
                "pode_restaurar": r.status == Status.EXCLUIDA
                and pode_excluir_confirmado(user),
            }
        )
        return context


class RecebimentoEditarView(LancaNoCicloMixin, View):
    template_name = "procurement/recebimento_form.html"

    def get(self, request, pk):
        r = _recebimento(request, pk)
        if not _pode_editar(request.user, r):
            messages.error(
                request, "Este recebimento não pode ser editado por você agora."
            )
            return redirect("procurement:recebimento_detalhe", pk=r.pk)
        form = ReceivingForm(
            initial={
                "date": r.date,
                "notes": r.notes,
                "trip_loss_percent": r.trip_loss_percent,
            }
        )
        formset = _formset_de_recebimento(
            r.trip, initial=linhas_de_recebimento_iniciais(r)
        )
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "viagem": r.trip,
                "compromisso": r.trip.commitment,
                "recebimento": r,
            },
        )

    def post(self, request, pk):
        r = _recebimento(request, pk)
        form = ReceivingForm(request.POST)
        formset = _formset_de_recebimento(r.trip, data=request.POST)
        contexto = {
            "form": form,
            "formset": formset,
            "viagem": r.trip,
            "compromisso": r.trip.commitment,
            "recebimento": r,
        }
        if not (form.is_valid() & formset.is_valid()):
            return render(request, self.template_name, contexto)
        motivo = form.cleaned_data.get("edit_reason", "")
        if not motivo.strip():
            form.add_error("edit_reason", "Informe o motivo da correção.")
            return render(request, self.template_name, contexto)
        try:
            receivings.editar_recebimento(
                r,
                {
                    "date": form.cleaned_data["date"],
                    "notes": form.cleaned_data["notes"],
                    "trip_loss_percent": form.cleaned_data["trip_loss_percent"],
                },
                entradas_do_formset(formset),
                usuario=request.user,
                motivo=motivo,
            )
        except ERROS_DE_NEGOCIO as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(request, f"✓ Recebimento {r.code} corrigido.")
        return redirect("procurement:recebimento_detalhe", pk=r.pk)


# --------------------------------------------------------------------------
# Romaneio
# --------------------------------------------------------------------------


class RomaneioView(LancaNoCicloMixin, View):
    template_name = "procurement/romaneio_form.html"

    def _formset(self, item, *, initial=None, data=None):
        return GradingLineFormSet(
            data,
            initial=initial,
            prefix="linhas",
            form_kwargs={"classes": comercial.classes_ativas()},
        )

    def _contexto(self, item, formset, reason_form, **extra):
        return {
            "item": item,
            "compromisso": item.commitment,
            "formset": formset,
            "reason_form": reason_form,
            "romaneio": grading.romaneio_do_item(item),
            "titulo": "Romaneio valorizado",
            "ajuda": "romaneio",
            "subtitulo": (
                "Classificação, faixa, cabeças e peso de carcaça. Média @, valor "
                "bruto e líquido são calculados."
            ),
            "rotulo": "Linha do romaneio",
            "voltar": reverse(
                "procurement:compromisso_detalhe", args=[item.commitment_id]
            ),
            "voltar_rotulo": item.commitment.code,
            **extra,
        }

    def get(self, request, pk):
        item = _item(request, pk)
        if item.price_basis != PriceBasis.ARROBA:
            messages.error(
                request,
                f"O item {item.number} é precificado por cabeça: não tem romaneio por faixa.",
            )
            return redirect("procurement:compromisso_detalhe", pk=item.commitment_id)
        existentes = linhas_de_romaneio_iniciais(item)
        formset = self._formset(item, initial=existentes or [{}])
        return render(
            request, self.template_name, self._contexto(item, formset, ReasonForm())
        )

    def post(self, request, pk):
        item = _item(request, pk)
        formset = self._formset(item, data=request.POST)
        reason_form = ReasonForm(request.POST)
        contexto = self._contexto(item, formset, reason_form)
        if not (formset.is_valid() & reason_form.is_valid()):
            return render(request, self.template_name, contexto)
        try:
            grading.registrar_romaneio(
                item,
                entradas_do_formset(formset),
                usuario=request.user,
                motivo=reason_form.cleaned_data["reason"],
            )
        except ERROS_DE_NEGOCIO as exc:
            reason_form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(
            request,
            f"✓ Romaneio do item {item.number} salvo. Próximo passo: abrir o acerto.",
        )
        return redirect("procurement:compromisso_detalhe", pk=item.commitment_id)


# --------------------------------------------------------------------------
# Acerto
# --------------------------------------------------------------------------


class AcertoListView(VeOCicloMixin, TemplateView):
    template_name = "procurement/acerto_list.html"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        season = ctx.current_season(self.request, ctx.current_company())
        farm = ctx.current_farm(self.request, user)
        qs = Settlement.objects.for_user(user).select_related(
            "commitment__seller", "commitment__destination_farm"
        )
        if season is not None:
            qs = qs.filter(commitment__season=season)
        if farm is not None:
            qs = qs.filter(commitment__destination_farm=farm)
        situacao = self.request.GET.get("situacao", "")
        if situacao:
            qs = qs.filter(status=situacao)
        pagina = Paginator(qs, self.paginate_by).get_page(self.request.GET.get("page"))
        context.update(
            {"page_obj": pagina, "acertos": pagina.object_list, "situacao": situacao}
        )
        return context


class AcertoNovoView(LancaNoCicloMixin, View):
    """Abrir o acerto não pede formulário: a data é hoje e dá para mudar depois."""

    def post(self, request, pk):
        c = _compromisso(request, pk)
        try:
            acerto = closing.criar_acerto(
                usuario=request.user, compromisso=c, date=datetime.date.today()
            )
        except ERROS_DE_NEGOCIO as exc:
            messages.error(request, str(exc))
            return redirect("procurement:compromisso_detalhe", pk=c.pk)
        messages.success(
            request,
            f"✓ Acerto {acerto.code} aberto. Lance tributos e taxas, confira o "
            "previsto × realizado e aprove.",
        )
        return redirect("procurement:acerto_detalhe", pk=acerto.pk)


class AcertoDetalheView(VeOCicloMixin, TemplateView):
    template_name = "procurement/acerto_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        a = _acerto(self.request, kwargs["pk"])
        calculo = calcular_acerto(a.commitment)
        compras = [
            i.purchase
            for i in a.commitment.items.select_related("purchase__lot")
            if i.purchase_id and i.purchase.status == Status.CONFIRMADA
        ]
        em_andamento = a.status == Status.RASCUNHO
        context.update(
            {
                "acerto": a,
                "compromisso": a.commitment,
                "calculo": calculo,
                "linhas": a.lines.select_related("tax_type"),
                "notas": a.fiscal_notes.all(),
                "compras": compras,
                "titulos": a.invoices.filter(status=Status.CONFIRMADA)
                .select_related("payee")
                .order_by("due_date", "id"),
                "pode_editar": em_andamento and pode_lancar_no_ciclo(user),
                "pode_aprovar": em_andamento and pode_aprovar_o_acerto(user),
                "pode_reabrir": a.status == Status.CONFIRMADA
                and pode_aprovar_o_acerto(user),
                "pode_excluir": _pode_excluir(user, a),
                "pode_restaurar": a.status == Status.EXCLUIDA
                and pode_excluir_confirmado(user),
                "pode_lancar": pode_lancar_no_ciclo(user)
                and a.status != Status.EXCLUIDA,
            }
        )
        return context


class AcertoAprovarView(View):
    """GET mostra o que aprovar vai fazer; POST aprova."""

    template_name = "procurement/acerto_aprovar.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        if not pode_aprovar_o_acerto(request.user):
            messages.error(
                request, "A aprovação do acerto é de administrador ou gestor."
            )
            return redirect("procurement:acerto_detalhe", pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        a = _acerto(request, pk)
        calculo = calcular_acerto(a.commitment)
        return render(
            request,
            self.template_name,
            {"acerto": a, "compromisso": a.commitment, "calculo": calculo},
        )

    def post(self, request, pk):
        a = _acerto(request, pk)
        try:
            closing.aprovar_acerto(a, usuario=request.user)
        except ERROS_DE_NEGOCIO as exc:
            messages.error(request, str(exc))
            return redirect("procurement:acerto_aprovar", pk=a.pk)
        compras = [
            i.purchase
            for i in a.commitment.items.select_related("purchase__lot")
            if i.purchase_id and i.purchase.status == Status.CONFIRMADA
        ]
        cabecas = sum(c.head_count for c in compras)
        lotes = ", ".join(sorted({c.lot.code for c in compras}))
        messages.success(
            request,
            f"✓ Acerto {a.code} aprovado. {cabecas} cabeças deram entrada no "
            f"rebanho (lote {lotes}) e os títulos foram gerados.",
        )
        return redirect("procurement:acerto_detalhe", pk=a.pk)


class _LinhasDoAcertoView(LancaNoCicloMixin, View):
    """Base das telas de tabela do acerto (tributos e notas fiscais)."""

    template_name = "procurement/linhas_form.html"
    titulo = ""
    subtitulo = ""
    rotulo = "Linha"
    ancora = ""

    def formset(self, a, *, initial=None, data=None):
        raise NotImplementedError

    def iniciais(self, a):
        raise NotImplementedError

    def salvar(self, a, entradas, *, usuario, motivo):
        raise NotImplementedError

    def contexto(self, a, formset, reason_form):
        return {
            "acerto": a,
            "formset": formset,
            "reason_form": reason_form,
            "titulo": self.titulo,
            "ajuda": "acerto",
            "subtitulo": self.subtitulo,
            "rotulo": self.rotulo,
            "voltar": reverse("procurement:acerto_detalhe", args=[a.pk]) + self.ancora,
            "voltar_rotulo": a.code,
        }

    def get(self, request, pk):
        a = _acerto(request, pk)
        formset = self.formset(a, initial=self.iniciais(a))
        return render(
            request, self.template_name, self.contexto(a, formset, ReasonForm())
        )

    def post(self, request, pk):
        a = _acerto(request, pk)
        formset = self.formset(a, data=request.POST)
        reason_form = ReasonForm(request.POST)
        contexto = self.contexto(a, formset, reason_form)
        if not (formset.is_valid() & reason_form.is_valid()):
            return render(request, self.template_name, contexto)
        try:
            self.salvar(
                a,
                entradas_do_formset(formset),
                usuario=request.user,
                motivo=reason_form.cleaned_data["reason"],
            )
        except ERROS_DE_NEGOCIO as exc:
            reason_form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(request, f"✓ {self.titulo} salvo.")
        return redirect(contexto["voltar"])


class AcertoLinhasView(_LinhasDoAcertoView):
    titulo = "Tributos, taxas e descontos"
    subtitulo = (
        "Valores digitados. Tributo e taxa somam ao custo; desconto reduz os animais; "
        "adiantamento e crédito reduzem só o que se paga ao vendedor."
    )
    rotulo = "Linha"

    def formset(self, a, *, initial=None, data=None):
        return SettlementLineFormSet(
            data,
            initial=initial,
            prefix="linhas",
            form_kwargs={"tipos": comercial.tipos_ativos()},
        )

    def iniciais(self, a):
        return linhas_do_acerto_iniciais(a) or [{}]

    def salvar(self, a, entradas, *, usuario, motivo):
        closing.registrar_linhas(a, entradas, usuario=usuario, motivo=motivo)


class AcertoDistribuicaoView(LancaNoCicloMixin, View):
    """O que cada item recebe do frete, da comissão, dos tributos, dos descontos
    e dos adiantamentos. **O sistema não rateia sozinho**: a tela vem
    pré-preenchida com uma sugestão (por cabeça e por valor), e só vale depois
    que o usuário confere e salva."""

    template_name = "procurement/acerto_distribuicao.html"

    def _recebidos(self, a):
        calculo = calcular_acerto(a.commitment)
        return calculo, [i for i in calculo.itens if i.recebido]

    def _iniciais(self, a, calculo, recebidos):
        salvas = {x.item_id: x for x in a.allocations.all()}
        if salvas:
            return [
                {
                    "item": i.item.pk,
                    **{
                        campo: (
                            getattr(salvas[i.item.pk], campo)
                            if i.item.pk in salvas
                            else 0
                        )
                        for campo, _ in settlement.TOTAIS_A_DISTRIBUIR
                    },
                }
                for i in recebidos
            ], False
        sugestao = settlement.sugerir_distribuicao(
            recebidos,
            frete=calculo.frete,
            comissao=calculo.comissao_total,
            tributos=calculo.tributos,
            descontos=calculo.descontos,
            abatimentos=calculo.adiantamentos + calculo.creditos,
        )
        return [{"item": i.item.pk, **sugestao[i.item.pk]} for i in recebidos], True

    def _contexto(self, a, calculo, recebidos, formset, reason_form, sugerido):
        totais = [
            ("Descontos", calculo.descontos),
            ("Adiantamentos e créditos", calculo.adiantamentos + calculo.creditos),
            ("Frete", calculo.frete),
            ("Comissão", calculo.comissao_total),
            ("Tributos e taxas", calculo.tributos),
        ]
        itens = {i.item.pk: i.item for i in recebidos}
        return {
            "acerto": a,
            "compromisso": a.commitment,
            "formset": formset,
            "calculo": calculo,
            "linhas": [(f, itens.get(int(f["item"].value()))) for f in formset],
            "reason_form": reason_form,
            "totais": totais,
            "sugerido": sugerido,
            "voltar": reverse("procurement:acerto_detalhe", args=[a.pk]),
            "voltar_rotulo": a.code,
        }

    def get(self, request, pk):
        a = _acerto(request, pk)
        calculo, recebidos = self._recebidos(a)
        iniciais, sugerido = self._iniciais(a, calculo, recebidos)
        formset = AllocationFormSet(initial=iniciais, prefix="distribuicao")
        return render(
            request,
            self.template_name,
            self._contexto(a, calculo, recebidos, formset, ReasonForm(), sugerido),
        )

    def post(self, request, pk):
        a = _acerto(request, pk)
        calculo, recebidos = self._recebidos(a)
        formset = AllocationFormSet(request.POST, prefix="distribuicao")
        reason_form = ReasonForm(request.POST)
        contexto = self._contexto(a, calculo, recebidos, formset, reason_form, False)
        if not (formset.is_valid() & reason_form.is_valid()):
            return render(request, self.template_name, contexto)
        try:
            closing.registrar_distribuicao(
                a,
                [f.cleaned_data for f in formset.forms],
                usuario=request.user,
                motivo=reason_form.cleaned_data["reason"],
            )
        except ERROS_DE_NEGOCIO as exc:
            reason_form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(request, "✓ Distribuição entre os itens salva.")
        return redirect("procurement:acerto_detalhe", pk=a.pk)


class AcertoNotasView(_LinhasDoAcertoView):
    titulo = "Notas fiscais"
    subtitulo = (
        "Só o registro do número: o sistema não emite nota. Com nota registrada, "
        "reabrir o acerto fica bloqueado até a nota ser retirada."
    )
    rotulo = "Nota"
    ancora = "#notas-fiscais"

    def formset(self, a, *, initial=None, data=None):
        return FiscalNoteFormSet(data, initial=initial, prefix="notas")

    def iniciais(self, a):
        return notas_iniciais(a) or [{}]

    def salvar(self, a, entradas, *, usuario, motivo):
        closing.registrar_notas(a, entradas, usuario=usuario, motivo=motivo)
