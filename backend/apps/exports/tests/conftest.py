import io
import json
import zipfile
from decimal import Decimal

import pytest

from apps.accounts.models import Role, User, UserFarmAccess
from apps.exports import services as exportacao
from apps.exports import tasks
from apps.purchases import services as compras
from apps.sales.tests.conftest import *  # noqa: F401,F403
from apps.sales.tests.conftest import DATA_COMPRA

D = Decimal


@pytest.fixture(autouse=True)
def midia_temporaria(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def pedir(monkeypatch, django_capture_on_commit_callbacks):
    """Pede e **executa na hora**: no teste não há fila nem processador."""
    monkeypatch.setattr(tasks.executar, "delay", lambda pk: tasks.executar.run(pk))

    def _pedir(user, **pedido):
        with django_capture_on_commit_callbacks(execute=True):
            job = exportacao.solicitar_exportacao(user=user, **pedido)
        job.refresh_from_db()
        return job

    return _pedir


@pytest.fixture
def conteudo():
    """Os arquivos de uma exportação pronta, `{nome: bytes}`. Se ela não for ZIP,
    é o próprio arquivo, sob o nome `job.file_name`."""

    def _ler(job):
        assert job.status == "PRONTO", job.error
        with job.file.open("rb") as f:
            bruto = f.read()
        if job.content_type == "application/zip":
            with zipfile.ZipFile(io.BytesIO(bruto)) as z:
                return {n: z.read(n) for n in z.namelist()}
        return {job.file_name: bruto}

    return _ler


@pytest.fixture
def ler_json():
    return lambda bruto: json.loads(bruto.decode("utf-8"))


def _usuario(username, role, *fazendas):
    user = User.objects.create_user(username=username, password="x", role=role)
    for fazenda in fazendas:
        UserFarmAccess.objects.create(user=user, farm=fazenda, can_write=True)
    return user


@pytest.fixture
def escritorio_baixao(baixao):
    """Escritório com acesso só ao Baixão."""
    return _usuario("escritorio-bxo", Role.ESCRITORIO, baixao)


@pytest.fixture
def financeiro(baixao, sao_francisco):
    return _usuario("financeiro", Role.FINANCEIRO, baixao, sao_francisco)


@pytest.fixture
def consulta(baixao):
    return _usuario("consulta", Role.CONSULTA, baixao)


@pytest.fixture
def operacao(
    lote_de_compra,
    dados_abate,
    criar,
    confirmar,
    escritorio,
    baixao,
    categoria_25_36,
    vendedor,
    lote_baixao,
):
    """Duas fazendas com movimento: uma compra e um abate em São Francisco, e
    uma compra no Baixão. É o que permite provar que o escopo separa."""
    confirmar(criar(**dados_abate))
    compra_baixao = compras.criar_compra(
        usuario=escritorio,
        date=DATA_COMPRA,
        destination_farm=baixao,
        category=categoria_25_36,
        seller=vendedor,
        head_count=40,
        animal_value=D("90000.50"),
        freight_value=D("1000"),
    )
    compras.confirmar_compra(compra_baixao, usuario=escritorio)
    return {"lote_sfr": lote_de_compra, "lote_bxo": lote_baixao}
