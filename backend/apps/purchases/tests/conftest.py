import datetime
from decimal import Decimal

import pytest

from apps.costs.tests.conftest import *  # noqa: F401,F403
from apps.purchases import services

DATA_COMPRA = datetime.date(2025, 9, 18)


@pytest.fixture
def dados_compra(sao_francisco, categoria_desmamados, vendedor):
    """126 bezerros, como na compra de abril da planilha (R$ 388.080,00)."""
    return {
        "date": DATA_COMPRA,
        "seller": vendedor,
        "destination_farm": sao_francisco,
        "category": categoria_desmamados,
        "head_count": 126,
        "animal_value": Decimal("388080.00"),
    }


@pytest.fixture
def criar(escritorio):
    def _criar(**sobrescrever):
        return services.criar_compra(usuario=escritorio, **sobrescrever)

    return _criar
