from django.urls import path

from apps.organizations import views

app_name = "organizations"

urlpatterns = [
    path("empresas/", views.CompanyListView.as_view(), name="empresa_lista"),
    path("empresas/nova/", views.CompanyCreateView.as_view(), name="empresa_nova"),
    path(
        "empresas/<int:pk>/editar/",
        views.CompanyUpdateView.as_view(),
        name="empresa_editar",
    ),
    path("unidades/", views.BusinessUnitListView.as_view(), name="unidade_lista"),
    path("unidades/nova/", views.BusinessUnitCreateView.as_view(), name="unidade_nova"),
    path(
        "unidades/<int:pk>/editar/",
        views.BusinessUnitUpdateView.as_view(),
        name="unidade_editar",
    ),
    path("safras/", views.SeasonListView.as_view(), name="safra_lista"),
    path("safras/nova/", views.SeasonCreateView.as_view(), name="safra_nova"),
    path(
        "safras/<int:pk>/editar/", views.SeasonUpdateView.as_view(), name="safra_editar"
    ),
    path(
        "safras/<int:pk>/tornar-corrente/",
        views.SeasonSetCurrentView.as_view(),
        name="safra_tornar_corrente",
    ),
    path(
        "safras/<int:pk>/encerrar/",
        views.SeasonCloseView.as_view(),
        name="safra_encerrar",
    ),
    path(
        "safras/<int:pk>/reabrir/",
        views.SeasonReopenView.as_view(),
        name="safra_reabrir",
    ),
    path(
        "contexto/trocar-safra/", views.TrocarSafraView.as_view(), name="trocar_safra"
    ),
]
