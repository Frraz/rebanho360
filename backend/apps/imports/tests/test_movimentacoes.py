"""F2-12 — importador de movimentações com conciliação.

O que importa: toda transferência pareada vira movimento de soma zero, e as
não pareadas ficam listadas aguardando decisão — nenhuma importada em
silêncio. É aqui que os −140 da aba `GERAL` aparecem."""

import datetime
from decimal import Decimal

import pytest

from apps.core.reversible import Status
from apps.herd import services as herd
from apps.herd.models import HerdLedgerEntry, HerdMovement, MovementType
from apps.herd.selectors import conciliar_transferencias
from apps.imports import services
from apps.imports.importers.movimentacoes import ImportadorDeMovimentacoes
from apps.imports.models import ImportKind, RowStatus
from apps.imports.tests.conftest import (
    aba_de_fazenda,
    planilha_sem_abas,
    precisa_da_planilha,
    upload_de,
    upload_real,
)
from apps.livestock.models import AnimalCategory
from apps.organizations.models import Season
from apps.partners.models import Partner
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db

D = Decimal
DESM = "Machos Desm. até 12m"
D1 = datetime.datetime(2025, 9, 10)


def safra():
    return Season.objects.get(name="2025/2026")


def enviar(usuario, wb, **opcoes):
    batch = services.criar_importacao(
        kind=ImportKind.MOVIMENTACOES, arquivo=upload_de(wb), usuario=usuario
    )
    return services.salvar_opcoes(
        batch, {"season_id": safra().pk, **opcoes}, usuario=usuario
    )


def saldo(codigo_da_fazenda, categoria=None):
    farm = Farm.objects.get(code=codigo_da_fazenda)
    kwargs = (
        {"category": AnimalCategory.objects.get(name=categoria)} if categoria else {}
    )
    return herd.saldo(farm=farm, **kwargs)["head_count"]


def soma_do_razao(movimento):
    return sum(movimento.entries.values_list("quantity", flat=True))


