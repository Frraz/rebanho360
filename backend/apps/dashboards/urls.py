from django.urls import path

from apps.dashboards import views

app_name = "dashboards"

urlpatterns = [
    path("", views.InicioView.as_view(), name="inicio"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("dashboard/<slug:aba>/", views.DashboardView.as_view(), name="dashboard_aba"),
]
