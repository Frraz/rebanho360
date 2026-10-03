from django.urls import path

from apps.commercial import views

app_name = "commercial"

urlpatterns = [
    path("classes/", views.CarcassClassListView.as_view(), name="classe_lista"),
    path("classes/nova/", views.CarcassClassCreateView.as_view(), name="classe_nova"),
    path(
        "classes/<int:pk>/editar/",
        views.CarcassClassUpdateView.as_view(),
        name="classe_editar",
    ),
    path("tributos/", views.TaxTypeListView.as_view(), name="tributo_lista"),
    path("tributos/novo/", views.TaxTypeCreateView.as_view(), name="tributo_novo"),
    path(
        "tributos/<int:pk>/editar/",
        views.TaxTypeUpdateView.as_view(),
        name="tributo_editar",
    ),
    path("comissoes/", views.CommissionRuleListView.as_view(), name="comissao_lista"),
    path(
        "comissoes/nova/",
        views.CommissionRuleCreateView.as_view(),
        name="comissao_nova",
    ),
    path(
        "comissoes/<int:pk>/editar/",
        views.CommissionRuleUpdateView.as_view(),
        name="comissao_editar",
    ),
]
