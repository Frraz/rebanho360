from django.contrib import admin

from apps.livestock.models import AnimalCategory, Breed


@admin.register(AnimalCategory)
class AnimalCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "sex", "age_order", "display_order", "is_active")
    list_filter = ("sex", "is_active")
    search_fields = ("name",)


@admin.register(Breed)
class BreedAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)
