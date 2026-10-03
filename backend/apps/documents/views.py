"""Fino. Recebe request, chama o serviço, devolve tela ou arquivo.

O PDF nunca é servido como arquivo estático: só por view autenticada, e só
a quem o gerou (ou a quem enxerga tudo). Fora disso, 404 — não 403.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import context as ctx
from apps.core.exceptions import BusinessError
from apps.documents import services
from apps.documents.models import DocumentStatus, GeneratedDocument
from apps.documents.permissions import pode_ver_documento


def _documento(request, document_id) -> GeneratedDocument:
    documento = get_object_or_404(GeneratedDocument, document_id=document_id)
    if not pode_ver_documento(request.user, documento):
        raise Http404
    return documento


class GerarView(LoginRequiredMixin, View):
    """POST: criar um documento é gravar. Os filtros da tela vêm junto."""

    http_method_names = ["post"]

    def post(self, request, slug):
        season = ctx.current_season(request, ctx.current_company())
        farm = ctx.current_farm(request, request.user)
        try:
            documento = services.solicitar_documento(
                slug=slug,
                user=request.user,
                season=season,
                farm=farm,
                origem=request.POST,
            )
        except BusinessError as exc:
            raise Http404(str(exc)) from exc
        return redirect("documents:detalhe", document_id=documento.document_id)


class DocumentDetailView(LoginRequiredMixin, View):
    def get(self, request, document_id):
        documento = _documento(request, document_id)
        template = (
            "documents/_estado.html"
            if request.htmx
            else "documents/document_detail.html"
        )
        return render(request, template, {"documento": documento})


class DownloadView(LoginRequiredMixin, View):
    def get(self, request, document_id):
        documento = _documento(request, document_id)
        if documento.status != DocumentStatus.PRONTO or not documento.file:
            messages.error(request, "Este documento ainda não está pronto.")
            return redirect("documents:detalhe", document_id=documento.document_id)
        registrar_auditoria(
            action=AuditAction.EXPORT,
            entity_type="Documento",
            entity_id=str(documento.document_id),
            reason="download do PDF",
            actor=request.user,
        )
        resposta = FileResponse(
            documento.file.open("rb"), content_type="application/pdf"
        )
        resposta["Content-Disposition"] = (
            f'attachment; filename="{documento.entity_id}-{documento.generated_at:%Y%m%d-%H%M}.pdf"'
        )
        return resposta


class DocumentListView(LoginRequiredMixin, View):
    def get(self, request):
        documentos = GeneratedDocument.objects.select_related("generated_by")
        if not request.user.has_broad_access:
            documentos = documentos.filter(generated_by=request.user)
        return render(
            request, "documents/document_list.html", {"documentos": documentos[:100]}
        )
