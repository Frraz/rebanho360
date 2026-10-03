"""Rate limit de login. Ver docs/seguranca/01-seguranca.md#autenticação."""

from django.core.cache import cache

RATE_LIMIT_WINDOW_SECONDS = 15 * 60
RATE_LIMIT_MAX_ATTEMPTS = 5


def _key(scope: str, value: str) -> str:
    return f"login_attempts:{scope}:{value}"


def is_rate_limited(*, username: str, ip_address: str | None) -> bool:
    if cache.get(_key("user", username), 0) >= RATE_LIMIT_MAX_ATTEMPTS:
        return True
    if ip_address and cache.get(_key("ip", ip_address), 0) >= RATE_LIMIT_MAX_ATTEMPTS:
        return True
    return False


def registrar_tentativa_falha(*, username: str, ip_address: str | None) -> None:
    keys = [_key("user", username)]
    if ip_address:
        keys.append(_key("ip", ip_address))
    for key in keys:
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, RATE_LIMIT_WINDOW_SECONDS)


def limpar_tentativas(*, username: str, ip_address: str | None) -> None:
    cache.delete(_key("user", username))
    if ip_address:
        cache.delete(_key("ip", ip_address))
