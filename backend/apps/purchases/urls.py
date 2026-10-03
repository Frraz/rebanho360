from django.urls import path

from apps.purchases import views

app_name = "purchases"

urlpatterns = [
    path("", views.PurchaseListView.as_view(), name="lista"),
    path("nova/", views.PurchaseCreateView.as_view(), name="nova"),
    path("previa-custo/", views.previa_custo, name="previa_custo"),
    path("<int:pk>/", views.PurchaseDetailView.as_view(), name="detalhe"),
    path("<int:pk>/confirmar/", views.PurchaseConfirmView.as_view(), name="confirmar"),
    path("<int:pk>/editar/", views.PurchaseUpdateView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.PurchaseDeleteView.as_view(), name="excluir"),
    path("<int:pk>/restaurar/", views.PurchaseRestoreView.as_view(), name="restaurar"),
]