class TestSaldoAnteriorETiposSimples:
    def _wb(self):
        wb = planilha_sem_abas()
        aba_de_fazenda(
            wb,
            "BAIXÃO",
            saldos=[(DESM, 100)],
            movimentos=[
                (D1, DESM, "MORTE", 2),
                (
                    datetime.datetime(2025, 9, 11),
                    DESM,
                    "ABATE",
                    30,
                    "COPERFRIGU",
                    15000,
                ),
                (datetime.datetime(2025, 9, 12), DESM, "NASC.", 5),
            ],
        )
        return wb

    def test_saldo_anterior_do_quadro_resumo_vira_saldo_inicial(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb())

        services.importar(batch, usuario=usuario_escritorio)

        assert HerdMovement.objects.filter(type=MovementType.SALDO_INICIAL).count() == 1
        assert saldo("BXO", DESM) == 100 - 2 - 30 + 5

    def test_saldo_inicial_leva_a_data_de_abertura_da_safra(self, usuario_escritorio):
        batch = enviar(usuario_escritorio, self._wb())
        services.importar(batch, usuario=usuario_escritorio)

        movimento = HerdMovement.objects.get(type=MovementType.SALDO_INICIAL)

        assert movimento.date == safra().start_date

    def test_sem_escolher_a_safra_do_saldo_a_previa_diz_o_que_falta(
        self, usuario_escritorio
    ):
        batch = services.criar_importacao(
            kind=ImportKind.MOVIMENTACOES,
            arquivo=upload_de(self._wb()),
            usuario=usuario_escritorio,
        )

        resumo = services.resumo_da_previa(batch)

        assert "Escolha a safra do saldo anterior" in resumo["problemas"][0]

    def test_morte_importada_diz_que_o_motivo_nao_foi_informado(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb())
        services.importar(batch, usuario=usuario_escritorio)

        morte = HerdMovement.objects.get(type=MovementType.MORTE)

        assert "motivo não informado" in morte.reason
        assert "aba BAIXÃO, linha 20" in morte.notes

    def test_destino_em_texto_livre_fica_na_observacao_e_vira_parceiro_so_com_confirmacao(
        self, usuario_escritorio
    ):
        wb = self._wb()
        batch = enviar(usuario_escritorio, wb)
        assert ("COPERFRIGU", 1) in ImportadorDeMovimentacoes().textos_de_destino(batch)

        # sem decisão: não cria parceiro, mas guarda o texto
        services.importar(batch, usuario=usuario_escritorio)
        abate = HerdMovement.objects.get(type=MovementType.ABATE)
        assert abate.partner is None
        assert "Destino na planilha: COPERFRIGU" in abate.notes
        assert not Partner.objects.filter(name="COPERFRIGU").exists()

    def test_destino_com_decisao_de_criar_vira_parceiro(self, usuario_escritorio):
        batch = enviar(
            usuario_escritorio, self._wb(), destinos={"coperfrigu": {"acao": "CRIAR"}}
        )

        services.importar(batch, usuario=usuario_escritorio)

        abate = HerdMovement.objects.get(type=MovementType.ABATE)
        assert abate.partner.name == "COPERFRIGU"

    def test_saida_maior_que_o_saldo_e_erro_na_previa_com_mensagem_especifica(
        self, usuario_escritorio
    ):
        wb = planilha_sem_abas()
        aba_de_fazenda(
            wb, "BAIXÃO", saldos=[(DESM, 10)], movimentos=[(D1, DESM, "ABATE", 20)]
        )

        batch = enviar(usuario_escritorio, wb)

        linha = batch.rows.get(raw__tipo="ABATE")
        assert linha.status == RowStatus.ERRO
        assert (
            "Saldo insuficiente: há 10 cabeças de Machos Desm. até 12m em Baixão"
            in linha.messages[0]["texto"]
        )
        assert "foram informadas 20" in linha.messages[0]["texto"]

    def test_previa_sem_erro_importa_sem_surpresa(self, usuario_escritorio):
        batch = enviar(usuario_escritorio, self._wb())
        assert services.resumo_da_previa(batch)["erros"] == 0

        resultado = services.importar(batch, usuario=usuario_escritorio)

        assert resultado["movimentos"] == 4  # saldo + morte + abate + nascimento

    def test_tipo_desconhecido_e_erro_nao_e_ignorado(self, usuario_escritorio):
        wb = planilha_sem_abas()
        aba_de_fazenda(wb, "BAIXÃO", movimentos=[(D1, DESM, "SUMIU", 1)])

        batch = enviar(usuario_escritorio, wb)

        assert batch.rows.get().status == RowStatus.ERRO

    def test_categoria_desconhecida_pede_decisao(self, usuario_escritorio):
        wb = planilha_sem_abas()
        aba_de_fazenda(wb, "BAIXÃO", movimentos=[(D1, "Boi Jurássico", "MORTE", 1)])

        batch = enviar(usuario_escritorio, wb)

        linha = batch.rows.get()
        assert linha.status == RowStatus.PENDENTE
        assert linha.pendencias[0]["campo"] == "category"

    def test_aba_sem_fazenda_cadastrada_pede_decisao(self, usuario_escritorio):
        wb = planilha_sem_abas()
        aba_de_fazenda(wb, "SAO JOSE DO GROTAO", movimentos=[(D1, DESM, "NASC.", 1)])
        Farm.objects.filter(code="SJG").update(is_active=False)

        batch = enviar(usuario_escritorio, wb)

        assert batch.rows.get().pendencias[0]["campo"] == "farm"


