"""F1-12: editar, excluir e restaurar movimentação, usando os serviços
genéricos da F0-10 — ver docs/regras-negocio/06-edicao-exclusao-e-auditoria.md
e docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-12."""

import datetime

import pytest
from django.urls import reverse

from apps.herd import services
from apps.herd.models import MovementType

pytestmark = pytest.mark.django_db

DATA = datetime.date(2025, 9, 18)


@pytest.fixture
def movimento_de_compra(baixao, lote_baixao, categoria_desmamados, gestor):
    return services.registrar_movimento(
        type=MovementType.COMPRA,
        date=DATA,
        quantity=50,
        usuario=gestor,
        destination_farm=baixao,
        destination_lot=lote_baixao,
        destination_category=categoria_desmamados,
    )


class TestEditar:
    def test_escritorio_corrige_quantidade_pela_tela(
        self,
        client,
        movimento_de_compra,
        escritorio,
        baixao,
        lote_baixao,
        categoria_desmamados,
    ):
        client.force_login(escritorio)
        response = client.post(
            reverse("herd:movimento_editar", args=[movimento_de_compra.pk]),
            {
                "type": MovementType.COMPRA,
                "date": "2025-09-18",
                "quantity": 45,
                "destination_farm": baixao.pk,
                "destination_lot": lote_baixao.pk,
                "destination_category": categoria_desmamados.pk,
                "edit_reason": "Contagem corrigida no curral",
            },
        )
        assert response.status_code == 302
        movimento_de_compra.refresh_from_db()
        assert movimento_de_compra.quantity == 45
        assert movimento_de_compra.version == 2
        assert (
            services.saldo(farm=baixao, category=categoria_desmamados)["head_count"]
            == 45
        )

    def test_campo_nao_pode_editar_movimento_confirmado(
        self, client, movimento_de_compra, campo_baixao
    ):
        client.force_login(campo_baixao)
        response = client.get(
            reverse("herd:movimento_editar", args=[movimento_de_compra.pk])
        )
        assert response.status_code == 302  # redirecionado, sem acesso ao form

    def test_editar_sem_motivo_e_recusado(
        self,
        client,
        movimento_de_compra,
        escritorio,
        baixao,
        lote_baixao,
        categoria_desmamados,
    ):
        client.force_login(escritorio)
        response = client.post(
            reverse("herd:movimento_editar", args=[movimento_de_compra.pk]),
            {
                "type": MovementType.COMPRA,
                "date": "2025-09-18",
                "quantity": 45,
                "destination_farm": baixao.pk,
                "destination_lot": lote_baixao.pk,
                "destination_category": categoria_desmamados.pk,
                "edit_reason": "",
            },
        )
        assert response.status_code == 200
        movimento_de_compra.refresh_from_db()
        assert movimento_de_compra.quantity == 50  # não mudou


class TestExcluir:
    def test_gestor_exclui_com_motivo_e_desfaz_o_efeito(
        self, client, movimento_de_compra, gestor, baixao, categoria_desmamados
    ):
        client.force_login(gestor)
        response = client.post(
            reverse("herd:movimento_excluir", args=[movimento_de_compra.pk]),
            {"motivo": "Lançamento duplicado"},
        )
        assert response.status_code == 302
        movimento_de_compra.refresh_from_db()
        assert movimento_de_compra.status == "EXCLUIDA"
        assert (
            services.saldo(farm=baixao, category=categoria_desmamados)["head_count"]
            == 0
        )

    def test_escritorio_nao_pode_excluir_confirmado(
        self, client, movimento_de_compra, escritorio
    ):
        client.force_login(escritorio)
        client.post(
            reverse("herd:movimento_excluir", args=[movimento_de_compra.pk]),
            {"motivo": "Teste"},
        )
        movimento_de_compra.refresh_from_db()
        assert movimento_de_compra.status == "CONFIRMADA"  # nada aconteceu

    def test_excluir_que_deixaria_saldo_negativo_e_bloqueado(
        self,
        client,
        movimento_de_compra,
        gestor,
        baixao,
        lote_baixao,
        categoria_desmamados,
    ):
        # vende o que foi comprado — agora excluir a compra deixaria -50
        services.registrar_movimento(
            type=MovementType.VENDA,
            date=DATA,
            quantity=50,
            usuario=gestor,
            origin_farm=baixao,
            origin_lot=lote_baixao,
            origin_category=categoria_desmamados,
        )
        client.force_login(gestor)
        response = client.post(
            reverse("herd:movimento_excluir", args=[movimento_de_compra.pk]),
            {"motivo": "Tentativa de exclusão"},
        )
        assert response.status_code == 302
        movimento_de_compra.refresh_from_db()
        assert movimento_de_compra.status == "CONFIRMADA"  # bloqueado, nada mudou


class TestRestaurar:
    def test_gestor_restaura_e_reaplica_o_efeito(
        self, client, movimento_de_compra, gestor, baixao, categoria_desmamados
    ):
        from apps.core import reversible

        reversible.excluir(movimento_de_compra, usuario=gestor, motivo="teste")

        client.force_login(gestor)
        response = client.post(
            reverse("herd:movimento_restaurar", args=[movimento_de_compra.pk])
        )
        assert response.status_code == 302
        movimento_de_compra.refresh_from_db()
        assert movimento_de_compra.status == "CONFIRMADA"
        assert (
            services.saldo(farm=baixao, category=categoria_desmamados)["head_count"]
            == 50
        )


class TestTelaDeDetalhe:
    def test_detalhe_mostra_as_linhas_do_razao(
        self, client, movimento_de_compra, gestor
    ):
        client.force_login(gestor)
        response = client.get(
            reverse("herd:movimento_detalhe", args=[movimento_de_compra.pk])
        )
        assert response.status_code == 200
        assert movimento_de_compra.code.encode() in response.content

    def test_lista_mostra_editada_com_versao(
        self,
        client,
        movimento_de_compra,
        gestor,
        baixao,
        lote_baixao,
        categoria_desmamados,
    ):
        from apps.core import reversible

        reversible.editar(
            movimento_de_compra,
            {"quantity": 45},
            usuario=gestor,
            motivo="correção",
        )
        client.force_login(gestor)
        response = client.get(reverse("herd:movimento_lista"))
        assert b"Editada (v2)" in response.content
