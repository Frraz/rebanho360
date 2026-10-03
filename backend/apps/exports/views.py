"""Fino. Recebe request, chama o serviço, devolve tela ou arquivo.

Cada exportação é de quem a pediu: só ele a vê e a baixa. Outro usuário — até
o `ADMIN` — recebe 404, não 403 (o 403 confirmaria que existe). O arquivo tem
os dados do escopo de quem pediu, e não há razão para outro papel herdá-los.
"""

from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.exceptions import BusinessError
from apps.exports import catalog, services
from apps.exports.forms import ExportForm
from apps.exports.models import STATUS_EM_ANDAMENTO, ExportJob
from apps.exports.permissions import ExportaMixin

PRIMEIROS_FORMATOS = ["csv", "xlsx"]


def _pedido_do_usuario(request, job_id) -> ExportJob:
    return get_object_or_404(
        ExportJob.objects.select_related("requested_by"),
        job_id=job_id,
        requested_by=request.user,
    )


class ListaView(ExportaMixin, View):
    def get(self, request):
        pedidos = ExportJob.objects.filter(requested_by=request.user)[:50]
        return render(request, "exports/export_list.html", {"pedidos": pedidos})


class NovaView(ExportaMixin, View):
    template_name = "exports/export_form.html"

    def _contexto(self, request, form):
        contagens = services.contagens_para(request.user)
        conjuntos_marcados = set(form["conjuntos"].value() or [])
        relatorios_marcados = set(form["relatorios"].value() or [])
        return {
            "form": form,
            "grupos": [
                (
                    grupo,
                    [
                        {
                            "conjunto": c,
                            "marcado": c.chave in conjuntos_marcados,
                            "total": contagens.get(c.chave),
                        }
                        for c in conjuntos
                    ],
                )
                for grupo, conjuntos in catalog.grupos_para(request.user)
            ],
            "relatorios": [
                (slug, titulo, descricao, slug in relatorios_marcados)
                for slug, titulo, descricao in catalog.relatorios_para(request.user)
            ],
            "formatos": services.FORMATOS,
            "estilos_do_csv": services.ESTILOS_DO_CSV,
            "ativas": ExportJob.objects.filter(
                requested_by=request.user, status__in=STATUS_EM_ANDAMENTO
            ).count(),
        }

    def get(self, request):
        # Sem filtro de safra nem de fazenda de partida, de propósito: quem
        # exporta "tudo" para guardar não pode levar só a safra do topo da tela
        # sem perceber. `?conjuntos=lotes` pré-marca (para links de outras telas).
        inicial = {
            "formatos": PRIMEIROS_FORMATOS,
            "csv": "br",
            "conjuntos": request.GET.getlist("conjuntos"),
            "relatorios": request.GET.getlist("relatorios"),
        }
        form = ExportForm(initial=inicial, user=request.user)
        return render(request, self.template_name, self._contexto(request, form))

    def post(self, request):
        form = ExportForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                job = services.solicitar_exportacao(**form.pedido())
            except BusinessError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    "✓ Exportação pedida. Ela roda em segundo plano: você pode sair "
                    "desta tela e voltar depois em Exportações.",
                )
                return redirect("exports:detalhe", job_id=job.job_id)
        return render(request, self.template_name, self._contexto(request, form))


class DetalheView(ExportaMixin, View):
    def get(self, request, job_id):
        job = _pedido_do_usuario(request, job_id)
        # O HTMX só pede o fragmento (a cada 2 s, enquanto roda).
        template = (
            "exports/_estado.html" if request.htmx else "exports/export_detail.html"
        )
        return render(request, template, {"job": job})


class BaixarView(ExportaMixin, View):
    def get(self, request, job_id):
        job = _pedido_do_usuario(request, job_id)
        if not job.baixavel:
            messages.error(
                request, "Esta exportação não tem arquivo para baixar (ainda ou mais)."
            )
            return redirect("exports:detalhe", job_id=job.job_id)
        registrar_auditoria(
            action=AuditAction.EXPORT,
            entity_type="Exportacao",
            entity_id=str(job.job_id),
            reason=f"download de {job.file_name}",
            actor=request.user,
        )
        resposta = FileResponse(
            job.file.open("rb"),
            as_attachment=True,
            filename=job.file_name,
            content_type=job.content_type or "application/octet-stream",
        )
        # Dado do negócio: nunca fica em cache de navegador nem de proxy.
        resposta["Cache-Control"] = "private, no-store"
        return resposta


class _AcaoView(ExportaMixin, View):
    """Ação que escreve: só POST (e CSRF), nunca um link de GET."""

    http_method_names = ["post"]

    def agir(self, request, job):
        raise NotImplementedError

    def post(self, request, job_id):
        job = _pedido_do_usuario(request, job_id)
        try:
            return self.agir(request, job)
        except BusinessError as exc:
            messages.error(request, str(exc))
        return redirect("exports:detalhe", job_id=job.job_id)


class CancelarView(_AcaoView):
    def agir(self, request, job):
        services.cancelar_exportacao(job, user=request.user)
        messages.success(request, "✓ Cancelamento pedido. Nada será entregue.")
        return redirect("exports:detalhe", job_id=job.job_id)


class RepetirView(_AcaoView):
    def agir(self, request, job):
        novo = services.repetir_exportacao(job, user=request.user)
        messages.success(request, "✓ Nova exportação pedida com os mesmos parâmetros.")
        return redirect("exports:detalhe", job_id=novo.job_id)


class ApagarView(_AcaoView):
    def agir(self, request, job):
        services.apagar_arquivo(job, user=request.user)
        messages.success(
            request,
            "✓ Arquivo apagado do servidor. O registro do pedido continua na lista.",
        )
        return redirect("exports:detalhe", job_id=job.job_id)
