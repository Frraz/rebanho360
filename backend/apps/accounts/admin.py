from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts import selectors, two_factor
from apps.accounts.models import Role, User, UserFarmAccess


class UserFarmAccessInline(admin.TabularInline):
    model = UserFarmAccess
    extra = 1
    autocomplete_fields = ["farm"]


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Rebanho360",
            {
                "fields": (
                    "role",
                    "phone",
                    "last_login_ip",
                    "must_change_password",
                    "deleted_at",
                )
            },
        ),
    )
    list_display = (
        "username",
        "first_name",
        "last_name",
        "role",
        "is_active",
        "is_staff",
    )
    list_filter = DjangoUserAdmin.list_filter + ("role",)
    inlines = [UserFarmAccessInline]
    readonly_fields = ("last_login_ip", "deleted_at")
    actions = ["redefinir_segundo_fator"]

    def get_queryset(self, request):
        # O superusuário (suporte) não aparece para os demais, nem aqui.
        return selectors.usuarios_visiveis(request.user)

    @admin.action(description="Redefinir o segundo fator (perdeu celular e códigos)")
    def redefinir_segundo_fator(self, request, queryset):
        """Recuperação de quem perdeu o celular **e** os códigos. Só `ADMIN`,
        nunca em si mesmo (senão a ação é um atalho para fugir do 2FA), e com
        rastro na auditoria. No próximo login a pessoa configura de novo."""
        if request.user.role != Role.ADMIN:
            self.message_user(
                request,
                "Só o administrador redefine o segundo fator.",
                messages.ERROR,
            )
            return
        redefinidos = 0
        for usuario in queryset:
            if usuario.pk == request.user.pk:
                self.message_user(
                    request,
                    "Você não pode redefinir o seu próprio segundo fator: peça a "
                    "outro administrador.",
                    messages.WARNING,
                )
                continue
            two_factor.redefinir_segundo_fator(
                usuario, por=request.user, motivo="pelo painel de administração"
            )
            redefinidos += 1
        if redefinidos:
            self.message_user(
                request,
                f"Segundo fator redefinido para {redefinidos} usuário(s). Eles "
                "configuram de novo no próximo login.",
                messages.SUCCESS,
            )


@admin.register(UserFarmAccess)
class UserFarmAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "farm", "can_write", "created_at")
    list_filter = ("can_write",)
    search_fields = ("user__username", "farm__name")
    autocomplete_fields = ["user", "farm"]
