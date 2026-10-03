"""F5-07 — viagem, embarque e frete (previsto derivado × realizado digitado)."""

import datetime

import pytest

from apps.audit.models import AuditAction, AuditEvent
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.reversible import Status
from apps.procurement import trips
from apps.procurement.models import TripLoad
from apps.procurement.tests.conftest import DATA_RETIRADA, D

pytestmark = pytest.mark.django_db


@pytest.fixture
def nova_viagem(escritorio, compromisso, item, transportador):
    def _criar(**extra):
        dados = {
            "usuario": escritorio,
            "compromisso": compromisso,
            "pickup_date": DATA_RETIRADA,
            "carrier": transportador,
            "cargas": [
                {
                    "item": item,
                    "planned_qty": 10,
                    "shipped_qty": 10,
                    "origin_weight_kg": D("5000"),
                }
            ],
        }
        return trips.criar_viagem(**(dados | extra))

    return _criar


class TestCriar:
    def test_cria_viagem_confirmada_com_cargas(self, viagem):
        assert viagem.status == Status.CONFIRMADA
        assert viagem.code == "OP-000001/V1"  # o número da operação + a etapa
        assert viagem.loads.count() == 1
        assert viagem.distance_km == 100  # herdada do compromisso

    def test_audita_viagem_e_carga(self, viagem):
        assert AuditEvent.objects.filter(
            entity_type="Trip", action=AuditAction.CONFIRM
        ).exists()
        assert AuditEvent.objects.filter(
            entity_type="TripLoad", action=AuditAction.CREATE
        ).exists()

    def test_so_depois_de_aprovar_o_compromisso(self, criar_compromisso, nova_viagem):
        em_negociacao = criar_compromisso()
        with pytest.raises(BusinessError, match="depois da aprovação"):
            nova_viagem(
                compromisso=em_negociacao,
                cargas=[{"item": em_negociacao.items.get(), "planned_qty": 1}],
            )

    def test_transportador_precisa_do_papel(self, nova_viagem, produtor):
        with pytest.raises(BusinessError, match="Transportador"):
            nova_viagem(carrier=produtor)

    def test_data_da_retirada_e_obrigatoria(self, nova_viagem):
        with pytest.raises(BusinessError, match="data da retirada"):
            nova_viagem(pickup_date=None)

    def test_criterio_sem_tarifa_e_recusado(self, nova_viagem):
        with pytest.raises(BusinessError, match="tarifa"):
            nova_viagem(freight_criterion="POR_CABECA")

    def test_tarifa_sem_criterio_e_recusada(self, nova_viagem):
        with pytest.raises(BusinessError, match="critério"):
            nova_viagem(freight_rate=D("10"))

    def test_precisa_levar_algum_item(self, nova_viagem):
        with pytest.raises(BusinessError, match="pelo menos um item"):
            nova_viagem(cargas=[])

    def test_item_de_outro_compromisso_e_recusado(
        self, nova_viagem, criar_compromisso, gestor
    ):
        from apps.procurement import commitments

        outro = commitments.aprovar_compromisso(criar_compromisso(), usuario=gestor)
        with pytest.raises(BusinessError, match="não pertence"):
            nova_viagem(cargas=[{"item": outro.items.get(), "planned_qty": 5}])

    def test_item_repetido_e_recusado(self, nova_viagem, item):
        with pytest.raises(BusinessError, match="duas vezes"):
            nova_viagem(
                cargas=[
                    {"item": item, "planned_qty": 5},
                    {"item": item, "planned_qty": 5},
                ]
            )

    def test_carga_sem_cabecas_e_recusada(self, nova_viagem, item):
        with pytest.raises(BusinessError, match="programadas ou embarcadas"):
            nova_viagem(cargas=[{"item": item, "planned_qty": 0}])

    def test_campo_nao_lanca_viagem(self, campo_baixao, compromisso, item):
        with pytest.raises(BusinessError, match="permissão"):
            trips.criar_viagem(
                usuario=campo_baixao,
                compromisso=compromisso,
                pickup_date=DATA_RETIRADA,
                cargas=[{"item": item, "planned_qty": 1}],
            )

    def test_placa_vai_em_maiuscula(self, nova_viagem):
        assert nova_viagem(vehicle_plate="abc1d23").vehicle_plate == "ABC1D23"

    def test_um_compromisso_pode_ter_varias_viagens(self, nova_viagem):
        a, b = nova_viagem(), nova_viagem()
        assert (a.code, b.code) == ("OP-000001/V1", "OP-000001/V2")


