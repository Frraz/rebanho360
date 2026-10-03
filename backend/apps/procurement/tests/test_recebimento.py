"""F5-08 — recebimento e quebra de viagem."""

import datetime

import pytest

from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.reversible import Status
from apps.procurement import receivings
from apps.procurement.models import Receiving
from apps.procurement.tests.conftest import DATA_RECEBIMENTO, DATA_RETIRADA, D

pytestmark = pytest.mark.django_db


@pytest.fixture
def receber(escritorio, viagem):
    def _receber(**extra):
        carga = viagem.loads.get()
        dados = {
            "usuario": escritorio,
            "viagem": viagem,
            "date": DATA_RECEBIMENTO,
            "linhas": [
                {"load": carga, "received_qty": 10, "received_weight_kg": D("4900")}
            ],
        }
        return receivings.criar_recebimento(**(dados | extra))

    return _receber


class TestCriar:
    def test_cria_recebimento_confirmado(self, recebimento):
        assert recebimento.status == Status.CONFIRMADA
        assert recebimento.code == "OP-000001/R1"
        assert receivings.cabecas_recebidas(recebimento) == 10

    def test_recebimento_nao_escreve_no_razao(self, recebimento):
        """Pendência #24: o gado só entra no saldo com o acerto aprovado."""
        from apps.herd.models import HerdLedgerEntry

        assert not HerdLedgerEntry.objects.exists()

    def test_uma_viagem_tem_um_recebimento(self, recebimento, receber):
        with pytest.raises(BusinessError, match="já tem recebimento"):
            receber()

    def test_viagem_excluida_nao_recebe(self, viagem, receber, gestor):
        from apps.procurement import trips

        trips.excluir_viagem(viagem, usuario=gestor, motivo="Cancelada")
        viagem.refresh_from_db()
        with pytest.raises(BusinessError, match="excluída"):
            receber()

    def test_antes_da_retirada_e_recusado(self, receber):
        with pytest.raises(BusinessError, match="antes da retirada"):
            receber(date=DATA_RETIRADA - datetime.timedelta(days=1))

    def test_data_futura_e_recusada(self, receber):
        with pytest.raises(BusinessError, match="futura"):
            receber(date=datetime.date.today() + datetime.timedelta(days=1))

    def test_precisa_de_pelo_menos_uma_linha(self, receber):
        with pytest.raises(BusinessError, match="pelo menos uma linha"):
            receber(linhas=[])

    def test_carga_de_outra_viagem_e_recusada(
        self, escritorio, viagem, receber, item, compromisso
    ):
        from apps.procurement import trips

        outra = trips.criar_viagem(
            usuario=escritorio,
            compromisso=compromisso,
            pickup_date=DATA_RETIRADA,
            cargas=[{"item": item, "planned_qty": 3}],
        )
        with pytest.raises(BusinessError, match="não pertence"):
            receber(linhas=[{"load": outra.loads.get(), "received_qty": 3}])

    def test_peso_zero_e_recusado(self, receber, viagem):
        with pytest.raises(BusinessError, match="maior que zero"):
            receber(
                linhas=[
                    {
                        "load": viagem.loads.get(),
                        "received_qty": 5,
                        "received_weight_kg": D("0"),
                    }
                ]
            )

    def test_categoria_recebida_inativa_e_recusada(
        self, receber, viagem, categoria_13_24
    ):
        categoria_13_24.is_active = False
        categoria_13_24.save()
        with pytest.raises(BusinessError, match="inativa"):
            receber(
                linhas=[
                    {
                        "load": viagem.loads.get(),
                        "received_qty": 5,
                        "received_category": categoria_13_24,
                    }
                ]
            )

    def test_campo_nao_lanca(self, campo_baixao, viagem):
        with pytest.raises(BusinessError, match="permissão"):
            receivings.criar_recebimento(
                usuario=campo_baixao,
                viagem=viagem,
                date=DATA_RECEBIMENTO,
                linhas=[{"load": viagem.loads.get(), "received_qty": 1}],
            )

    def test_so_um_recebimento_por_viagem_no_banco(self, recebimento, viagem):
        """A garantia real é a constraint, não só o serviço."""
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            Receiving.objects.create(
                code="RB-X",
                trip=viagem,
                date=DATA_RECEBIMENTO,
                status=Status.CONFIRMADA,
                created_by=recebimento.created_by,
            )


