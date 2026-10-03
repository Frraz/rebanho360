import uuid

from apps.core import request_context


class RequestContextMiddleware:
    """Gera `request_id` por requisição e popula o contexto compartilhado.

    Dois efeitos: (1) dois eventos de auditoria da mesma requisição
    compartilham `request_id`; (2) serviços gravam auditoria sem receber
    `request`, lendo `apps.core.request_context.get_current()`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = uuid.uuid4()
        request.request_id = request_id

        actor = getattr(request, "user", None)
        if actor is not None and not actor.is_authenticated:
            actor = None

        request_context.set_current(
            request_context.RequestContext(
                actor=actor,
                ip_address=request_context.client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:400],
                request_id=request_id,
            )
        )
        try:
            response = self.get_response(request)
        finally:
            request_context.reset()

        response["X-Request-ID"] = str(request_id)
        return response
