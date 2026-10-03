from django.urls import path

from apps.partners import views

app_name = "partners"

urlpatterns = [
    path("", views.PartnerListView.as_view(), name="lista"),
    path("buscar/", views.PartnerSearchView.as_view(), name="buscar"),
    path("novo/", views.PartnerCreateView.as_view(), name="novo"),
    path("<int:pk>/", views.PartnerDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.PartnerUpdateView.as_view(), name="editar"),
    path(
        "<int:partner_pk>/contas/nova/",
        views.BankAccountCreateView.as_view(),
        name="conta_nova",
    ),
    path(
        "contas/<int:pk>/editar/",
        views.BankAccountUpdateView.as_view(),
        name="conta_editar",
    ),
]
