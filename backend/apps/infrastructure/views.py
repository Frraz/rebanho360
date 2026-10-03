"""Fino: HTTP. Fora do escopo de fazenda, 404 — nunca 403 (ADR 0003)."""

import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.permissions import pode_editar_confirmado
from apps.core.reversible import Status
from apps.core.views import ExclusaoComImpactoView
from apps.infrastructure import indicators, services
from apps.infrastructure.forms import (
    FarmStructureForm,
    MachineForm,
    MachineLogEditForm,
    MachineLogForm,
)
from apps.infrastructure.models import FarmStructure, Machine, MachineLog
from apps.infrastructure.permissions import (
    CadastraMixin,
    LancaUsoMixin,
    pode_cadastrar,
    pode_lancar_uso,
)

ERROS = (BusinessError, BlockingDependencyError)


class _CadastroMixin:
    """Salva pelo serviço (auditoria) e leva o rótulo da tela para o template."""

    template_name = "infrastructure/cadastro_form.html"
    subtitulo = ""
    voltar_rotulo = ""
    ajuda = ""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "titulo": (
                    str(self.object)
                    if getattr(self, "object", None) and self.object.pk
                    else self.titulo_novo
                ),
                "subtitulo": self.subtitulo,
                "voltar": str(self.success_url),
                "voltar_rotulo": self.voltar_rotulo,
                "ajuda": self.ajuda,
            }
        )
        return context

    def form_valid(self, form):
        criando = form.instance.pk is None
        self.object = form.save(commit=False)
        try:
            services.salvar_cadastro(
                self.object, usuario=self.request.user, criando=criando
            )
        except ERROS as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())

    def get_queryset(self):
        return self.model.objects.for_user(self.request.user)


class _ListaMixin(LoginRequiredMixin):
    def get_queryset(self):
        return self.model.objects.for_user(self.request.user).select_related("farm")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pode_gerenciar"] = pode_cadastrar(self.request.user)
        return context


# --- Estruturas da fazenda ---------------------------------------------------


class EstruturaListView(_ListaMixin, ListView):
    model = FarmStructure
    template_name = "infrastructure/estrutura_list.html"
    context_object_name = "estruturas"


class EstruturaNovaView(CadastraMixin, _CadastroMixin, CreateView):
    model = FarmStructure
    form_class = FarmStructureForm
    success_url = reverse_lazy("infrastructure:estrutura_lista")
    success_message = "✓ Estrutura cadastrada."
    titulo_novo = "Nova estrutura"
    subtitulo = "Curral, cocho, bebedouro… As razões (m² por animal, cm de cocho) são calculadas."
    voltar_rotulo = "Infraestrutura"
    ajuda = "estrutura"


class EstruturaEditarView(CadastraMixin, _CadastroMixin, UpdateView):
    model = FarmStructure
    form_class = FarmStructureForm
    success_url = reverse_lazy("infrastructure:estrutura_lista")
    success_message = "✓ Estrutura atualizada."
    voltar_rotulo = "Infraestrutura"
    ajuda = "estrutura"


# --- Máquinas ---------------------------------------------------------------


class MaquinaListView(_ListaMixin, ListView):
    model = Machine
    template_name = "infrastructure/maquina_list.html"
    context_object_name = "maquinas"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["linhas"] = [
            {"maquina": m, "custo": indicators.custo_hora_da_maquina(m)}
            for m in context["maquinas"]
        ]
        return context


class MaquinaNovaView(CadastraMixin, _CadastroMixin, CreateView):
    model = Machine
    form_class = MachineForm
    success_url = reverse_lazy("infrastructure:maquina_lista")
    success_message = "✓ Máquina cadastrada."
    titulo_novo = "Nova máquina"
    subtitulo = "O custo por hora sai do uso lançado: horas, combustível e manutenção."
    voltar_rotulo = "Máquinas"
    ajuda = "maquina"


class MaquinaEditarView(CadastraMixin, _CadastroMixin, UpdateView):
    model = Machine
    form_class = MachineForm
    success_url = reverse_lazy("infrastructure:maquina_lista")
    success_message = "✓ Máquina atualizada."
    voltar_rotulo = "Máquinas"
    ajuda = "maquina"


def _maquina(request, pk) -> Machine:
    return get_object_or_404(
        Machine.objects.for_user(request.user).select_related("farm"), pk=pk
    )


def _uso(request, pk) -> MachineLog:
    return get_object_or_404(
        MachineLog.objects.for_user(request.user).select_related("machine__farm"), pk=pk
    )


class MaquinaDetalheView(LoginRequiredMixin, TemplateView):
    template_name = "infrastructure/maquina_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        m = _maquina(self.request, kwargs["pk"])
        context.update(
            {
                "maquina": m,
                "custo": indicators.custo_hora_da_maquina(m),
                "usos": m.logs.exclude(status=Status.EXCLUIDA),
                "pode_lancar": m.is_active and pode_lancar_uso(user),
                "pode_gerenciar": pode_cadastrar(user),
            }
        )
        return context


class UsoNovoView(LancaUsoMixin, View):
    template_name = "infrastructure/uso_form.html"

    def get(self, request, pk):
        m = _maquina(request, pk)
        form = MachineLogForm(initial={"date": datetime.date.today()})
        return render(request, self.template_name, {"form": form, "maquina": m})

    def post(self, request, pk):
        m = _maquina(request, pk)
        form = MachineLogForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "maquina": m})
        try:
            uso = services.registrar_uso(
                usuario=request.user, machine=m, **form.cleaned_data
            )
        except ERROS as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form, "maquina": m})
        messages.success(request, f"✓ Uso {uso.code} lançado: {uso.hours} h.")
        return redirect("infrastructure:maquina_detalhe", pk=m.pk)


class UsoEditarView(LoginRequiredMixin, View):
    template_name = "infrastructure/uso_form.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not pode_editar_confirmado(request.user):
            messages.error(
                request, "Você não tem permissão para editar este lançamento."
            )
            return redirect("infrastructure:maquina_lista")
        return super().dispatch(request, *args, **kwargs)

    def _inicial(self, u):
        return {c: getattr(u, c) for c in services.CAMPOS_DO_USO}

    def get(self, request, pk):
        u = _uso(request, pk)
        form = MachineLogEditForm(initial=self._inicial(u))
        return render(
            request, self.template_name, {"form": form, "maquina": u.machine, "uso": u}
        )

    def post(self, request, pk):
        u = _uso(request, pk)
        form = MachineLogEditForm(request.POST)
        contexto = {"form": form, "maquina": u.machine, "uso": u}
        if not form.is_valid():
            return render(request, self.template_name, contexto)
        dados = {k: v for k, v in form.cleaned_data.items() if k != "edit_reason"}
        try:
            services.editar_uso(
                u, dados, usuario=request.user, motivo=form.cleaned_data["edit_reason"]
            )
        except ERROS as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, contexto)
        messages.success(request, f"✓ Uso {u.code} corrigido.")
        return redirect("infrastructure:maquina_detalhe", pk=u.machine_id)


class UsoExcluirView(ExclusaoComImpactoView):
    model = MachineLog
    titulo = "Excluir uso da máquina"

    def url_do_registro(self, registro):
        return reverse("infrastructure:maquina_detalhe", args=[registro.machine_id])

    def executar_exclusao(self, registro, *, motivo, cascata):
        services.excluir_uso(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )


class UsoRestaurarView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        u = _uso(request, pk)
        try:
            services.restaurar_uso(u, usuario=request.user)
        except ERROS as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Uso {u.code} restaurado.")
        return redirect("infrastructure:maquina_detalhe", pk=u.machine_id)
