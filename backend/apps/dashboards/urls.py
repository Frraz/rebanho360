from django.urls import path

from apps.dashboards import views

app_name = "dashboards"

urlpatterns = [
    path("", views.InicioView.as_view(), name="inicio"),
]
