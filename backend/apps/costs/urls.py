from django.urls import path

from apps.costs import views

app_name = "costs"

urlpatterns = [
    path("", views.CostListView.as_view(), name="lista"),
    path("novo/", views.CostCreateView.as_view(), name="novo"),
    path("<int:pk>/", views.CostDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.CostUpdateView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.CostDeleteView.as_view(), name="excluir"),
    path("<int:pk>/restaurar/", views.CostRestoreView.as_view(), name="restaurar"),
    path("centros/", views.CostCenterListView.as_view(), name="centro_lista"),
    path("centros/novo/", views.CostCenterCreateView.as_view(), name="centro_novo"),
    path(
        "centros/<int:pk>/editar/",
        views.CostCenterUpdateView.as_view(),
        name="centro_editar",
    ),
]
