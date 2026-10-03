import csv

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import TemplateView

from apps.accounts.selectors import usuarios_visiveis
from apps.audit import selectors
from apps.audit.models import AuditAction, AuditEvent
from apps.audit.permissions import AuditConsoleAccessMixin
from apps.core import reversible
from apps.core.exceptions import BusinessError


def _group_cascades(events: list[AuditEvent]) -> list[dict]:
    """Agrupa eventos de uma mesma cascata num item só — ver
    docs/regras-negocio/06-edicao-exclusao-e-auditoria.md#console-de-auditoria."""
    rows, seen = [], set()
    for event in events:
        if event.cascade_root:
            if event.cascade_root in seen:
                continue
            seen.add(event.cascade_root)
            group = [e for e in events if e.cascade_root == event.cascade_root]
        else:
            group = [event]
        rows.append({"primary": event, "group": group, "is_cascade": len(group) > 1})
    return rows


class ConsoleView(AuditConsoleAccessMixin, TemplateView):
    template_name = "audit/console.html"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET

        events = selectors.filter_events(
            user_id=params.get("user") or None,
            action=params.get("action") or None,
            entity_type=params.get("entity_type") or None,
            date_from=params.get("de") or None,
            date_to=params.get("ate") or None,
            ip_address=params.get("ip") or None,
        )

        paginator = Paginator(events, self.paginate_by)
        page = paginator.get_page(params.get("page"))

        context.update(
            {
                "page": page,
                "rows": _group_cascades(list(page.object_list)),
                "usuarios": usuarios_visiveis(self.request.user).order_by("username"),
                "acoes": AuditAction.choices,
                "entidades": selectors.distinct_entity_types(),
                "filtros": params,
            }
        )
        return context


class RestoreView(AuditConsoleAccessMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(["POST"])

    def post(self, request, *args, **kwargs):
        event = get_object_or_404(AuditEvent, pk=kwargs["pk"])
        model = selectors.resolve_model(event.entity_type)
        if model is None:
            messages.error(request, "Tipo de registro desconhecido para restauração.")
            return redirect("audit:console")

        registro = get_object_or_404(model, pk=event.entity_id)
        try:
            reversible.restaurar(registro, usuario=request.user)
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request, f"{event.entity_type} restaurado(a) a partir do evento."
            )
        return redirect("audit:console")


class TimelineView(AuditConsoleAccessMixin, TemplateView):
    template_name = "audit/timeline.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity_type"] = kwargs["entity_type"]
        context["entity_id"] = kwargs["entity_id"]
        context["events"] = selectors.timeline_for(
            kwargs["entity_type"], kwargs["entity_id"]
        )
        return context


class ExportCsvView(AuditConsoleAccessMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        events = selectors.filter_events(
            user_id=request.GET.get("user") or None,
            action=request.GET.get("action") or None,
            entity_type=request.GET.get("entity_type") or None,
            date_from=request.GET.get("de") or None,
            date_to=request.GET.get("ate") or None,
            ip_address=request.GET.get("ip") or None,
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="auditoria.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["timestamp", "ator", "ação", "entidade", "id", "motivo", "ip", "cascata"]
        )
        for e in events:
            writer.writerow(
                [
                    e.timestamp.isoformat(),
                    str(e.actor) if e.actor else "",
                    e.get_action_display(),
                    e.entity_type,
                    e.entity_id,
                    e.reason,
                    e.ip_address or "",
                    str(e.cascade_root) if e.cascade_root else "",
                ]
            )

        registrar_auditoria_export(request)
        return response


def registrar_auditoria_export(request):
    from apps.audit.services import registrar_auditoria

    registrar_auditoria(
        action=AuditAction.EXPORT,
        entity_type="AuditEvent",
        entity_id="",
        reason="Exportação CSV do console de auditoria",
        actor=request.user,
    )
