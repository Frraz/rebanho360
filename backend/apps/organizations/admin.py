from django.contrib import admin

from apps.organizations.models import BusinessUnit, Company, Season


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "tax_id", "is_active")
    search_fields = ("name", "tax_id")


@admin.register(BusinessUnit)
class BusinessUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "company", "is_active")
    search_fields = ("name", "code")
    autocomplete_fields = ["company"]


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "start_date", "end_date", "status", "is_current")
    list_filter = ("status", "is_current")
    search_fields = ("name",)
    autocomplete_fields = ["company"]
