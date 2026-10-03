"""Fino. Recebe request, chama service/selector, devolve template."""

import re

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.core.exceptions import BusinessError
from apps.imports import services
from apps.imports.forms import FORMS_DE_OPCOES, UploadForm
from apps.imports.models import BatchStatus, ImportBatch, ImportKind, RowStatus
from apps.imports.permissions import ImportaMixin

POR_PAGINA = 40

#: O que sugerir como próximo passo depois de importar cada tipo.
PROXIMO_PASSO = {
    ImportKind.CUSTOS: ("costs:lista", "Ver os custos importados"),
    ImportKind.COMPRAS: (
        "imports:nova",
        "Importar agora as movimentações das fazendas",
    ),
    ImportKind.MOVIMENTACOES: (
        "imports:nova",
        "Importar agora as vendas e abates",
    ),
    ImportKind.VENDAS: ("sales:lista", "Ver as vendas importadas"),
    ImportKind.PESAGENS: ("herd:pesagem_lista", "Ver as pesagens importadas"),
}


class BatchListView(ImportaMixin, ListView):
    template_name = "imports/batch_list.html"
    context_object_name = "lotes"
    paginate_by = 30

    def get_queryset(self):
        return ImportBatch.objects.select_related("created_by")


class UploadView(ImportaMixin, View):
    template_name = "imports/upload.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"form": UploadForm(initial=request.GET.dict())},
        )

    def post(self, request):
        form = UploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        dados = form.cleaned_data
        try:
            lote = services.criar_importacao(
                kind=dados["kind"],
                arquivo=dados["file"],
                usuario=request.user,
                confirmar_reimportacao=dados["confirmar_reimportacao"],
            )
        except services.ImportacaoDuplicada as exc:
            form.add_error(None, str(exc))
            return render(
                request, self.template_name, {"form": form, "duplicada": True}
            )
        except BusinessError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form})

        messages.success(
            request,
            f"✓ Planilha lida: {lote.rows.count()} linhas na prévia. Nada foi importado ainda.",
        )
        return redirect("imports:detalhe", pk=lote.pk)


def _linha_com_campos(row, importador, lote):
    return {
        "row": row,
        "descricao": importador.descrever(row),
        "campos": importador.campos_da_linha(row, lote),
    }


class BatchDetailView(ImportaMixin, View):
    template_name = "imports/batch_detail.html"

    def _get_lote(self, pk) -> ImportBatch:
        return get_object_or_404(ImportBatch, pk=pk)

    def _contexto(self, request, lote, *, form_opcoes=None):
        importador = services.importador_de(lote)
        resumo = services.resumo_da_previa(lote)
        aberto = lote.status == BatchStatus.PREVIA

        filtro = request.GET.get("ver", "abertas")
        base = lote.rows.all()
        if filtro == "abertas":
            base = base.filter(status__in=[RowStatus.PENDENTE, RowStatus.ERRO])
        elif filtro in RowStatus.values:
            base = base.filter(status=filtro)
        pagina = Paginator(base, POR_PAGINA).get_page(request.GET.get("pagina"))

        return {
            "lote": lote,
            "aberto": aberto,
            "resumo": resumo,
            "form_opcoes": form_opcoes
            or (FORMS_DE_OPCOES[lote.kind](batch=lote) if aberto else None),
            "grupos": importador.grupos_de_sugestao(lote) if aberto else [],
            "linhas": (
                [_linha_com_campos(r, importador, lote) for r in pagina.object_list]
                if aberto
                else [
                    {"row": r, "descricao": importador.descrever(r), "campos": []}
                    for r in pagina.object_list
                ]
            ),
            "pagina": pagina,
            "filtro": filtro,
            "pode_importar": aberto
            and not resumo["problemas"]
            and resumo["prontas"] > 0,
            "proximo_passo": PROXIMO_PASSO.get(lote.kind),
            "status_rotulos": dict(RowStatus.choices),
        }

    def get(self, request, pk):
        return render(
            request, self.template_name, self._contexto(request, self._get_lote(pk))
        )

    def post(self, request, pk):
        lote = self._get_lote(pk)
        acao = request.POST.get("acao")
        try:
            if acao == "opcoes":
                return self._salvar_opcoes(request, lote)
            if acao == "decisoes":
                return self._salvar_decisoes(request, lote)
            if acao == "importar":
                return self._importar(request, lote)
            if acao == "cancelar":
                services.cancelar_importacao(lote, usuario=request.user)
                messages.success(request, "✓ Importação cancelada. Nada foi importado.")
                return redirect("imports:lista")
        except BusinessError as exc:
            messages.error(request, str(exc))
        return redirect("imports:detalhe", pk=lote.pk)

    def _salvar_opcoes(self, request, lote):
        form = FORMS_DE_OPCOES[lote.kind](request.POST, batch=lote)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                self._contexto(request, lote, form_opcoes=form),
            )
        lote = services.salvar_opcoes(lote, form.opcoes(), usuario=request.user)
        resumo = services.resumo_da_previa(lote)
        messages.success(
            request,
            f"✓ Opções salvas e linhas revalidadas: {resumo['prontas']} prontas, "
            f"{resumo['pendentes']} pendentes, {resumo['erros']} com erro.",
        )
        return redirect("imports:detalhe", pk=lote.pk)

    def _salvar_decisoes(self, request, lote):
        decisoes: dict[int, dict] = {}
        for chave, valor in request.POST.items():
            achou = re.fullmatch(r"r(\d+)__(\w+)", chave)
            if achou:
                decisoes.setdefault(int(achou.group(1)), {})[
                    achou.group(2)
                ] = valor.strip()
        grupos = request.POST.getlist("grupo")
        lote = services.salvar_decisoes(lote, decisoes, grupos, usuario=request.user)
        resumo = services.resumo_da_previa(lote)
        messages.success(
            request,
            f"✓ Decisões salvas: {resumo['prontas']} prontas, {resumo['pendentes']} "
            f"pendentes, {resumo['erros']} com erro.",
        )
        return redirect(request.path + "?" + request.GET.urlencode())

    def _importar(self, request, lote):
        if request.POST.get("confirmo") != "1":
            messages.error(request, "Marque a confirmação para importar.")
            return redirect("imports:detalhe", pk=lote.pk)
        resultado = services.importar(lote, usuario=request.user)
        messages.success(
            request,
            f"✓ Importação concluída: {_frase_do_resultado(lote.kind, resultado)}"
            + (
                f" {resultado['pendentes_restantes']} linha(s) ficaram pendentes neste lote."
                if resultado["pendentes_restantes"]
                else ""
            ),
        )
        return redirect("imports:detalhe", pk=lote.pk)


def _frase_do_resultado(kind, resultado) -> str:
    if kind == ImportKind.CUSTOS:
        return f"{resultado['importadas']} lançamentos de custo entraram."
    if kind == ImportKind.COMPRAS:
        return (
            f"{resultado['importadas']} compras confirmadas, {resultado['cabecas']} cabeças "
            "deram entrada no rebanho."
        )
    if kind == ImportKind.VENDAS:
        vinculadas = resultado.get("vinculadas", 0)
        return (
            f"{resultado['importadas']} vendas confirmadas, {resultado['cabecas']} cabeças."
            + (
                f" {vinculadas} delas adotaram a saída que já estava no rebanho, "
                "sem debitar as cabeças de novo."
                if vinculadas
                else ""
            )
        )
    if kind == ImportKind.PESAGENS:
        return f"{resultado['pesagens']} pesagens com {resultado['animais']} animais entraram."
    return f"{resultado['movimentos']} movimentações ({resultado['cabecas']} cabeças) entraram no razão."