class TestCompraNaoDuplica:
    def test_linhas_de_compra_das_abas_sao_ignoradas_com_motivo(
        self, usuario_escritorio
    ):
        wb = planilha_sem_abas()
        aba_de_fazenda(
            wb, "BAIXÃO", movimentos=[(D1, DESM, "COMPRA", 133, "COMPRA GOIANO", 27668)]
        )

        batch = enviar(usuario_escritorio, wb)

        linha = batch.rows.get()
        assert linha.status == RowStatus.IGNORADA
        assert "dobraria o rebanho" in linha.messages[0]["texto"]

    def test_aviso_quando_as_compras_das_abas_nao_batem_com_as_importadas(
        self, usuario_escritorio
    ):
        from apps.purchases import services as compras

        farm = Farm.objects.get(code="BXO")
        compra = compras.criar_compra(
            usuario=usuario_escritorio,
            date=D1.date(),
            destination_farm=farm,
            category=AnimalCategory.objects.get(name=DESM),
            head_count=140,
            animal_value=D("1000"),
        )
        compras.confirmar_compra(compra, usuario=usuario_escritorio)
        wb = planilha_sem_abas()
        aba_de_fazenda(wb, "BAIXÃO", movimentos=[(D1, DESM, "COMPRA", 133)])

        batch = enviar(usuario_escritorio, wb)

        avisos = ImportadorDeMovimentacoes().avisos_do_lote(batch)
        assert any("133" in a and "140" in a and "diferença de 7" in a for a in avisos)

    def test_sem_compras_importadas_o_aviso_manda_importar_as_compras_primeiro(
        self, usuario_escritorio
    ):
        wb = planilha_sem_abas()
        aba_de_fazenda(wb, "BAIXÃO", movimentos=[(D1, DESM, "COMPRA", 133)])

        batch = enviar(usuario_escritorio, wb)

        avisos = ImportadorDeMovimentacoes().avisos_do_lote(batch)
        assert any("Importe as compras primeiro" in a for a in avisos)


