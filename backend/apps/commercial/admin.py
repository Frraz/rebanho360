from django.contrib import admin

from apps.commercial.models import CarcassClass, CommissionRule, TaxType


@admin.register(CarcassClass)
class CarcassClassAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "default_band", "is_active")
    search_fields = ("name", "code")


@admin.register(TaxType)
class TaxTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "nature", "is_active")
    search_fields = ("name",)


@admin.register(CommissionRule)
class CommissionRuleAdmin(admin.ModelAdmin):
    list_display = ("__str__", "base", "valid_from", "valid_to", "is_active")
    raw_id_fields = ["commissioned"]
