from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core import health

urlpatterns = [
    path("health/", health.health, name="health"),
    path("ready/", health.ready, name="ready"),
    path("admin/", admin.site.urls),
    path("contas/", include("apps.accounts.urls")),
    path("auditoria/", include("apps.audit.urls")),
    path("organizacao/", include("apps.organizations.urls")),
    path("propriedades/", include("apps.properties.urls")),
    path("parceiros/", include("apps.partners.urls")),
    path("rebanho/", include("apps.livestock.urls")),
    path("rebanho/movimentacoes/", include("apps.herd.urls")),
    path("compras/", include("apps.purchases.urls")),
    path("vendas/", include("apps.sales.urls")),
    path("custos/", include("apps.costs.urls")),
    path("financeiro/", include("apps.finance.urls")),
    path("comercial/", include("apps.commercial.urls")),
    path("ciclo-de-compra/", include("apps.procurement.urls")),
    path("importacoes/", include("apps.imports.urls")),
    path("exportacoes/", include("apps.exports.urls")),
    path("relatorios/", include("apps.reports.urls")),
    path("documentos/", include("apps.documents.urls")),
    path("", include("apps.dashboards.urls")),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
