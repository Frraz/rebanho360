"""F1-14: Pesagem não altera saldo do rebanho, e o peso médio é
calculado, nunca digitado — ver
docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-14."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.herd import services
from apps.herd.models import MovementType, Weighing, WeighingReason

pytestmark = pytest.mark.django_db

DATA = datetime.date(2025, 9, 18)


class TestPesagemNaoAlteraSaldo:
    def test_registrar_pesagem_nao_muda_o_saldo_do_lote(
        self, baixao, lote_baixao, categoria_desmamados, gestor
    ):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=133,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        saldo_antes = services.saldo(lot=lote_baixao)["head_count"]

        services.registrar_pesagem(
            date=DATA,
            farm=baixao,
            lot=lote_baixao,
            reason=WeighingReason.CONFERENCIA,
            head_count=133,
            total_weight_kg=Decimal("27664.000"),
            usuario=gestor,
        )

        assert services.saldo(lot=lote_baixao)["head_count"] == saldo_antes

    def test_peso_medio_e_calculado_nao_digitado(self, baixao, lote_baixao, gestor):
        pesagem = services.registrar_pesagem(
            date=DATA,
            farm=baixao,
            lot=lote_baixao,
            reason=WeighingReason.CONFERENCIA,
            head_count=133,
            total_weight_kg=Decimal("27664.000"),
            usuario=gestor,
        )
        assert not hasattr(Weighing, "average_weight_kg_field")
        assert pesagem.average_weight_kg == Decimal("27664.000") / 133

    def test_pesagem_com_data_futura_e_bloqueada(self, baixao, lote_baixao, gestor):
        futuro = datetime.date.today() + datetime.timedelta(days=1)
        from apps.core.exceptions import BusinessError

        with pytest.raises(BusinessError, match="futura"):
            services.registrar_pesagem(
                date=futuro,
                farm=baixao,
                lot=lote_baixao,
                reason=WeighingReason.CONFERENCIA,
                head_count=10,
                total_weight_kg=Decimal("2000"),
                usuario=gestor,
            )


class TestGmd:
    def test_gmd_precisa_de_duas_pesagens(self, baixao, lote_baixao, gestor):
        assert services.calcular_gmd(lote_baixao) is None

        services.registrar_pesagem(
            date=DATA,
            farm=baixao,
            lot=lote_baixao,
            reason=WeighingReason.CONFERENCIA,
            head_count=10,
            total_weight_kg=Decimal("2000"),
            usuario=gestor,
        )
        assert services.calcular_gmd(lote_baixao) is None

    def test_gmd_calculado_entre_duas_pesagens(self, baixao, lote_baixao, gestor):
        services.registrar_pesagem(
            date=datetime.date(2025, 9, 1),
            farm=baixao,
            lot=lote_baixao,
            reason=WeighingReason.CONFERENCIA,
            head_count=10,
            total_weight_kg=Decimal("2000"),  # média 200kg
            usuario=gestor,
        )
        services.registrar_pesagem(
            date=datetime.date(2025, 9, 11),
            farm=baixao,
            lot=lote_baixao,
            reason=WeighingReason.CONFERENCIA,
            head_count=10,
            total_weight_kg=Decimal("2074"),  # média 207.4kg, 10 dias depois
            usuario=gestor,
        )
        gmd = services.calcular_gmd(lote_baixao)
        assert gmd == Decimal("0.74")


class TestTelaDePesagem:
    def test_lista_de_pesagens_e_escopada_por_usuario(
        self,
        client,
        baixao,
        sao_francisco,
        lote_baixao,
        lote_sao_francisco,
        campo_baixao,
        gestor,
    ):
        services.registrar_pesagem(
            date=DATA,
            farm=baixao,
            lot=lote_baixao,
            reason=WeighingReason.CONFERENCIA,
            head_count=10,
            total_weight_kg=Decimal("2000"),
            usuario=gestor,
        )
        services.registrar_pesagem(
            date=DATA,
            farm=sao_francisco,
            lot=lote_sao_francisco,
            reason=WeighingReason.CONFERENCIA,
            head_count=5,
            total_weight_kg=Decimal("1000"),
            usuario=gestor,
        )

        client.force_login(campo_baixao)
        response = client.get(reverse("herd:pesagem_lista"))

        assert response.status_code == 200
        conteudo = response.content.decode("utf-8")
        assert "LT-BXO-001" in conteudo
        assert "LT-SFR-001" not in conteudo

    def test_campo_registra_pesagem_pela_tela(
        self, client, baixao, lote_baixao, campo_baixao
    ):
        client.force_login(campo_baixao)
        response = client.post(
            reverse("herd:pesagem_nova"),
            {
                "date": "2025-09-18",
                "farm": baixao.pk,
                "lot": lote_baixao.pk,
                "reason": WeighingReason.CONFERENCIA,
                "head_count": 50,
                "total_weight_kg": "10000",
            },
        )
        assert response.status_code == 302
        assert Weighing.objects.filter(lot=lote_baixao).exists()