class TestFretePrevisto:
    """Cada critério confere com conta feita à mão."""

    def test_por_cabeca(self, viagem):
        # 10 cabeças embarcadas × R$ 50,00
        assert trips.frete_previsto(viagem) == D("500.00")

    def test_por_cabeca_usa_o_programado_se_nao_embarcou(self, nova_viagem, item):
        viagem = nova_viagem(
            freight_criterion="POR_CABECA",
            freight_rate=D("50"),
            cargas=[{"item": item, "planned_qty": 8}],
        )
        assert trips.frete_previsto(viagem) == D("400.00")

    def test_por_km(self, nova_viagem):
        viagem = nova_viagem(freight_criterion="POR_KM", freight_rate=D("4.50"))
        assert trips.frete_previsto(viagem) == D("450.00")  # 100 km × 4,50

    def test_por_kg(self, nova_viagem):
        viagem = nova_viagem(freight_criterion="POR_KG", freight_rate=D("0.10"))
        assert trips.frete_previsto(viagem) == D("500.00")  # 5.000 kg × 0,10

    def test_por_viagem(self, nova_viagem):
        viagem = nova_viagem(freight_criterion="POR_VIAGEM", freight_rate=D("1800"))
        assert trips.frete_previsto(viagem) == D("1800.00")

    def test_sem_criterio_nao_ha_previsto(self, nova_viagem):
        assert trips.frete_previsto(nova_viagem()) is None

    def test_por_kg_sem_peso_de_origem_devolve_none_nao_zero(self, nova_viagem, item):
        viagem = nova_viagem(
            freight_criterion="POR_KG",
            freight_rate=D("0.10"),
            cargas=[{"item": item, "planned_qty": 10, "shipped_qty": 10}],
        )
        assert trips.frete_previsto(viagem) is None

    def test_por_km_sem_distancia_devolve_none(self, nova_viagem, compromisso):
        compromisso.distance_km = None
        compromisso.save()
        viagem = nova_viagem(
            freight_criterion="POR_KM", freight_rate=D("4.5"), distance_km=None
        )
        viagem.distance_km = None
        assert trips.frete_previsto(viagem) is None

    def test_arredonda_so_no_fim(self, nova_viagem, item):
        # 7 cabeças × 33,3333 = 233,3331 → 233,33
        viagem = nova_viagem(
            freight_criterion="POR_CABECA",
            freight_rate=D("33.3333"),
            cargas=[{"item": item, "planned_qty": 7}],
        )
        assert trips.frete_previsto(viagem) == D("233.33")


class TestFreteDaViagem:
    def test_realizado_vale_mais_que_o_previsto(self, viagem, escritorio):
        viagem = trips.editar_viagem(
            viagem,
            {"freight_actual": D("620")},
            None,
            usuario=escritorio,
            motivo="Nota do transportador",
        )
        frete = trips.frete_da_viagem(viagem)
        assert (frete.previsto, frete.realizado, frete.final, frete.origem) == (
            D("500.00"),
            D("620"),
            D("620"),
            "realizado",
        )

    def test_sem_realizado_usa_o_previsto_e_diz_qual(self, viagem):
        frete = trips.frete_da_viagem(viagem)
        assert frete.final == D("500.00") and frete.origem == "previsto"

    def test_sem_nada_nao_ha_frete(self, nova_viagem):
        frete = trips.frete_da_viagem(nova_viagem())
        assert frete.final is None and frete.origem is None


class TestEmbarcarAcimaDoCompromisso:
    def test_avisa_nao_bloqueia(self, nova_viagem, item):
        viagem = nova_viagem(
            cargas=[{"item": item, "planned_qty": 12, "shipped_qty": 12}]
        )
        avisos = trips.avisos_da_viagem(viagem)
        assert avisos and "12 cabeças embarcadas, acima das 10" in avisos[0]

    def test_soma_as_viagens_do_item(self, nova_viagem, item):
        nova_viagem()
        segunda = nova_viagem(
            cargas=[{"item": item, "planned_qty": 5, "shipped_qty": 5}]
        )
        assert "15 cabeças embarcadas" in trips.avisos_da_viagem(segunda)[0]

    def test_dentro_do_compromisso_nao_avisa(self, viagem):
        assert trips.avisos_da_viagem(viagem) == []


