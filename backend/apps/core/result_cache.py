"""Cache de resultados caros (dashboard e Início), com invalidação por escrita.

**Nunca por tempo.** O resultado vale enquanto nada mudou: há uma *época*
global, um número no Redis que sobe a cada escrita de dado de negócio
(`apps/core/signals.py` e a auditoria, `apps/audit/services.py`), sempre depois
do commit. A época entra na chave — subir a época deixa todo resultado antigo
inalcançável, sem apagar nada.

O que mais entra na chave, para um resultado nunca servir a quem não é dele nem
sobreviver a uma mudança de código:

- a *versão do código* (impressão digital dos arquivos .py e .html): um deploy
  invalida sozinho, mesmo com o Redis intacto;
- quem pede, e o recorte (quem, safra, fazenda, dia). O dia entra porque o
  recorte vai "até hoje".

**Falha aberta.** Redis fora do ar, cheio ou lento: o resultado é calculado
como se o cache não existisse. Cache nunca é motivo de erro nem de número
velho. O Redis é compartilhado com a fila do Celery (`noeviction`): por isso o
valor vai comprimido e com um prazo de *limpeza* curto — não é regra de
validade, só impede os resultados de épocas passadas de ficarem ocupando
memória.

Escritas que não passam por modelo nem auditoria (comando de seed, SQL
manual) não invalidam: use `python manage.py limpar_cache_de_resultados`, ou
"Recalcular" na própria aba do dashboard.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import time
import zlib
from functools import cache as memoizar_no_processo
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

log = logging.getLogger(__name__)

CHAVE_DA_EPOCA = "r360:resultados:epoca"
PREFIXO = "r360:resultados:"
#: Faxina, não validade (ver o texto do módulo): o que passar disso já é de uma
#: época que ninguém mais lê.
PRAZO_DE_LIMPEZA = 3600


def habilitado() -> bool:
    return bool(getattr(settings, "CACHE_DE_RESULTADOS", True))


@memoizar_no_processo
def versao_do_codigo() -> str:
    """Impressão digital do código que produz os resultados: caminho, tamanho e
    data de cada .py e .html de `apps/` e `templates/`. Mesma imagem, mesmo valor
    em todos os workers; qualquer mudança (deploy, edição em dev) muda a chave."""
    raiz = Path(settings.BASE_DIR)
    resumo = hashlib.sha1(usedforsecurity=False)
    for pasta in ("apps", "templates"):
        for caminho in sorted((raiz / pasta).rglob("*")):
            if caminho.suffix in (".py", ".html"):
                try:
                    info = caminho.stat()
                except OSError:
                    continue
                resumo.update(
                    f"{caminho.relative_to(raiz)}|{info.st_size}|{info.st_mtime_ns}".encode()
                )
    return resumo.hexdigest()[:16]


def epoca() -> int | None:
    """A época atual; `None` se o Redis não responde (e então não há cache)."""
    try:
        valor = cache.get(CHAVE_DA_EPOCA)
        if valor is None:
            # Valor inicial único: se o Redis perder só esta chave, a nova época
            # não repete uma antiga e ressuscita resultado velho.
            cache.add(CHAVE_DA_EPOCA, time.time_ns(), timeout=None)
            valor = cache.get(CHAVE_DA_EPOCA)
        return valor
    except Exception:  # noqa: BLE001 — falha aberta, qualquer que seja o motivo
        log.warning("cache de resultados: época indisponível", exc_info=True)
        return None


def avancar() -> None:
    """Invalida tudo: a próxima leitura recalcula."""
    if not habilitado():
        return
    try:
        cache.incr(CHAVE_DA_EPOCA)
    except ValueError:  # a chave não existe (ainda ou mais): recria com valor único
        try:
            cache.set(CHAVE_DA_EPOCA, time.time_ns(), timeout=None)
        except Exception:  # noqa: BLE001
            log.warning(
                "cache de resultados: não consegui avançar a época", exc_info=True
            )
    except Exception:  # noqa: BLE001
        log.warning("cache de resultados: não consegui avançar a época", exc_info=True)


def avancar_ao_confirmar() -> None:
    """Agenda `avancar()` para depois do commit da transação em curso (se for
    desfeita, nada mudou e nada se invalida). Dentro de uma transação grande
    (importação de milhares de linhas) agenda uma vez só."""
    if not habilitado():
        return
    conexao = transaction.get_connection()
    if conexao.in_atomic_block and any(
        entrada[1] is avancar for entrada in conexao.run_on_commit
    ):
        return
    transaction.on_commit(avancar)


def _chave(namespace: str, partes: tuple, ep: int) -> str:
    bruto = repr((versao_do_codigo(), ep, namespace, partes))
    return PREFIXO + hashlib.sha1(bruto.encode(), usedforsecurity=False).hexdigest()


def obter(namespace: str, partes: tuple, calcular, *, recalcular: bool = False):
    """O resultado de `calcular()` guardado para este recorte, se nada mudou
    desde que foi calculado. `partes` identifica o recorte (usuário, safra,
    fazenda, dia...) e **precisa** ter tudo o que muda o resultado: o que ficar
    de fora é compartilhado entre quem não deveria.

    `recalcular=True` ignora o que há guardado (botão "Recalcular") e grava o
    novo."""
    if not habilitado():
        return calcular()
    ep = epoca()
    if ep is None:
        return calcular()
    chave = _chave(namespace, partes, ep)
    if not recalcular:
        try:
            guardado = cache.get(chave)
            if guardado is not None:
                return pickle.loads(zlib.decompress(guardado))
        except Exception:  # noqa: BLE001 — valor ilegível = como se não houvesse
            log.warning("cache de resultados: leitura falhou", exc_info=True)
    valor = calcular()
    try:
        cache.set(
            chave,
            zlib.compress(pickle.dumps(valor, pickle.HIGHEST_PROTOCOL), 3),
            timeout=PRAZO_DE_LIMPEZA,
        )
    except Exception:  # noqa: BLE001 — Redis cheio ou fora do ar: segue sem cache
        log.warning("cache de resultados: gravação falhou", exc_info=True)
    return valor


__all__ = ["avancar", "avancar_ao_confirmar", "epoca", "habilitado", "obter"]
