from django.contrib import admin

from apps.properties.models import Farm, Paddock


@admin.register(Farm)
class FarmAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "state", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active", "state")
    autocomplete_fields = ["business_unit"]


@admin.register(Paddock)
class PaddockAdmin(admin.ModelAdmin):
    list_display = ("name", "farm", "type", "area_ha", "is_active")
    list_filter = ("type", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ["farm"]
