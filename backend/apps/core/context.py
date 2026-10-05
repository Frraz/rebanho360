"""Contexto fixo do topo: Empresa · Safra · Fazenda (docs/ux/01).

A seleção de safra e fazenda persiste na sessão. Empresa não tem seletor
real — a operação tem uma só —, mas o nome aparece na barra.
"""

from apps.core import request_context

SESSION_SEASON_ID = "ctx_season_id"
SESSION_FARM_ID = "ctx_farm_id"


def memoizado(chave, calcular):
    """Calcula uma vez por requisição. O processador de contexto, a view e o
    `Escopo` pedem a mesma empresa, safra e fazenda: eram 3 a 6 consultas
    repetidas em toda tela (e em todo fragmento do HTMX).

    Fora de uma requisição (tarefa Celery, comando, serviço chamado de teste) não
    há onde guardar: calcula sempre, como antes, sem risco de valor velho."""
    contexto = request_context.get_current()
    if contexto.request_id is None:
        return calcular()
    if chave not in contexto.memo:
        contexto.memo[chave] = calcular()
    return contexto.memo[chave]


def current_company():
    from apps.organizations.models import Company

    return memoizado(
        "company", lambda: Company.objects.filter(is_active=True).order_by("id").first()
    )


def available_seasons(company):
    from apps.organizations.models import Season

    if company is None:
        return Season.objects.none()
    # O mesmo QuerySet na requisição inteira: avaliado uma vez, reaproveitado
    # (cada `.filter()` por cima dele é outra consulta, como sempre).
    return memoizado(
        ("seasons", company.pk), lambda: Season.objects.filter(company=company)
    )


def current_season(request, company):
    season_id = request.session.get(SESSION_SEASON_ID)
    company_id = company.pk if company is not None else None

    def calcular():
        seasons = available_seasons(company)
        if season_id:
            season = seasons.filter(pk=season_id).first()
            if season:
                return season
        return seasons.filter(is_current=True).first()

    return memoizado(("season", company_id, season_id), calcular)


def set_current_season(request, season) -> None:
    request.session[SESSION_SEASON_ID] = season.pk if season else None


def available_farms(user):
    from apps.properties.models import Farm

    def montar():
        if user.has_broad_access:
            return Farm.objects.filter(is_active=True)
        return user.accessible_farms().filter(is_active=True)

    return memoizado(("farms", user.pk), montar)


def current_farm(request, user):
    farm_id = request.session.get(SESSION_FARM_ID)
    if not farm_id:
        return None  # None = "Todas"
    return memoizado(
        ("farm", user.pk, farm_id),
        lambda: available_farms(user).filter(pk=farm_id).first(),
    )  # `None` também vale: a fazenda da sessão pode ter saído do escopo


def set_current_farm(request, farm) -> None:
    request.session[SESSION_FARM_ID] = farm.pk if farm else None


def destino_seguro(request, padrao: str) -> str:
    """O `next` dos seletores do topo, só se for desta mesma aplicação: um
    endereço de outro site (`//outro.com`, `https://...`) vira o `padrao`."""
    from django.utils.http import url_has_allowed_host_and_scheme

    destino = request.POST.get("next") or ""
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return padrao
