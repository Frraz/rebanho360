"""Raiz dos testes.

O cache de resultados (apps/core/result_cache.py) fica desligado em toda a
suíte: o Redis dos testes é o mesmo do desenvolvimento e sobrevive entre
execuções, e id de banco recriado repete chave. Os testes do próprio cache o
ligam, com um cache em memória."""

import pytest


@pytest.fixture(autouse=True)
def _sem_cache_de_resultados(settings):
    settings.CACHE_DE_RESULTADOS = False
