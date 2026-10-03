from django.urls import path

from apps.sales import views

app_name = "sales"

urlpatterns = [
    path("", views.SaleListView.as_view(), name="lista"),
    path("nova/", views.SaleCreateView.as_view(), name="nova"),
    path("previa/", views.previa_indicadores, name="previa"),
    path("<int:pk>/", views.SaleDetailView.as_view(), name="detalhe"),
    path("<int:pk>/confirmar/", views.SaleConfirmView.as_view(), name="confirmar"),
    path("<int:pk>/editar/", views.SaleUpdateView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.SaleDeleteView.as_view(), name="excluir"),
    path("<int:pk>/restaurar/", views.SaleRestoreView.as_view(), name="restaurar"),
]