class TestQuebraDeViagem:
    """Cliente, 2026-10-03 (#23): a quebra é **digitada**. O sistema não a
    calcula, não alerta e não desconta nada do valor dos animais."""

    def test_quebra_e_a_que_o_usuario_digitou(self, receber):
        recebimento = receber(trip_loss_percent=D("2.5"))
        quebra = receivings.quebra_da_viagem(recebimento)
        assert quebra.quebra_percentual == D("2.5")

    def test_nao_calcula_a_quebra_dos_pesos(self, recebimento):
        # saiu 5.000 kg, chegou 4.900: os pesos aparecem lado a lado, mas o
        # percentual não é inventado
        quebra = receivings.quebra_da_viagem(recebimento)
        assert quebra.peso_origem_kg == D("5000")
        assert quebra.peso_recebido_kg == D("4900")
        assert quebra.diferenca_de_peso_kg == D("100")
        assert quebra.quebra_percentual is None
        assert recebimento.trip_loss_percent is None

    def test_nao_ha_alerta_percentual(self, receber):
        recebimento = receber(trip_loss_percent=D("40"))
        quebra = receivings.quebra_da_viagem(recebimento)
        assert not hasattr(quebra, "acima_do_limite")

    def test_quebra_fora_de_0_a_100_e_recusada(self, receber):
        with pytest.raises(BusinessError, match="entre 0 e 100"):
            receber(trip_loss_percent=D("120"))

    def test_sem_nada_informado_e_sem_pesos_devolve_none(self, receber, viagem):
        recebimento = receber(linhas=[{"load": viagem.loads.get(), "received_qty": 10}])
        assert receivings.quebra_da_viagem(recebimento) is None

    def test_sem_peso_de_origem_so_vale_a_quebra_informada(
        self, escritorio, compromisso, item
    ):
        from apps.procurement import trips

        viagem = trips.criar_viagem(
            usuario=escritorio,
            compromisso=compromisso,
            pickup_date=DATA_RETIRADA,
            cargas=[{"item": item, "planned_qty": 10}],
        )
        recebimento = receivings.criar_recebimento(
            usuario=escritorio,
            viagem=viagem,
            date=DATA_RECEBIMENTO,
            trip_loss_percent=D("1.5"),
            linhas=[
                {
                    "load": viagem.loads.get(),
                    "received_qty": 10,
                    "received_weight_kg": D("4900"),
                }
            ],
        )
        quebra = receivings.quebra_da_viagem(recebimento)
        assert quebra.quebra_percentual == D("1.5")
        assert quebra.peso_origem_kg is None and quebra.diferenca_de_peso_kg is None

    def test_corrigir_a_quebra_audita(self, recebimento, escritorio):
        from apps.audit.models import AuditAction, AuditEvent

        receivings.editar_recebimento(
            recebimento,
            {"trip_loss_percent": D("3")},
            None,
            usuario=escritorio,
            motivo="Quebra confirmada pelo transportador",
        )
        recebimento.refresh_from_db()
        assert recebimento.trip_loss_percent == D("3")
        assert AuditEvent.objects.filter(
            entity_id=str(recebimento.pk), action=AuditAction.UPDATE
        ).exists()

    def test_quebra_nao_desconta_nada_do_valor(
        self, recebimento, romaneio, compromisso
    ):
        from apps.procurement.settlement import calcular_acerto

        antes = calcular_acerto(compromisso).valor_dos_animais
        # a quebra só é informada depois: o valor não se mexe
        receivings.editar_recebimento(
            recebimento,
            {"trip_loss_percent": D("9")},
            None,
            usuario=recebimento.created_by,
            motivo="Informando a quebra",
        )
        assert calcular_acerto(compromisso).valor_dos_animais == antes == D("43200.00")

    def test_diferenca_de_cabecas(self, receber, viagem):
        recebimento = receber(linhas=[{"load": viagem.loads.get(), "received_qty": 9}])
        linha = recebimento.lines.get()
        assert receivings.diferenca_de_cabecas(linha) == 1  # embarcou 10, chegou 9


class TestEditarExcluir:
    def test_editar_exige_motivo(self, recebimento, escritorio):
        with pytest.raises(BusinessError, match="Motivo"):
            receivings.editar_recebimento(
                recebimento, {"notes": "x"}, None, usuario=escritorio, motivo=""
            )

    def test_corrigir_a_contagem_audita(self, recebimento, escritorio):
        from apps.audit.models import AuditAction, AuditEvent

        linha = recebimento.lines.get()
        receivings.editar_recebimento(
            recebimento,
            {},
            [
                {
                    "id": linha.pk,
                    "load": linha.load,
                    "received_qty": 9,
                    "received_weight_kg": D("4900"),
                }
            ],
            usuario=escritorio,
            motivo="Recontagem no curral",
        )
        linha.refresh_from_db()
        assert linha.received_qty == 9
        evento = AuditEvent.objects.get(
            entity_type="ReceivingLine", action=AuditAction.UPDATE
        )
        assert evento.reason == "Recontagem no curral"
        assert evento.changed_fields == ["received_qty"]

    def test_excluir_e_restaurar(self, recebimento, gestor):
        excluido = receivings.excluir_recebimento(
            recebimento, usuario=gestor, motivo="Lançado na viagem errada"
        )
        assert excluido.status == Status.EXCLUIDA
        restaurado = receivings.restaurar_recebimento(excluido, usuario=gestor)
        assert restaurado.status == Status.CONFIRMADA

    def test_pode_lancar_outro_depois_de_excluir(self, recebimento, receber, gestor):
        receivings.excluir_recebimento(recebimento, usuario=gestor, motivo="Errado")
        novo = receber()
        assert novo.code == "OP-000001/R2"

    def test_nao_restaura_se_ja_ha_outro(self, recebimento, receber, gestor):
        excluido = receivings.excluir_recebimento(
            recebimento, usuario=gestor, motivo="Errado"
        )
        receber()
        with pytest.raises(BusinessError, match="outro recebimento"):
            receivings.restaurar_recebimento(excluido, usuario=gestor)

    def test_acerto_aprovado_trava_a_correcao(
        self, acerto_aprovado, recebimento, escritorio
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            receivings.editar_recebimento(
                recebimento, {"notes": "x"}, None, usuario=escritorio, motivo="x"
            )

    def test_acerto_aprovado_trava_a_exclusao(
        self, acerto_aprovado, recebimento, gestor
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            receivings.excluir_recebimento(recebimento, usuario=gestor, motivo="x")
