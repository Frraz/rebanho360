"""Fino. Recebe request, chama o serviço de relatório, devolve tela ou arquivo."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify
from django.views import View

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import context as ctx
from apps.livestock.models import Lot
from apps.procurement.permissions import VeOCicloMixin
from apps.reports import services
from apps.reports.parametros import (
    campos_de_selecao,
    compradores_do_escopo,
    parametros_do_relatorio,
)

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class IndiceView(LoginRequiredMixin, View):
    def get(self, request):
        return render(
            request,
            "reports/index.html",
            {"catalogo": services.catalogo_para(request.user)},
        )


class ContratosView(VeOCicloMixin, View):
    """ "Contrato de Compra" no catálogo de relatórios: a lista dos compromissos
    aprovados, cada um com o botão que gera o contrato em PDF (o mesmo documento
    do detalhe do compromisso, com a versão do layout e o hash gravados)."""

    por_pagina = 30

    def get(self, request):
        from apps.core.reversible import Status
        from apps.documents.models import DocumentType, GeneratedDocument
        from apps.procurement.models import Commitment
        from apps.reports.parametros import _data

        season = ctx.current_season(request, ctx.current_company())
        farm = ctx.current_farm(request, request.user)
        de, ate = _data(request.GET.get("de")), _data(request.GET.get("ate"))
        comprador = request.GET.get("comprador", "")
        texto = request.GET.get("q", "").strip()

        qs = (
            Commitment.objects.for_user(request.user)
            .filter(status=Status.CONFIRMADA)
            .select_related("seller", "destination_farm")
            .annotate(cabecas=Sum("items__head_count"))
            .order_by("-date", "-id")
        )
        if season is not None:
            qs = qs.filter(season=season)
        if farm is not None:
            qs = qs.filter(destination_farm=farm)
        if de:
            qs = qs.filter(date__gte=de)
        if ate:
            qs = qs.filter(date__lte=ate)
        if comprador.isdigit():
            qs = qs.filter(commissions__payee_id=comprador)
        if texto:
            qs = qs.filter(Q(code__icontains=texto) | Q(seller__name__icontains=texto))

        pagina = Paginator(qs, self.por_pagina).get_page(request.GET.get("page"))
        compromissos = list(pagina.object_list)
        # O último contrato gerado de cada compromisso da página (uma consulta).
        gerados = {}
        for d in GeneratedDocument.objects.filter(
            doc_type=DocumentType.CONTRATO,
            entity_type="Commitment",
            entity_id__in=[str(c.pk) for c in compromissos],
        ).order_by("generated_at"):
            gerados[d.entity_id] = d
        for c in compromissos:
            c.contrato = gerados.get(str(c.pk))
        return render(
            request,
            "reports/contratos.html",
            {
                "page_obj": pagina,
                "compromissos": compromissos,
                "season": season,
                "compradores": compradores_do_escopo(request.user),
                "de": request.GET.get("de", ""),
                "ate": request.GET.get("ate", ""),
                "comprador": comprador,
                "q": texto,
                "filtrando": any((de, ate, comprador, texto)),
            },
        )


class RelatorioView(LoginRequiredMixin, View):
    """Qualquer usuário logado vê o relatório — mas sempre dentro do escopo
    de fazendas dele (`for_user` nos seletores)."""

    def get(self, request, slug):
        if slug not in services.RELATORIOS:
            raise Http404

        season = ctx.current_season(request, ctx.current_company())
        farm = ctx.current_farm(request, request.user)
        extras = parametros_do_relatorio(request.user, slug, request.GET)
        relatorio = services.montar_relatorio(
            request.user, slug, season=season, farm=farm, extras=extras
        )

        formato = request.GET.get("formato")
        if formato in ("csv", "xlsx"):
            registrar_auditoria(
                action=AuditAction.EXPORT,
                entity_type="Relatorio",
                entity_id=slug,
                reason=f"{relatorio.titulo} ({formato}) · "
                + " · ".join(relatorio.filtros),
                actor=request.user,
            )
            nome = slugify(relatorio.titulo)
            if formato == "csv":
                resposta = HttpResponse(
                    services.csv_do_relatorio(relatorio),
                    content_type="text/csv; charset=utf-8",
                )
            else:
                resposta = HttpResponse(
                    services.xlsx_do_relatorio(
                        relatorio,
                        emitido_por=str(request.user),
                        emitido_em=timezone.localtime().replace(tzinfo=None),
                    ),
                    content_type=TIPO_XLSX,
                )
            resposta["Content-Disposition"] = f'attachment; filename="{nome}.{formato}"'
            return resposta

        aceitos = services.PARAMETROS.get(slug, ())
        return render(
            request,
            "reports/relatorio.html",
            {
                "relatorio": relatorio,
                "tabela": services.para_tela(relatorio),
                "secoes": [(s, services.para_tela(s)) for s in relatorio.secoes],
                "slug": slug,
                "aceita_periodo": "de" in aceitos,
                "aceita_lote": "lote" in aceitos,
                "aceita_rendimento": "rendimento_entrada" in aceitos,
                "aceita_preco_arroba": "preco_arroba" in aceitos,
                "preco_arroba": request.GET.get("preco_arroba", ""),
                "tem_filtros": bool(aceitos),
                "lotes": (
                    Lot.objects.for_user(request.user).order_by("code")
                    if "lote" in aceitos
                    else []
                ),
                "de": request.GET.get("de", ""),
                "ate": request.GET.get("ate", ""),
                "campos": campos_de_selecao(request.user, slug, request.GET),
                "lote_escolhido": request.GET.get("lote", ""),
                "rendimento_entrada": request.GET.get("rendimento_entrada", ""),
            },
        )
