"""F5-18 — o painel responde "o que falta fechar?" sem entrar em cada compromisso."""

import datetime

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User, UserFarmAccess
from apps.dashboards import selectors
from apps.procurement import closing, receivings, trips
from apps.procurement.tests.conftest import DATA_RECEBIMENTO, DATA_RETIRADA, D

pytestmark = pytest.mark.django_db
HOJE = datetime.date(2025, 9, 25)


def pendencias(user, **kw):
    kw.setdefault("hoje", HOJE)
    return {p.chave: p for p in selectors.pendencias_do_painel(user, **kw)}


class TestRecebidoSemAcerto:
    def test_gado_recebido_e_sem_acerto_avisa_que_ainda_esta_fora_do_saldo(
        self, gestor, compromisso, recebimento
    ):
        p = pendencias(gestor)["recebido_sem_acerto"]
        assert p.quantidade == 1
        assert "10 cabeças ainda fora do saldo do rebanho" in p.texto
        assert compromisso.code in p.exemplos[0]
        assert p.url.endswith("?situacao=CONFIRMADA")

    def test_nada_recebido_nao_e_pendencia(self, gestor, compromisso, viagem):
        assert "recebido_sem_acerto" not in pendencias(gestor)

    def test_com_acerto_aberto_deixa_de_ser_recebido_sem_acerto(self, gestor, acerto):
        assert "recebido_sem_acerto" not in pendencias(gestor)

    def test_acerto_aprovado_tambem_resolve(self, gestor, acerto_aprovado):
        chaves = pendencias(gestor)
        assert "recebido_sem_acerto" not in chaves
        assert "acerto_a_aprovar" not in chaves

    def test_campo_nao_ve(self, campo_baixao, compromisso, recebimento):
        assert "recebido_sem_acerto" not in pendencias(campo_baixao)

    def test_so_o_que_a_fazenda_do_usuario_alcanca(
        self, baixao, compromisso, recebimento
    ):
        de_outra = User.objects.create_user(
            username="o", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=de_outra, farm=baixao, can_write=True)
        assert "recebido_sem_acerto" not in pendencias(de_outra)


class TestAcertoAAprovar:
    def test_aparece_para_quem_aprova(self, gestor, acerto):
        p = pendencias(gestor)["acerto_a_aprovar"]
        assert p.quantidade == 1 and acerto.code in p.exemplos[0]

    def test_escritorio_nao_aprova_entao_nao_ve(self, escritorio, acerto):
        assert "acerto_a_aprovar" not in pendencias(escritorio)

    def test_some_depois_de_aprovado(self, gestor, acerto, aprovar):
        aprovar(acerto)
        assert "acerto_a_aprovar" not in pendencias(gestor)

    def test_volta_quando_o_acerto_e_reaberto(self, gestor, acerto_aprovado):
        closing.reabrir_acerto(acerto_aprovado, usuario=gestor, motivo="Corrigir")
        assert "acerto_a_aprovar" in pendencias(gestor)


class TestQuebraAcimaDoLimite:
    def _receber_com_peso(self, escritorio, compromisso, item, transportador, kg):
        v = trips.criar_viagem(
            usuario=escritorio,
            compromisso=compromisso,
            pickup_date=DATA_RETIRADA,
            carrier=transportador,
            cargas=[
                {
                    "item": item,
                    "planned_qty": 10,
                    "shipped_qty": 10,
                    "origin_weight_kg": D("5000"),
                }
            ],
        )
        return receivings.criar_recebimento(
            usuario=escritorio,
            viagem=v,
            date=DATA_RECEBIMENTO,
            linhas=[
                {"load": v.loads.get(), "received_qty": 10, "received_weight_kg": D(kg)}
            ],
        )

    def test_aparece_quando_passa_do_limite(
        self, gestor, escritorio, compromisso, item, transportador
    ):
        self._receber_com_peso(escritorio, compromisso, item, transportador, "4700")
        p = pendencias(gestor)["quebra_acima_do_limite"]
        assert p.quantidade == 1
        assert "6,00%" in p.exemplos[0] and "5.000 kg → 4.700 kg" in p.exemplos[0]

    def test_dentro_do_limite_nao_aparece(
        self, gestor, escritorio, compromisso, item, transportador
    ):
        self._receber_com_peso(escritorio, compromisso, item, transportador, "4900")
        assert "quebra_acima_do_limite" not in pendencias(gestor)

    def test_sem_peso_nao_inventa_pendencia(self, gestor, compromisso, recebimento):
        # o recebimento da fixture tem peso e 2%: dentro do limite
        assert "quebra_acima_do_limite" not in pendencias(gestor)


class TestNaTela:
    def test_painel_mostra_as_pendencias_do_ciclo(
        self, client, gestor, compromisso, recebimento
    ):
        client.force_login(gestor)
        html = client.get("/").content.decode()
        assert "compromisso com gado recebido e sem acerto" in html
        assert "ainda fora do saldo do rebanho" in html

    def test_painel_nao_quebra_sem_nada_do_ciclo(self, client, gestor):
        client.force_login(gestor)
        assert client.get("/").status_code == 200
        assert reverse("procurement:compromisso_lista")
