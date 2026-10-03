"""Contexto fixo do topo: Empresa · Safra · Fazenda (docs/ux/01).

A seleção de safra e fazenda persiste na sessão. Empresa não tem seletor
real — a operação tem uma só —, mas o nome aparece na barra.
"""

SESSION_SEASON_ID = "ctx_season_id"
SESSION_FARM_ID = "ctx_farm_id"


def current_company():
    from apps.organizations.models import Company

    return Company.objects.filter(is_active=True).order_by("id").first()


def available_seasons(company):
    from apps.organizations.models import Season

    if company is None:
        return Season.objects.none()
    return Season.objects.filter(company=company)


def current_season(request, company):
    seasons = available_seasons(company)
    season_id = request.session.get(SESSION_SEASON_ID)
    if season_id:
        season = seasons.filter(pk=season_id).first()
        if season:
            return season
    return seasons.filter(is_current=True).first()


def set_current_season(request, season) -> None:
    request.session[SESSION_SEASON_ID] = season.pk if season else None


def available_farms(user):
    from apps.properties.models import Farm

    if user.has_broad_access:
        return Farm.objects.filter(is_active=True)
    return user.accessible_farms().filter(is_active=True)


def current_farm(request, user):
    farm_id = request.session.get(SESSION_FARM_ID)
    if farm_id:
        farm = available_farms(user).filter(pk=farm_id).first()
        if farm:
            return farm
    return None  # None = "Todas"


def set_current_farm(request, farm) -> None:
    request.session[SESSION_FARM_ID] = farm.pk if farm else None
