from django.urls import path

from apps.livestock import views

app_name = "livestock"

urlpatterns = [
    path("categorias/", views.AnimalCategoryListView.as_view(), name="categoria_lista"),
    path(
        "categorias/nova/",
        views.AnimalCategoryCreateView.as_view(),
        name="categoria_nova",
    ),
    path(
        "categorias/<int:pk>/editar/",
        views.AnimalCategoryUpdateView.as_view(),
        name="categoria_editar",
    ),
    path(
        "categorias/<int:pk>/sugestao-evolucao/",
        views.sugestao_evolucao,
        name="categoria_sugestao_evolucao",
    ),
    path("racas/", views.BreedListView.as_view(), name="raca_lista"),
    path("racas/nova/", views.BreedCreateView.as_view(), name="raca_nova"),
    path("racas/<int:pk>/editar/", views.BreedUpdateView.as_view(), name="raca_editar"),
    path("lotes/", views.LotListView.as_view(), name="lote_lista"),
    path("lotes/novo/", views.LotCreateView.as_view(), name="lote_novo"),
    path("lotes/<int:pk>/editar/", views.LotUpdateView.as_view(), name="lote_editar"),
    path("lotes/<int:pk>/", views.LotDetailView.as_view(), name="lote_detalhe"),
]
