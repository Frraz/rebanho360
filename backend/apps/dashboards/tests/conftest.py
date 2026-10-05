import pytest

from apps.sales.tests.conftest import *  # noqa: F401,F403


@pytest.fixture
def cenario(escritorio, sao_francisco, categoria_25_36, vendedor, frigorifico):
    return {
        "escritorio": escritorio,
        "sao_francisco": sao_francisco,
        "categoria_25_36": categoria_25_36,
        "vendedor": vendedor,
        "frigorifico": frigorifico,
    }
