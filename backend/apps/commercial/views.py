"""Fino. Recebe request, chama service/selector, devolve template."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from apps.commercial import selectors, services
from apps.commercial.forms import (
    CarcassClassForm,
    CommissionRuleForm,
    PaymentConditionForm,
    TaxTypeForm,
)
from apps.commercial.models import (
    CarcassClass,
    CommissionRule,
    PaymentCondition,
    TaxType,
)
from apps.commercial.permissions import (
    CadastraCondicoesMixin,
    GerenciaOComercialMixin,
    pode_cadastrar_condicoes,
    pode_gerenciar_o_comercial,
)
from apps.core.exceptions import BusinessError


class _CadastroMixin:
    """Salva pelo serviço (auditoria) e leva o rótulo da tela para o template."""

    template_name = "commercial/cadastro_form.html"
    titulo_novo = ""
    titulo_edicao = ""
    subtitulo = ""
    voltar_rotulo = ""
    ajuda = ""

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
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class _ListaMixin(LoginRequiredMixin):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pode_gerenciar"] = pode_gerenciar_o_comercial(self.request.user)
        return context


# --- Classificações de carcaça ---------------------------------------------


class CarcassClassListView(_ListaMixin, ListView):
    template_name = "commercial/classe_list.html"
    context_object_name = "classes"

    def get_queryset(self):
        return selectors.listar_classes()


class CarcassClassCreateView(GerenciaOComercialMixin, _CadastroMixin, CreateView):
    model = CarcassClass
    form_class = CarcassClassForm
    success_url = reverse_lazy("commercial:classe_lista")
    success_message = "✓ Classificação cadastrada."
    titulo_novo = "Nova classificação de carcaça"
    subtitulo = "Magro, gordura escassa, lesão traumática… Cada frigorífico classifica de um jeito."
    voltar_rotulo = "Classificações de carcaça"
    ajuda = "classe_carcaca"


class CarcassClassUpdateView(GerenciaOComercialMixin, _CadastroMixin, UpdateView):
    model = CarcassClass
    form_class = CarcassClassForm
    success_url = reverse_lazy("commercial:classe_lista")
    success_message = "✓ Classificação atualizada."
    subtitulo = (
        "Mudar o nome não altera romaneios já lançados: eles guardam a classificação."
    )
    voltar_rotulo = "Classificações de carcaça"
    ajuda = "classe_carcaca"


# --- Tipos de tributo, taxa e desconto -------------------------------------


class TaxTypeListView(_ListaMixin, ListView):
    template_name = "commercial/tributo_list.html"
    context_object_name = "tipos"

    def get_queryset(self):
        return selectors.listar_tipos()


class TaxTypeCreateView(GerenciaOComercialMixin, _CadastroMixin, CreateView):
    model = TaxType
    form_class = TaxTypeForm
    success_url = reverse_lazy("commercial:tributo_lista")
    success_message = "✓ Tipo cadastrado."
    titulo_novo = "Novo tipo de tributo, taxa ou desconto"
    subtitulo = (
        "Sem alíquota: o valor é digitado no acerto. A natureza decide só o efeito."
    )
    voltar_rotulo = "Tributos e taxas"
    ajuda = "tributo"


class TaxTypeUpdateView(GerenciaOComercialMixin, _CadastroMixin, UpdateView):
    model = TaxType
    form_class = TaxTypeForm
    success_url = reverse_lazy("commercial:tributo_lista")
    success_message = "✓ Tipo atualizado."
    subtitulo = "Mudar a natureza muda o efeito dos acertos ainda não aprovados."
    voltar_rotulo = "Tributos e taxas"
    ajuda = "tributo"


# --- Regras de comissão -----------------------------------------------------


class CommissionRuleListView(_ListaMixin, ListView):
    template_name = "commercial/comissao_list.html"
    context_object_name = "regras"

    def get_queryset(self):
        return selectors.listar_regras_de_comissao()


class CommissionRuleCreateView(GerenciaOComercialMixin, _CadastroMixin, CreateView):
    model = CommissionRule
    form_class = CommissionRuleForm
    success_url = reverse_lazy("commercial:comissao_lista")
    success_message = "✓ Regra de comissão cadastrada."
    titulo_novo = "Nova regra de comissão"
    subtitulo = (
        "A regra vale para compromissos aprovados depois dela. "
        "Os já aprovados guardam a regra que valia."
    )
    voltar_rotulo = "Regras de comissão"
    ajuda = "comissao"


class CommissionRuleUpdateView(GerenciaOComercialMixin, _CadastroMixin, UpdateView):
    model = CommissionRule
    form_class = CommissionRuleForm
    success_url = reverse_lazy("commercial:comissao_lista")
    success_message = "✓ Regra de comissão atualizada."
    subtitulo = "Compromissos já aprovados não mudam: guardam a regra que valia."
    voltar_rotulo = "Regras de comissão"
    ajuda = "comissao"


# --- Condições de pagamento -------------------------------------------------


class PaymentConditionListView(LoginRequiredMixin, ListView):
    template_name = "commercial/condicao_list.html"
    context_object_name = "condicoes"

    def get_queryset(self):
        return selectors.listar_condicoes()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pode_gerenciar"] = pode_cadastrar_condicoes(self.request.user)
        return context


class PaymentConditionCreateView(CadastraCondicoesMixin, _CadastroMixin, CreateView):
    model = PaymentCondition
    form_class = PaymentConditionForm
    success_url = reverse_lazy("commercial:condicao_lista")
    success_message = "✓ Condição cadastrada."
    titulo_novo = "Nova condição de pagamento"
    subtitulo = "À vista, 4 dias, 30 dias, parcelado… Crie a que a operação precisar."
    voltar_rotulo = "Condições de pagamento"
    ajuda = "condicao_pagamento"


class PaymentConditionUpdateView(CadastraCondicoesMixin, _CadastroMixin, UpdateView):
    model = PaymentCondition
    form_class = PaymentConditionForm
    success_url = reverse_lazy("commercial:condicao_lista")
    success_message = "✓ Condição atualizada."
    subtitulo = (
        "Operações já lançadas guardam o prazo que valia: mudar aqui não as altera."
    )
    voltar_rotulo = "Condições de pagamento"
    ajuda = "condicao_pagamento"
