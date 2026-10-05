"""Cache de resultados: vale enquanto nada mudou, nunca por tempo, nunca para
quem não é o dono do resultado, e nunca atrapalha quando o Redis falha."""

import pytest
from django.core.cache import cache
from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import result_cache
from apps.organizations.models import Company

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def cache_ligado(settings):
    """Cache em memória: o Redis dos testes é o do desenvolvimento."""
    settings.CACHE_DE_RESULTADOS = True
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "r360-result-cache-tests",
        }
    }
    cache.clear()
    yield
    cache.clear()


class Contador:
    def __init__(self, valor="resultado"):
        self.chamadas = 0
        self.valor = valor

    def __call__(self):
        self.chamadas += 1
        return self.valor


def test_segunda_leitura_nao_recalcula():
    calcular = Contador({"a": [1, 2]})
    primeira = result_cache.obter("ns", (1, "x"), calcular)
    segunda = result_cache.obter("ns", (1, "x"), calcular)
    assert primeira == segunda == {"a": [1, 2]}
    assert calcular.chamadas == 1


def test_recorte_diferente_nao_compartilha():
    """Outro usuário, safra ou fazenda: outro resultado."""
    calcular = Contador()
    result_cache.obter("ns", (1, "safra-1"), calcular)
    result_cache.obter("ns", (2, "safra-1"), calcular)
    result_cache.obter("ns", (1, "safra-2"), calcular)
    result_cache.obter("outro", (1, "safra-1"), calcular)
    assert calcular.chamadas == 4


def test_avancar_a_epoca_invalida_tudo():
    calcular = Contador()
    result_cache.obter("ns", (1,), calcular)
    result_cache.avancar()
    result_cache.obter("ns", (1,), calcular)
    assert calcular.chamadas == 2


def test_recalcular_ignora_o_guardado_e_grava_o_novo():
    calcular = Contador("velho")
    result_cache.obter("ns", (1,), calcular)
    calcular.valor = "novo"
    assert result_cache.obter("ns", (1,), calcular, recalcular=True) == "novo"
    assert result_cache.obter("ns", (1,), calcular) == "novo"
    assert calcular.chamadas == 2


def test_nao_vale_por_tempo():
    """Sem prazo de validade: nenhuma chave de resultado é regra de tempo."""
    assert result_cache.PRAZO_DE_LIMPEZA >= 600  # só faxina de memória


def test_desligado_calcula_sempre(settings):
    settings.CACHE_DE_RESULTADOS = False
    calcular = Contador()
    result_cache.obter("ns", (1,), calcular)
    result_cache.obter("ns", (1,), calcular)
    assert calcular.chamadas == 2


def test_cache_fora_do_ar_nao_derruba_nem_muda_o_numero(monkeypatch):
    def quebra(*a, **k):
        raise ConnectionError("Redis fora do ar")

    for metodo in ("get", "set", "add", "incr"):
        monkeypatch.setattr(cache, metodo, quebra)
    calcular = Contador("certo")

    assert result_cache.obter("ns", (1,), calcular) == "certo"
    assert result_cache.obter("ns", (1,), calcular) == "certo"
    assert calcular.chamadas == 2
    result_cache.avancar()  # também não levanta


def test_gravacao_que_falha_devolve_o_resultado(monkeypatch):
    """Redis cheio (`noeviction`) recusa o SET: o usuário recebe o número igual."""
    result_cache.epoca()  # cria a época antes de quebrar a gravação
    original = cache.set

    def recusa(chave, *a, **k):
        if (
            chave.startswith(result_cache.PREFIXO)
            and chave != result_cache.CHAVE_DA_EPOCA
        ):
            raise OSError("OOM command not allowed")
        return original(chave, *a, **k)

    monkeypatch.setattr(cache, "set", recusa)
    assert result_cache.obter("ns", (1,), Contador("valor")) == "valor"


def test_valor_ilegivel_e_recalculado(monkeypatch):
    calcular = Contador("bom")
    result_cache.obter("ns", (1,), calcular)
    original = cache.get

    def lixo(chave, *a, **k):  # tudo o que não é a época volta corrompido
        return (
            original(chave, *a, **k)
            if chave == result_cache.CHAVE_DA_EPOCA
            else b"lixo"
        )

    monkeypatch.setattr(cache, "get", lixo)
    assert result_cache.obter("ns", (1,), calcular) == "bom"
    assert calcular.chamadas == 2


def test_epoca_perdida_nao_ressuscita_resultado_velho():
    """Se o Redis perde só a chave da época, a nova não repete a antiga."""
    primeira = result_cache.epoca()
    result_cache.obter("ns", (1,), Contador("velho"))
    cache.delete(result_cache.CHAVE_DA_EPOCA)
    assert result_cache.epoca() != primeira
    assert result_cache.obter("ns", (1,), Contador("novo")) == "novo"


class TestInvalidacaoPorEscrita:
    @pytest.fixture(autouse=True)
    def _sem_pendencias(self):
        """O teste inteiro roda numa transação que nunca confirma: o que as
        fixtures agendaram ficaria pendente e o agendamento único (que dispensa
        um segundo `avancar` na mesma transação) não registraria o do teste."""
        transaction.get_connection().run_on_commit.clear()

    def test_so_depois_do_commit(self, django_capture_on_commit_callbacks):
        antes = result_cache.epoca()
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            result_cache.avancar_ao_confirmar()
            assert result_cache.epoca() == antes  # ainda não: falta o commit
        assert len(callbacks) == 1
        callbacks[0]()
        assert result_cache.epoca() != antes

    def test_transacao_desfeita_nao_invalida(self, django_capture_on_commit_callbacks):
        antes = result_cache.epoca()
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    result_cache.avancar_ao_confirmar()
                    raise RuntimeError("desfaz")
        assert result_cache.epoca() == antes

    def test_transacao_grande_agenda_uma_vez(self, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            for _ in range(200):
                result_cache.avancar_ao_confirmar()
        assert len(callbacks) == 1

    def test_gravar_modelo_de_negocio_invalida(
        self, django_capture_on_commit_callbacks
    ):
        antes = result_cache.epoca()
        with django_capture_on_commit_callbacks(execute=True):
            Company.objects.create(name="Fazendas Reunidas")
        assert result_cache.epoca() != antes

    def test_acao_auditada_que_muda_dado_invalida(
        self, django_capture_on_commit_callbacks
    ):
        antes = result_cache.epoca()
        with django_capture_on_commit_callbacks(execute=True):
            registrar_auditoria(
                action=AuditAction.CONFIRM, entity_type="X", entity_id="1"
            )
        assert result_cache.epoca() != antes

    @pytest.mark.parametrize(
        "acao",
        [
            AuditAction.LOGIN,
            AuditAction.LOGIN_FAILED,
            AuditAction.LOGOUT,
            AuditAction.EXPORT,
            AuditAction.VIEW,
        ],
    )
    def test_entrar_e_consultar_nao_esvaziam_o_cache(
        self, django_capture_on_commit_callbacks, acao
    ):
        """Tentativas de login em sequência não podem apagar o cache de todos."""
        antes = result_cache.epoca()
        with django_capture_on_commit_callbacks(execute=True):
            registrar_auditoria(action=acao, entity_type="User", entity_id="1")
        assert result_cache.epoca() == antes


def test_versao_do_codigo_e_estavel_no_processo():
    assert result_cache.versao_do_codigo() == result_cache.versao_do_codigo()
    assert len(result_cache.versao_do_codigo()) == 16
