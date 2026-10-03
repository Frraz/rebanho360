"""Injeta o contexto fixo (Empresa · Safra · Fazenda) em todo template."""

from django.conf import settings

from apps.core import context as ctx

TEMAS = ("light", "dark")


def contexto_fixo(request):
    if not request.user.is_authenticated:
        return {}

    company = ctx.current_company()
    season = ctx.current_season(request, company)
    farm = ctx.current_farm(request, request.user)

    return {
        "current_company": company,
        "current_season": season,
        "available_seasons": ctx.available_seasons(company),
        "current_farm": farm,
        "available_farms": ctx.available_farms(request.user),
    }


def tema_da_interface(request):
    """Tema que o `<html data-theme>` usa. Logado, é o do usuário; sem login
    (tela de entrar), o último escolhido neste navegador; na dúvida, claro."""
    usuario = getattr(request, "user", None)
    if usuario is not None and usuario.is_authenticated:
        tema = usuario.theme
    else:
        tema = request.COOKIES.get(settings.THEME_COOKIE, "")
    return {"tema": tema if tema in TEMAS else "light"}
