"""Injeta o contexto fixo (Empresa · Safra · Fazenda) em todo template."""

from apps.core import context as ctx


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