class TestConciliacaoDeTransferencias:
    """O ponto crítico: `TRANSF. S` e `TRANSF. E` viram UM movimento de 2 linhas."""

    def _wb(self, *, entrada=True, quantidade_entrada=50):
        wb = planilha_sem_abas()
        aba_de_fazenda(
            wb,
            "BAIXÃO",
            saldos=[(DESM, 100)],
            movimentos=[(D1, DESM, "TRANSF. S", 50, "GOIANO", 7500)],
        )
        aba_de_fazenda(
            wb,
            "GOIANO",
            movimentos=(
                [(D1, DESM, "TRANSF. E", quantidade_entrada, "BAIXÃO", 7500)]
                if entrada
                else []
            ),
        )
        return wb

    def test_saida_e_entrada_correspondentes_viram_um_movimento_de_soma_zero(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb())

        services.importar(batch, usuario=usuario_escritorio)

        transferencias = HerdMovement.objects.filter(type=MovementType.TRANSFERENCIA)
        assert transferencias.count() == 1  # um movimento, não dois
        movimento = transferencias.get()
        assert movimento.entries.count() == 2
        assert soma_do_razao(movimento) == 0
        assert (movimento.origin_farm.code, movimento.destination_farm.code) == (
            "BXO",
            "GOI",
        )
        assert saldo("BXO", DESM) == 50 and saldo("GOI", DESM) == 50

    def test_as_duas_linhas_da_planilha_apontam_para_o_mesmo_movimento(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb())
        services.importar(batch, usuario=usuario_escritorio)

        alvos = {r.target_id for r in batch.rows.filter(raw__tipo__startswith="TRANSF")}

        assert len(alvos) == 1

    def test_nenhuma_transferencia_importada_fica_sem_contrapartida(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb())
        services.importar(batch, usuario=usuario_escritorio)

        assert conciliar_transferencias().count() == 0

    def test_saida_sem_entrada_vira_pendencia_e_nao_e_importada(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb(entrada=False))

        resumo = services.resumo_da_previa(batch)
        linha = batch.rows.get(raw__tipo="TRANSF. S")

        assert linha.status == RowStatus.PENDENTE
        assert (
            "sem entrada correspondente em nenhuma aba" in linha.pendencias[0]["texto"]
        )
        assert "não inventa a contrapartida" in linha.pendencias[0]["texto"]
        assert resumo["pendentes"] == 1

        services.importar(batch, usuario=usuario_escritorio)

        assert not HerdMovement.objects.filter(type=MovementType.TRANSFERENCIA).exists()
        assert saldo("BXO", DESM) == 100  # a saída órfã NÃO foi lançada
        batch.refresh_from_db()
        assert batch.rows.get(raw__tipo="TRANSF. S").status == RowStatus.PENDENTE

    def test_quantidade_diferente_nao_pareia(self, usuario_escritorio):
        batch = enviar(usuario_escritorio, self._wb(quantidade_entrada=45))

        assert (
            batch.rows.filter(status=RowStatus.PENDENTE).count() == 2
        )  # as duas ficam órfãs

    def test_usuario_pode_definir_origem_e_destino_da_saida_orfa(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb(entrada=False))
        linha = batch.rows.get(raw__tipo="TRANSF. S")
        baixao, goiano = Farm.objects.get(code="BXO"), Farm.objects.get(code="GOI")

        batch = services.salvar_decisoes(
            batch,
            {linha.pk: {"acao": "DEFINIR", "origem": baixao.pk, "destino": goiano.pk}},
            [],
            usuario=usuario_escritorio,
        )
        services.importar(batch, usuario=usuario_escritorio)

        movimento = HerdMovement.objects.get(type=MovementType.TRANSFERENCIA)
        assert soma_do_razao(movimento) == 0
        assert saldo("GOI", DESM) == 50

    def test_usuario_pode_ignorar_a_saida_orfa_e_a_decisao_fica_registrada(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb(entrada=False))
        linha = batch.rows.get(raw__tipo="TRANSF. S")

        batch = services.salvar_decisoes(
            batch, {linha.pk: {"acao": "IGNORAR"}}, [], usuario=usuario_escritorio
        )

        linha.refresh_from_db()
        assert linha.status == RowStatus.IGNORADA
        assert linha.resolution == {"acao": "IGNORAR"}

    def test_definir_com_origem_igual_ao_destino_continua_pendente(
        self, usuario_escritorio
    ):
        batch = enviar(usuario_escritorio, self._wb(entrada=False))
        linha = batch.rows.get(raw__tipo="TRANSF. S")
        baixao = Farm.objects.get(code="BXO")

        batch = services.salvar_decisoes(
            batch,
            {linha.pk: {"acao": "DEFINIR", "origem": baixao.pk, "destino": baixao.pk}},
            [],
            usuario=usuario_escritorio,
        )

        linha.refresh_from_db()
        assert linha.status == RowStatus.PENDENTE

    def test_transferencia_sem_saldo_na_origem_e_erro_na_previa(
        self, usuario_escritorio
    ):
        wb = planilha_sem_abas()
        aba_de_fazenda(wb, "BAIXÃO", movimentos=[(D1, DESM, "TRANSF. S", 50)])
        aba_de_fazenda(wb, "GOIANO", movimentos=[(D1, DESM, "TRANSF. E", 50)])

        batch = enviar(usuario_escritorio, wb)

        assert (
            batch.rows.filter(status=RowStatus.ERRO).count() == 2
        )  # as duas pontas do par

    def test_evolucao_precisa_da_categoria_de_origem_e_sugere_a_anterior(
        self, usuario_escritorio
    ):
        wb = planilha_sem_abas()
        aba_de_fazenda(
            wb,
            "BAIXÃO",
            saldos=[(DESM, 10)],
            movimentos=[(D1, "Machos 13 a 24 meses", "EVOLUÇ", 4)],
        )
        batch = enviar(usuario_escritorio, wb)
        linha = batch.rows.get(raw__tipo="EVOLUÇ")

        assert linha.status == RowStatus.PENDENTE
        assert linha.pendencias[0]["campo"] == "origin_category"
        assert linha.pendencias[0]["sugestao"]["rotulo"] == DESM

        origem = AnimalCategory.objects.get(name=DESM)
        batch = services.salvar_decisoes(
            batch,
            {linha.pk: {"origin_category": origem.pk}},
            [],
            usuario=usuario_escritorio,
        )
        services.importar(batch, usuario=usuario_escritorio)

        evolucao = HerdMovement.objects.get(type=MovementType.EVOLUCAO)
        assert soma_do_razao(evolucao) == 0  # pendência #1: 2 linhas, soma zero
        assert saldo("BXO") == 10  # a evolução nunca altera o total


