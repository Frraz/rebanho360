"""Fino. Recebe request, chama service/selector, devolve template."""

import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.audit.models import OperationEvent
from apps.core import context as ctx
from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.formatting import dinheiro_br
from apps.core.permissions import pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.views import ExclusaoComImpactoView
from apps.finance import selectors, services
from apps.finance.forms import (
    BaixaForm,
    FiltroContasForm,
    MotivoForm,
    ProgramarForm,
    TituloEditForm,
    TituloForm,
    rotulo_da_conta,
)
from apps.finance.models import (
    Component,
    Direction,
    Invoice,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from apps.finance.permissions import (
    GerenciaTitulosMixin,
    VeTitulosMixin,
    pode_aprovar_pagamento,
    pode_desfazer_baixa,
    pode_executar_pagamento,
    pode_gerenciar_titulos,
    pode_ver_dado_bancario,
    pode_ver_titulos,
)
from apps.partners.models import BankAccount

POR_PAGINA = 30


def _get_titulo(request, pk) -> Invoice:
    """Título dentro do escopo do usuário: fora dele, 404 — nunca 403, que
    confirmaria que o registro existe (ADR 0003)."""
    return get_object_or_404(
        Invoice.objects.for_user(request.user).select_related(
            "payee", "farm", "season", "bank_account", "origin_purchase", "origin_sale"
        ),
        pk=pk,
    )


def _get_pagamento(request, pk) -> Payment:
    return get_object_or_404(
        Payment.objects.for_user(request.user).select_related(
            "invoice", "invoice__payee", "invoice__farm", "invoice__season"
        ),
        pk=pk,
    )


class _SoQuemVeTitulos:
    """`ExclusaoComImpactoView` só exige login; o financeiro exige papel."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not pode_ver_titulos(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# --------------------------------------------------------------------------
# Contas a pagar e a receber (F4-06)
# --------------------------------------------------------------------------


class ContasView(VeTitulosMixin, TemplateView):
    """Lista por vencimento, com filtro por favorecido, situação e período, e
    o resumo "o que vence esta semana e quanto" no topo."""

    template_name = "finance/contas.html"
    direction = Direction.PAGAR

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        hoje = datetime.date.today()
        farm = ctx.current_farm(self.request, user)
        form = FiltroContasForm(self.request.GET or None)
        filtros = form.cleaned_data if form.is_valid() else {}
        situacao = filtros.get("situacao") or "abertos"

        # Querysets, não listas: a página pede 30 linhas ao banco e o resto vira
        # soma lá mesmo, em vez de trazer todos os títulos para somar aqui.
        titulos = selectors.listar_titulos_para(
            user,
            farm=farm,
            direction=self.direction,
            situacao=situacao,
            payee=filtros.get("payee"),
            de=filtros.get("de"),
            ate=filtros.get("ate"),
        )
        # O resumo não obedece aos filtros: é o retrato do que está em aberto.
        em_aberto = selectors.listar_titulos_para(
            user, farm=farm, direction=self.direction, situacao="abertos"
        )
        pagina = Paginator(titulos, POR_PAGINA).get_page(self.request.GET.get("page"))
        a_receber = self.direction == Direction.RECEBER
        context.update(
            {
                "filtro": form,
                "page_obj": pagina,
                "titulos": [(t, t.vencido(hoje)) for t in pagina.object_list],
                "resumo": selectors.resumo_de_vencimentos(em_aberto, hoje=hoje),
                "a_receber": a_receber,
                "situacao": situacao,
                "pode_lancar": pode_gerenciar_titulos(user),
                "total_listado": selectors.saldo_dos_titulos(titulos),
                "sem_titulo": (
                    selectors.contar_operacoes_sem_titulo(user)
                    if pode_gerenciar_titulos(user)
                    else 0
                ),
            }
        )
        return context


class ContasAReceberView(ContasView):
    direction = Direction.RECEBER


# --------------------------------------------------------------------------
# Criar e ver o título
# --------------------------------------------------------------------------


def _initial_de_origem(request) -> dict:
    """ "Novo título desta compra/venda": a origem vem por querystring e
    pré-preenche tudo que já existe — nada que o sistema sabe é redigitado."""
    from apps.purchases.models import Purchase
    from apps.sales.models import Sale

    compra = venda = None
    if request.GET.get("compra", "").isdigit():
        compra = (
            Purchase.objects.for_user(request.user)
            .filter(pk=request.GET["compra"], status=Status.CONFIRMADA)
            .first()
        )
    if request.GET.get("venda", "").isdigit():
        venda = (
            Sale.objects.for_user(request.user)
            .filter(pk=request.GET["venda"], status=Status.CONFIRMADA)
            .first()
        )
    hoje = datetime.date.today()
    if compra is not None:
        return {
            "direction": Direction.PAGAR,
            "component": Component.FRETE,
            "farm": compra.destination_farm_id,
            "payee": compra.seller_id,
            "issue_date": compra.date,
            "due_date": compra.date,
            "origin_purchase": compra.pk,
        }
    if venda is not None:
        return {
            "direction": Direction.RECEBER,
            "component": Component.OUTRO,
            "farm": venda.farm_id,
            "payee": venda.buyer_id,
            "issue_date": venda.date,
            "due_date": venda.date,
            "origin_sale": venda.pk,
        }
    return {
        "direction": request.GET.get("direcao") or Direction.PAGAR,
        "issue_date": hoje,
        "due_date": hoje,
        "farm": ctx.current_farm(request, request.user),
    }


class TituloCreateView(GerenciaTitulosMixin, View):
    template_name = "finance/titulo_form.html"

    def get(self, request):
        form = TituloForm(user=request.user, initial=_initial_de_origem(request))
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = TituloForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        try:
            titulo = services.criar_titulo(usuario=request.user, **form.dados_limpos())
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form})
        messages.success(
            request,
            f"✓ Título {titulo.code} lançado: {dinheiro_br(titulo.amount)}, vence em "
            f"{titulo.due_date:%d/%m/%Y}. Próximo passo: programar o pagamento.",
        )
        return redirect("finance:titulo_detalhe", pk=titulo.pk)


class TituloDetailView(VeTitulosMixin, TemplateView):
    template_name = "finance/titulo_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        titulo = _get_titulo(self.request, kwargs["pk"])
        hoje = datetime.date.today()
        ativo = titulo.status == Status.CONFIRMADA
        a_pagar = not titulo.a_receber
        sem_baixa = not titulo.baixas_ativas().exists()

        conta = None
        if pode_ver_dado_bancario(user) and titulo.bank_account_id:
            conta = titulo.bank_account
            services.registrar_consulta_a_dado_bancario(titulo, usuario=user)

        alertas = []
        if ativo and titulo.em_aberto:
            if titulo.payee_id is None:
                alertas.append(
                    "Este título não tem favorecido. Informe a quem se paga "
                    "(Editar) antes de programar."
                )
            elif a_pagar and titulo.bank_account_id is None:
                alertas.append(
                    f"{titulo.payee} não tem conta bancária escolhida. Cadastre a "
                    "conta em Parceiros ou escolha uma ao programar."
                )
            if titulo.vencido(hoje):
                alertas.append(
                    f"Venceu em {titulo.due_date:%d/%m/%Y} "
                    f"({(hoje - titulo.due_date).days} dias)."
                )

        context.update(
            {
                "titulo": titulo,
                "hoje": hoje,
                "baixas": titulo.payments.select_related("created_by").order_by(
                    "date", "id"
                ),
                "conta": conta,
                "alertas": alertas,
                "eventos": OperationEvent.objects.filter(
                    entity_type="Invoice", entity_id=str(titulo.pk)
                ).order_by("timestamp"),
                "pode_programar": ativo
                and a_pagar
                and pode_gerenciar_titulos(user)
                and titulo.payment_status
                in (PaymentStatus.A_PAGAR, PaymentStatus.PROGRAMADO),
                "pode_aprovar": ativo
                and a_pagar
                and pode_aprovar_pagamento(user)
                and titulo.payment_status == PaymentStatus.PROGRAMADO,
                "pode_devolver": ativo
                and a_pagar
                and pode_gerenciar_titulos(user)
                and titulo.payment_status
                in (PaymentStatus.PROGRAMADO, PaymentStatus.APROVADO),
                "pode_baixar": ativo
                and pode_executar_pagamento(user)
                and titulo.payment_status
                in services.situacoes_que_aceitam_baixa(titulo),
                "pode_editar": ativo and pode_gerenciar_titulos(user) and sem_baixa,
                "pode_excluir": ativo and pode_excluir_confirmado(user),
                "pode_restaurar": titulo.status == Status.EXCLUIDA
                and pode_excluir_confirmado(user),
                "bloqueios": titulo.bloqueios() if ativo else [],
                "operacao_cancelada": titulo.origem is not None
                and titulo.origem.status == Status.EXCLUIDA,
            }
        )
        return context


class TituloUpdateView(GerenciaTitulosMixin, View):
    template_name = "finance/titulo_edit_form.html"

    def _initial(self, titulo: Invoice) -> dict:
        inicial = {
            campo: getattr(titulo, campo)
            for campo in (
                "direction",
                "component",
                "document",
                "issue_date",
                "due_date",
                "amount",
                "notes",
            )
        }
        for relacao in ("farm", "payee", "bank_account"):
            inicial[relacao] = getattr(titulo, f"{relacao}_id")
        return inicial

    def get(self, request, pk):
        titulo = _get_titulo(request, pk)
        form = TituloEditForm(
            user=request.user,
            initial=self._initial(titulo),
            campos_editaveis=services.campos_editaveis(titulo),
        )
        return render(request, self.template_name, {"form": form, "titulo": titulo})

    def post(self, request, pk):
        titulo = _get_titulo(request, pk)
        form = TituloEditForm(
            request.POST,
            user=request.user,
            initial=self._initial(titulo),
            campos_editaveis=services.campos_editaveis(titulo),
        )
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "titulo": titulo})
        dados = form.dados_limpos()
        motivo = dados.pop("edit_reason", "")
        # Só vai ao serviço o que a tela mostrou: campo ausente do form não é
        # "limpar", é "não mexer".
        dados = {k: v for k, v in dados.items() if k in form.fields}
        try:
            services.editar_titulo(titulo, dados, usuario=request.user, motivo=motivo)
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form, "titulo": titulo})
        messages.success(request, f"✓ Título {titulo.code} corrigido.")
        return redirect("finance:titulo_detalhe", pk=titulo.pk)


class TituloDeleteView(_SoQuemVeTitulos, ExclusaoComImpactoView):
    model = Invoice
    titulo = "Cancelar título"

    def url_do_registro(self, registro):
        return reverse("finance:titulo_detalhe", args=[registro.pk])

    def executar_exclusao(self, registro, *, motivo, cascata):
        services.excluir_titulo(
            registro, usuario=self.request.user, motivo=motivo, cascata=cascata
        )

    def _contexto(self, registro, **extra):
        return super()._contexto(
            registro, verbo="Cancelar título", verbo_infinitivo="cancelar", **extra
        )


class TituloRestoreView(VeTitulosMixin, View):
    def post(self, request, pk):
        titulo = _get_titulo(request, pk)
        try:
            services.restaurar_titulo(titulo, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Título {titulo.code} restaurado.")
        return redirect("finance:titulo_detalhe", pk=titulo.pk)


# --------------------------------------------------------------------------
# Programar, aprovar, devolver (F4-03)
# --------------------------------------------------------------------------


class TituloProgramarView(GerenciaTitulosMixin, View):
    template_name = "finance/titulo_programar.html"

    def get(self, request, pk):
        titulo = _get_titulo(request, pk)
        form = ProgramarForm(
            titulo=titulo,
            initial={
                "scheduled_date": titulo.scheduled_date
                or max(titulo.due_date, datetime.date.today()),
                "bank_account": titulo.bank_account_id,
            },
        )
        return render(request, self.template_name, {"form": form, "titulo": titulo})

    def post(self, request, pk):
        titulo = _get_titulo(request, pk)
        form = ProgramarForm(request.POST, titulo=titulo)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "titulo": titulo})
        try:
            services.programar_titulo(
                titulo,
                usuario=request.user,
                data=form.cleaned_data["scheduled_date"],
                bank_account=form.cleaned_data["bank_account"],
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form, "titulo": titulo})
        messages.success(
            request,
            f"✓ Pagamento do título {titulo.code} programado para "
            f"{form.cleaned_data['scheduled_date']:%d/%m/%Y}. Falta aprovar.",
        )
        return redirect("finance:titulo_detalhe", pk=titulo.pk)


class TituloAprovarView(VeTitulosMixin, View):
    """GET mostra o que se está aprovando; POST aprova."""

    template_name = "finance/titulo_aprovar.html"

    def get(self, request, pk):
        titulo = _get_titulo(request, pk)
        return render(
            request,
            self.template_name,
            {
                "titulo": titulo,
                "conta": (
                    titulo.bank_account
                    if pode_ver_dado_bancario(request.user)
                    else None
                ),
                "pode_aprovar": pode_aprovar_pagamento(request.user),
            },
        )

    def post(self, request, pk):
        titulo = _get_titulo(request, pk)
        try:
            services.aprovar_titulo(titulo, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
            return redirect("finance:titulo_detalhe", pk=titulo.pk)
        messages.success(
            request,
            f"✓ Pagamento do título {titulo.code} aprovado. Agora o financeiro "
            "pode dar a baixa.",
        )
        return redirect("finance:titulo_detalhe", pk=titulo.pk)


class TituloDevolverView(GerenciaTitulosMixin, View):
    template_name = "finance/motivo_form.html"

    def _contexto(self, titulo, form):
        return {
            "form": form,
            "titulo": titulo,
            "pagina_titulo": f"Devolver o título {titulo.code}",
            "subtitulo": (
                "A programação e a aprovação deixam de valer e o título volta a "
                "'a pagar'. Quem tira uma aprovação informa o motivo."
            ),
            "salvar": "Devolver o título",
            "voltar": reverse("finance:titulo_detalhe", args=[titulo.pk]),
        }

    def get(self, request, pk):
        titulo = _get_titulo(request, pk)
        return render(request, self.template_name, self._contexto(titulo, MotivoForm()))

    def post(self, request, pk):
        titulo = _get_titulo(request, pk)
        form = MotivoForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._contexto(titulo, form))
        try:
            services.desprogramar_titulo(
                titulo, usuario=request.user, motivo=form.cleaned_data["motivo"]
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, self._contexto(titulo, form))
        messages.success(request, f"✓ Título {titulo.code} devolvido a 'a pagar'.")
        return redirect("finance:titulo_detalhe", pk=titulo.pk)


# --------------------------------------------------------------------------
# Baixa (F4-04) e desfazer baixa (F4-05)
# --------------------------------------------------------------------------


class TituloBaixarView(VeTitulosMixin, View):
    template_name = "finance/titulo_baixar.html"

    def _contexto(self, titulo, form):
        return {
            "form": form,
            "titulo": titulo,
            "pode_executar": pode_executar_pagamento(self.request.user),
            "aceita_baixa": titulo.status == Status.CONFIRMADA
            and titulo.payment_status in services.situacoes_que_aceitam_baixa(titulo),
        }

    def get(self, request, pk):
        titulo = _get_titulo(request, pk)
        form = BaixaForm(
            initial={
                "date": datetime.date.today(),
                "amount": titulo.balance,
                "method": PaymentMethod.PIX,
            }
        )
        return render(request, self.template_name, self._contexto(titulo, form))

    def post(self, request, pk):
        titulo = _get_titulo(request, pk)
        form = BaixaForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._contexto(titulo, form))
        dados = form.cleaned_data
        try:
            baixa = services.baixar_titulo(
                titulo,
                usuario=request.user,
                date=dados["date"],
                amount=dados["amount"],
                method=dados["method"],
                document=dados["document"],
                notes=dados["notes"],
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, self._contexto(titulo, form))
        titulo.refresh_from_db()
        if titulo.payment_status == PaymentStatus.PAGO:
            resto = f"O título {titulo.code} está quitado."
        else:
            resto = f"Faltam {dinheiro_br(titulo.balance)} no título {titulo.code}."
        messages.success(
            request,
            f"✓ {baixa.verbo} {baixa.code} registrado: {dinheiro_br(baixa.amount)}. "
            f"{resto}",
        )
        return redirect("finance:pagamento_detalhe", pk=baixa.pk)


class PagamentoListView(VeTitulosMixin, TemplateView):
    template_name = "finance/pagamento_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        farm = ctx.current_farm(self.request, user)
        form = FiltroContasForm(self.request.GET or None)
        filtros = form.cleaned_data if form.is_valid() else {}
        direcao = self.request.GET.get("direcao") or ""
        if direcao not in Direction.values:
            direcao = ""
        pagamentos = list(
            selectors.pagamentos_para(
                user,
                farm=farm,
                direction=direcao or None,
                de=filtros.get("de"),
                ate=filtros.get("ate"),
                incluir_desfeitos=self.request.GET.get("desfeitos") == "1",
            )
        )
        pagina = Paginator(pagamentos, POR_PAGINA).get_page(
            self.request.GET.get("page")
        )
        context.update(
            {
                "filtro": form,
                "page_obj": pagina,
                "pagamentos": pagina.object_list,
                "direcao": direcao,
                "desfeitos": self.request.GET.get("desfeitos") == "1",
                "total": sum(
                    (p.amount for p in pagamentos if p.status == Status.CONFIRMADA),
                    start=0,
                ),
            }
        )
        return context


class PagamentoDetailView(VeTitulosMixin, TemplateView):
    template_name = "finance/pagamento_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pagamento = _get_pagamento(self.request, kwargs["pk"])
        user = self.request.user
        context.update(
            {
                "pagamento": pagamento,
                "titulo": pagamento.invoice,
                "pode_desfazer": pagamento.status == Status.CONFIRMADA
                and pode_desfazer_baixa(user),
                "pode_restaurar": pagamento.status == Status.EXCLUIDA
                and pode_desfazer_baixa(user),
                "bloqueios": (
                    pagamento.bloqueios()
                    if pagamento.status == Status.CONFIRMADA
                    else []
                ),
            }
        )
        return context


class PagamentoDesfazerView(_SoQuemVeTitulos, ExclusaoComImpactoView):
    """A única exceção ao "tudo é editável": análise de impacto, motivo
    obrigatório, e só `FINANCEIRO`/`ADMIN` (não `GESTOR`)."""

    model = Payment
    titulo = "Desfazer baixa"

    def url_do_registro(self, registro):
        return reverse("finance:pagamento_detalhe", args=[registro.pk])

    def _contexto(self, registro, **extra):
        return super()._contexto(
            registro,
            verbo="Desfazer a baixa",
            verbo_infinitivo="desfazer a baixa",
            motivo_de="de desfazer a baixa",
            **extra,
        )

    def executar_exclusao(self, registro, *, motivo, cascata):
        services.desfazer_baixa(registro, usuario=self.request.user, motivo=motivo)

    def get(self, request, pk):
        registro = self.get_registro(pk)
        if not pode_desfazer_baixa(request.user):
            return self._sem_permissao(registro)
        return render(request, self.template_name, self._contexto(registro))

    def post(self, request, pk):
        registro = self.get_registro(pk)
        if not pode_desfazer_baixa(request.user):
            return self._sem_permissao(registro)
        motivo = request.POST.get("motivo", "")
        try:
            self.executar_exclusao(registro, motivo=motivo, cascata=False)
        except (BusinessError, BlockingDependencyError, DependencyError) as exc:
            return render(
                request,
                self.template_name,
                self._contexto(registro, motivo=motivo, erro=str(exc)),
            )
        messages.success(
            request,
            f"✓ Baixa {registro.code} desfeita. O título {registro.invoice.code} "
            "voltou a ter saldo em aberto. Confira o extrato: o sistema não "
            "desfaz a transferência no banco.",
        )
        return redirect("finance:titulo_detalhe", pk=registro.invoice_id)


class PagamentoRestoreView(VeTitulosMixin, View):
    def post(self, request, pk):
        pagamento = _get_pagamento(request, pk)
        try:
            services.restaurar_baixa(pagamento, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"✓ Baixa {pagamento.code} restaurada.")
        return redirect("finance:pagamento_detalhe", pk=pagamento.pk)


# --------------------------------------------------------------------------
# Operações sem título (histórico) e apoio HTMX
# --------------------------------------------------------------------------


class SemTituloView(GerenciaTitulosMixin, View):
    """Compras e vendas confirmadas antes do financeiro existir. Gerar o
    título é decisão de quem conhece o caso — muitas já foram pagas fora do
    sistema, e gerar todas de uma vez encheria "vencidos" de coisa antiga."""

    template_name = "finance/sem_titulo.html"

    def get(self, request):
        compras, vendas = selectors.operacoes_sem_titulo(request.user)
        return render(
            request, self.template_name, {"compras": compras, "vendas": vendas}
        )

    def post(self, request):
        from apps.purchases.models import Purchase
        from apps.sales.models import Sale

        gerados, falhas = 0, []
        for chave in request.POST.getlist("operacao"):
            tipo, _, pk = chave.partition(":")
            modelo = {"compra": Purchase, "venda": Sale}.get(tipo)
            if modelo is None or not pk.isdigit():
                continue
            operacao = get_object_or_404(modelo.objects.for_user(request.user), pk=pk)
            try:
                gerados += len(
                    services.gerar_titulos_de_operacao_existente(
                        operacao, usuario=request.user
                    )
                )
            except BusinessError as exc:
                falhas.append(f"{operacao}: {exc}")
        if gerados:
            messages.success(
                request,
                f"✓ {gerados} título{'s' if gerados != 1 else ''} gerado"
                f"{'s' if gerados != 1 else ''}. Confira os vencimentos em "
                "Contas a pagar e a receber.",
            )
        for falha in falhas:
            messages.error(request, falha)
        if not gerados and not falhas:
            messages.warning(request, "Marque ao menos uma operação.")
        destino = request.POST.get("next", "")
        if destino and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={request.get_host()}
        ):
            return redirect(destino)
        return redirect("finance:sem_titulo")


class ContasDoFavorecidoView(GerenciaTitulosMixin, View):
    """Fragmento HTMX: as contas do favorecido escolhido, para o select. O
    rótulo é mascarado — o número inteiro não passa por aqui."""

    def get(self, request):
        contas = []
        pk = request.GET.get("payee", "")
        if pk.isdigit():
            contas = [
                (c.pk, rotulo_da_conta(c))
                for c in BankAccount.objects.filter(partner_id=int(pk))
            ]
        return render(request, "finance/_opcoes_conta.html", {"contas": contas})
