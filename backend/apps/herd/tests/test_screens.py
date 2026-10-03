"""F1-10 (posição do rebanho) e F1-11 (lançamento de movimentação) — ver
docs/roadmap/fase-1-cadastros-e-rebanho.md."""

import datetime

import pytest
from django.urls import reverse

from apps.herd import services
from apps.herd.models import HerdMovement, MovementType

pytestmark = pytest.mark.django_db

DATA = datetime.date(2025, 9, 18)


class TestPosicaoDoRebanho:
    def test_posicao_nunca_mostra_numero_negativo(
        self, client, baixao, lote_baixao, categoria_desmamados, gestor
    ):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=50,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        services.registrar_movimento(
            type=MovementType.MORTE,
            date=DATA,
            quantity=3,
            usuario=gestor,
            origin_farm=baixao,
            origin_lot=lote_baixao,
            origin_category=categoria_desmamados,
            reason="causa desconhecida",
        )

        client.force_login(gestor)
        response = client.get(
            reverse("herd:posicao"), {"farm": baixao.pk, "until": "2025-12-31"}
        )

        assert response.status_code == 200
        for linha in response.context["linhas"]:
            assert linha["posicao"] >= 0
        assert response.context["total"]["posicao"] == 47

    def test_consolidado_soma_todas_as_fazendas_acessiveis(
        self,
        client,
        baixao,
        sao_francisco,
        lote_baixao,
        lote_sao_francisco,
        categoria_desmamados,
        gestor,
    ):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=50,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=30,
            usuario=gestor,
            destination_farm=sao_francisco,
            destination_lot=lote_sao_francisco,
            destination_category=categoria_desmamados,
        )

        client.force_login(gestor)
        response = client.get(reverse("herd:posicao"), {"until": "2025-12-31"})

        assert response.context["total"]["posicao"] == 80

    def test_posicao_e_escopada_por_usuario(
        self,
        client,
        baixao,
        sao_francisco,
        lote_baixao,
        lote_sao_francisco,
        categoria_desmamados,
        campo_baixao,
        gestor,
    ):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=50,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=30,
            usuario=gestor,
            destination_farm=sao_francisco,
            destination_lot=lote_sao_francisco,
            destination_category=categoria_desmamados,
        )

        client.force_login(campo_baixao)
        response = client.get(reverse("herd:posicao"), {"until": "2025-12-31"})

        assert response.context["total"]["posicao"] == 50  # só vê o Baixão


class TestTelaDeLancamento:
    def test_campo_lanca_morte_pela_tela(
        self, client, baixao, lote_baixao, categoria_desmamados, campo_baixao
    ):
        client.force_login(campo_baixao)
        response = client.post(
            reverse("herd:lancar_movimento"),
            {
                "type": MovementType.COMPRA,
                "date": "2025-09-18",
                "quantity": 10,
                "destination_farm": baixao.pk,
                "destination_lot": lote_baixao.pk,
                "destination_category": categoria_desmamados.pk,
            },
        )
        assert response.status_code == 302
        assert HerdMovement.objects.filter(type=MovementType.COMPRA).exists()

    def test_morte_sem_motivo_reapresenta_o_formulario_com_erro(
        self, client, baixao, lote_baixao, categoria_desmamados, campo_baixao
    ):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=10,
            usuario=campo_baixao,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        client.force_login(campo_baixao)
        response = client.post(
            reverse("herd:lancar_movimento"),
            {
                "type": MovementType.MORTE,
                "date": "2025-09-18",
                "quantity": 1,
                "origin_farm": baixao.pk,
                "origin_lot": lote_baixao.pk,
                "origin_category": categoria_desmamados.pk,
            },
        )
        assert response.status_code == 200
        assert not HerdMovement.objects.filter(type=MovementType.MORTE).exists()

    def test_consulta_nao_pode_lancar_movimento(self, client):
        from apps.accounts.models import Role, User

        consulta = User.objects.create_user(
            username="consulta", password="x", role=Role.CONSULTA
        )
        client.force_login(consulta)
        response = client.get(reverse("herd:lancar_movimento"))
        assert response.status_code == 403

    def test_fragmento_de_lotes_da_fazenda_devolve_so_os_da_fazenda_escolhida(
        self, client, baixao, sao_francisco, lote_baixao, lote_sao_francisco, gestor
    ):
        client.force_login(gestor)
        response = client.get(
            reverse("herd:lotes_da_fazenda"),
            {"origin_farm": baixao.pk, "campo": "origin_lot"},
        )
        conteudo = response.content.decode("utf-8")
        assert "LT-BXO-001" in conteudo
        assert "LT-SFR-001" not in conteudo