@precisa_da_planilha
class TestPlanilhaReal:
    @pytest.fixture
    def compras_importadas(self, usuario_escritorio):
        previa = services.criar_importacao(
            kind=ImportKind.COMPRAS, arquivo=upload_real(), usuario=usuario_escritorio
        )
        previa = services.salvar_opcoes(
            previa,
            {"category_map": {"bezerros": AnimalCategory.objects.get(name=DESM).pk}},
            usuario=usuario_escritorio,
        )
        services.importar(previa, usuario=usuario_escritorio)

    @pytest.fixture
    def previa(self, usuario_escritorio, compras_importadas):
        batch = services.criar_importacao(
            kind=ImportKind.MOVIMENTACOES,
            arquivo=upload_real(),
            usuario=usuario_escritorio,
        )
        return services.salvar_opcoes(
            batch, {"season_id": safra().pk}, usuario=usuario_escritorio
        )

    def test_os_menos_140_aparecem_como_duas_pendencias_de_contrapartida(self, previa):
        orfas = previa.rows.filter(status=RowStatus.PENDENTE)

        assert orfas.count() == 2
        assert {r.sheet for r in orfas} == {"GOIANO"}
        assert sorted(r.raw["quantidade"] for r in orfas) == [45, 95]  # 140 ao todo
        assert all(r.raw["tipo"] == "TRANSF. S" for r in orfas)

    def test_compras_das_abas_sao_ignoradas_e_a_diferenca_de_126_e_avisada(
        self, previa
    ):
        ignoradas = previa.rows.filter(status=RowStatus.IGNORADA, raw__tipo="COMPRA")
        assert ignoradas.count() == 11

        avisos = ImportadorDeMovimentacoes().avisos_do_lote(previa)

        assert any(
            "828" in a and "954" in a and "diferença de 126" in a for a in avisos
        )

    def test_sem_erros_de_saldo_com_o_saldo_anterior_importado(self, previa):
        resumo = services.resumo_da_previa(previa)

        assert resumo["erros"] == 0
        assert resumo["prontas"] == 3 + 23 + 3  # saldos anteriores + mortes + abates

    def test_importa_sem_nenhuma_transferencia_orfa_em_silencio(
        self, previa, usuario_escritorio
    ):
        resultado = services.importar(previa, usuario=usuario_escritorio)

        assert resultado["movimentos"] == 29
        assert resultado["pendentes_restantes"] == 2
        assert not HerdMovement.objects.filter(type=MovementType.TRANSFERENCIA).exists()
        assert conciliar_transferencias().count() == 0

    def test_saldo_sao_francisco_considera_as_compras_da_aba_compra_de_gado(
        self, previa, usuario_escritorio
    ):
        services.importar(previa, usuario=usuario_escritorio)

        # 1.503 de saldo anterior + 954 compradas − 354 abatidas − 23 mortes.
        # A planilha fecha em 1.954 porque a aba da fazenda registra só 828
        # compras: a de 27/04/2026 (126 cabeças) ficou sem lançar lá.
        assert saldo("SFR") == 1503 + 954 - 354 - 23 == 2080
        assert 2080 - 1954 == 126

    def test_resolver_os_140_como_transferencia_sao_francisco_para_goiano(
        self, previa, usuario_escritorio
    ):
        sfr, goi = Farm.objects.get(code="SFR"), Farm.objects.get(code="GOI")
        decisoes = {
            r.pk: {"acao": "DEFINIR", "origem": sfr.pk, "destino": goi.pk}
            for r in previa.rows.filter(status=RowStatus.PENDENTE)
        }
        previa = services.salvar_decisoes(
            previa, decisoes, [], usuario=usuario_escritorio
        )

        resultado = services.importar(previa, usuario=usuario_escritorio)

        assert resultado["movimentos"] == 31
        for movimento in HerdMovement.objects.filter(type=MovementType.TRANSFERENCIA):
            assert soma_do_razao(movimento) == 0
        assert saldo("GOI") == 140
        assert HerdLedgerEntry.objects.filter(farm=goi).count() == 2

    def test_movimentos_importados_sao_editaveis_e_excluiveis(
        self, previa, usuario_escritorio, usuario_gestor
    ):
        from apps.core import reversible

        services.importar(previa, usuario=usuario_escritorio)
        morte = HerdMovement.objects.filter(type=MovementType.MORTE).first()

        reversible.excluir(morte, usuario=usuario_gestor, motivo="Importada errada")

        morte.refresh_from_db()
        assert morte.status == Status.EXCLUIDA
