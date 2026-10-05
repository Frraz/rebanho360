"""Injeta o contexto fixo (Empresa · Safra · Fazenda) em todo template."""

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from apps.core import context as ctx

TEMAS = ("light", "dark")


def contexto_fixo(request):
    """Tudo preguiçoso: só consulta quem o template realmente usar. Fragmento do
    HTMX (troca de aba, polling de exportação a cada 2 s) não renderiza a barra
    do topo e deixa de pagar de 3 a 6 consultas por resposta."""
    if not request.user.is_authenticated:
        return {}

    company = SimpleLazyObject(ctx.current_company)
    season = SimpleLazyObject(
        lambda: ctx.current_season(request, ctx.current_company())
    )
    farm = SimpleLazyObject(lambda: ctx.current_farm(request, request.user))

    return {
        "current_company": company,
        "current_season": season,
        "available_seasons": SimpleLazyObject(
            lambda: ctx.available_seasons(ctx.current_company())
        ),
        "current_farm": farm,
        "available_farms": SimpleLazyObject(lambda: ctx.available_farms(request.user)),
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
