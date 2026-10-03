"""Fino. Recebe request, chama o serviço de relatório, devolve tela ou arquivo."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify
from django.views import View

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import context as ctx
from apps.livestock.models import Lot
from apps.reports import services
from apps.reports.parametros import parametros_do_relatorio

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class IndiceView(LoginRequiredMixin, View):
    def get(self, request):
        return render(
            request,
            "reports/index.html",
            {"catalogo": services.catalogo_para(request.user)},
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
                "tem_filtros": bool(aceitos),
                "lotes": (
                    Lot.objects.for_user(request.user).order_by("code")
                    if "lote" in aceitos
                    else []
                ),
                "de": request.GET.get("de", ""),
                "ate": request.GET.get("ate", ""),
                "lote_escolhido": request.GET.get("lote", ""),
                "rendimento_entrada": request.GET.get("rendimento_entrada", ""),
            },
        )