class TestEditarExcluir:
    def test_editar_exige_motivo(self, viagem, escritorio):
        with pytest.raises(BusinessError, match="Motivo"):
            trips.editar_viagem(
                viagem, {"driver_name": "José"}, None, usuario=escritorio, motivo=""
            )

    def test_corrigir_carga_audita_a_linha(self, viagem, escritorio, item):
        carga = viagem.loads.get()
        trips.editar_viagem(
            viagem,
            {},
            [
                {
                    "id": carga.pk,
                    "item": item,
                    "planned_qty": 10,
                    "shipped_qty": 9,
                    "origin_weight_kg": D("5000"),
                }
            ],
            usuario=escritorio,
            motivo="Contagem no embarque",
        )
        carga.refresh_from_db()
        assert carga.shipped_qty == 9
        evento = AuditEvent.objects.get(
            entity_type="TripLoad", action=AuditAction.UPDATE
        )
        assert evento.changed_fields == ["shipped_qty"]

    def test_carga_ja_recebida_nao_sai_da_viagem(
        self, viagem, recebimento, escritorio, categoria_vaca, compromisso
    ):
        from apps.procurement import commitments
        from apps.procurement.tests.conftest import dados_item

        commitments.editar_compromisso(
            compromisso,
            {},
            [
                {"id": viagem.loads.get().item.pk}
                | dados_item(viagem.loads.get().item.category),
                dados_item(categoria_vaca),
            ],
            usuario=escritorio,
            motivo="Mais um item",
        )
        outro = compromisso.items.get(number=2)
        with pytest.raises(BlockingDependencyError, match="já foi recebido"):
            trips.editar_viagem(
                viagem,
                {},
                [{"item": outro, "planned_qty": 3}],
                usuario=escritorio,
                motivo="Trocar carga",
            )

    def test_excluir_viagem_com_recebimento_pede_cascata(
        self, viagem, recebimento, gestor
    ):
        from apps.core.exceptions import DependencyError

        with pytest.raises(DependencyError):
            trips.excluir_viagem(viagem, usuario=gestor, motivo="Cancelada")

        trips.excluir_viagem(viagem, usuario=gestor, motivo="Cancelada", cascata=True)
        recebimento.refresh_from_db()
        assert recebimento.status == Status.EXCLUIDA

    def test_restaurar_viagem(self, viagem, gestor):
        excluida = trips.excluir_viagem(viagem, usuario=gestor, motivo="Engano")
        restaurada = trips.restaurar_viagem(excluida, usuario=gestor)
        assert restaurada.status == Status.CONFIRMADA

    def test_cargas_retiradas_nao_saem_do_banco(self, viagem, escritorio, item):
        carga = viagem.loads.get()
        trips.editar_viagem(
            viagem,
            {},
            [{"item": item, "planned_qty": 4}],
            usuario=escritorio,
            motivo="Refeita",
        )
        assert TripLoad.all_objects.get(pk=carga.pk).removed_at is not None
        assert viagem.loads.count() == 1

    def test_escritorio_nao_exclui(self, viagem, escritorio):
        with pytest.raises(BusinessError, match="permissão"):
            trips.excluir_viagem(viagem, usuario=escritorio, motivo="x")


class TestTrava:
    def test_acerto_aprovado_trava_nova_viagem(self, acerto_aprovado, nova_viagem):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            nova_viagem()

    def test_acerto_aprovado_trava_a_correcao_da_viagem(
        self, acerto_aprovado, viagem, escritorio
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            trips.editar_viagem(
                viagem, {"driver_name": "x"}, None, usuario=escritorio, motivo="x"
            )

    def test_acerto_aprovado_trava_a_exclusao_da_viagem(
        self, acerto_aprovado, viagem, gestor
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            trips.excluir_viagem(viagem, usuario=gestor, motivo="x", cascata=True)
        assert datetime.date  # nada mudou
