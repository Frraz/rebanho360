"""F1-15: conciliação de transferências — numa operação saudável vem
vazio, e listaria o '-140' se ele fosse importado como está na
planilha (pendência #2) — ver
docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-15."""

import datetime

import pytest
from django.db import connection
from django.urls import reverse

from apps.herd import selectors, services
from apps.herd.models import MovementType

pytestmark = pytest.mark.django_db

DATA = datetime.date(2025, 9, 18)


class TestConciliacao:
    def test_vem_vazio_com_operacao_saudavel(
        self,
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
            quantity=140,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        services.registrar_movimento(
            type=MovementType.TRANSFERENCIA,
            date=DATA,
            quantity=140,
            usuario=gestor,
            origin_farm=baixao,
            origin_lot=lote_baixao,
            origin_category=categoria_desmamados,
            destination_farm=sao_francisco,
            destination_lot=lote_sao_francisco,
            destination_category=categoria_desmamados,
        )

        assert list(selectors.conciliar_transferencias()) == []

    def test_tela_mostra_mensagem_de_tudo_certo(self, client, gestor):
        client.force_login(gestor)
        response = client.get(reverse("herd:conciliacao_transferencias"))
        assert response.status_code == 200
        assert "Nenhuma pend" in response.content.decode("utf-8")

    @pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="O teste contorna o trigger de banco, só existente em Postgres.",
    )
    def test_listaria_o_140_se_fosse_importado_sem_contrapartida(
        self, baixao, lote_baixao, categoria_desmamados, season, gestor
    ):
        """Simula exatamente a pendência #2: uma saída de transferência
        importada sem a entrada correspondente — o cenário que o
        trigger da F1-06 impede pelos caminhos normais, mas que pode
        reaparecer se um futuro importador de histórico (Fase 2)
        gravar direto no banco, contornando o `registrar_movimento()`.
        Para simular, a trava de banco é suspensa só dentro desta
        transação de teste (DDL é transacional — não afeta outro teste)."""
        from apps.herd.models import HerdMovement
        from apps.livestock.models import AnimalCategory, Sex

        # A shape constraint exige origem e destino preenchidos e
        # distintos em pelo menos um campo — usa uma 2ª categoria só para
        # satisfazer essa forma; o que o teste quer provar é a ausência
        # da linha de entrada no razão, não a identidade da categoria.
        outra_categoria = AnimalCategory.objects.create(
            name="Categoria provisória do teste", sex=Sex.INDEFINIDO
        )
        movimento = HerdMovement.objects.create(
            code="MV-LEGADO-000140",
            date=DATA,
            type=MovementType.TRANSFERENCIA,
            season=season,
            quantity=140,
            origin_farm=baixao,
            origin_lot=lote_baixao,
            origin_category=categoria_desmamados,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=outra_categoria,
            created_by=gestor,
        )

        # A trava fica desligada só até o fim desta transação de teste —
        # o rollback automático do pytest-django a restaura, então não
        # precisa (e não pode: religar com evento pendente falha) ser
        # reativada manualmente aqui.
        with connection.cursor() as cur:
            cur.execute(
                "ALTER TABLE herd_herdledgerentry "
                "DISABLE TRIGGER herdledgerentry_soma_zero_trigger"
            )
            cur.execute(
                "INSERT INTO herd_herdledgerentry "
                "(movement_id, date, farm_id, lot_id, category_id, quantity, "
                "season_id, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now())",
                [
                    movimento.pk,
                    DATA,
                    baixao.pk,
                    lote_baixao.pk,
                    categoria_desmamados.pk,
                    -140,
                    season.pk,
                ],
            )
            # Sem a linha de entrada correspondente — exatamente o -140.

        pendencias = list(selectors.conciliar_transferencias())

        assert len(pendencias) == 1
        assert pendencias[0].pk == movimento.pk
        assert pendencias[0].soma == -140
