from django.contrib import admin

from apps.costs.models import CostCenter, CostClass


@admin.register(CostClass)
class CostClassAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ["parent"]
