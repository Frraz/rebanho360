"""F1-06 a F1-09: o núcleo do sistema — HerdMovement/HerdLedgerEntry,
partidas dobradas, saldo e a invariante de saldo não negativo. Ver
docs/regras-negocio/01-rebanho-movimentacoes.md e
docs/roadmap/fase-1-cadastros-e-rebanho.md."""

import datetime
import threading

import pytest
from django.db import DatabaseError, IntegrityError, connection

from apps.core import reversible
from apps.core.exceptions import BusinessError
from apps.herd import services
from apps.herd.models import HerdLedgerEntry, HerdMovement, MovementType
from apps.organizations.models import SeasonStatus

pytestmark = pytest.mark.django_db

DATA = datetime.date(2025, 9, 18)


# --------------------------------------------------------------------------
# F1-06 — invariantes de banco
# --------------------------------------------------------------------------


class TestInvariantesDeBanco:
    def test_quantidade_deve_ser_positiva_no_movimento(
        self, baixao, lote_baixao, categoria_desmamados, season
    ):
        with pytest.raises(IntegrityError):
            HerdMovement.objects.create(
                code="MV-TESTE-000001",
                date=DATA,
                type=MovementType.COMPRA,
                season=season,
                quantity=0,
                destination_farm=baixao,
                destination_lot=lote_baixao,
                destination_category=categoria_desmamados,
            )

    def test_transferencia_sem_destino_falha_no_banco_nao_so_na_validacao(
        self, baixao, lote_baixao, categoria_desmamados, season
    ):
        """A invariante que torna o '-140' da planilha impossível de
        representar: tentar gravar uma transferência sem contrapartida de
        destino falha no banco, não só no Python."""
        with pytest.raises(IntegrityError):
            HerdMovement.objects.create(
                code="MV-TESTE-000002",
                date=DATA,
                type=MovementType.TRANSFERENCIA,
                season=season,
                quantity=140,
                origin_farm=baixao,
                origin_lot=lote_baixao,
                origin_category=categoria_desmamados,
                # sem destino nenhum — exatamente o -140 da aba GERAL
            )

    def test_movimento_simples_com_origem_e_destino_falha_no_banco(
        self, baixao, lote_baixao, categoria_desmamados, season
    ):
        with pytest.raises(IntegrityError):
            HerdMovement.objects.create(
                code="MV-TESTE-000003",
                date=DATA,
                type=MovementType.COMPRA,
                season=season,
                quantity=10,
                origin_farm=baixao,
                origin_lot=lote_baixao,
                origin_category=categoria_desmamados,
                destination_farm=baixao,
                destination_lot=lote_baixao,
                destination_category=categoria_desmamados,
            )

    def test_linha_do_razao_com_quantidade_zero_falha_no_banco(
        self, baixao, lote_baixao, categoria_desmamados, season, gestor
    ):
        movimento = services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=10,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        with pytest.raises(IntegrityError):
            HerdLedgerEntry.objects.create(
                movement=movimento,
                date=DATA,
                farm=baixao,
                lot=lote_baixao,
                category=categoria_desmamados,
                quantity=0,
                season=season,
            )

    def test_soma_diferente_de_zero_em_deslocamento_falha_no_commit(
        self,
        baixao,
        sao_francisco,
        lote_baixao,
        lote_sao_francisco,
        categoria_desmamados,
        season,
        gestor,
    ):
        """(6): soma das linhas de um deslocamento = 0 — não é CHECK de
        linha única, é um constraint trigger deferido que só avalia no
        commit, depois que as duas linhas da transação existem."""
        movimento = HerdMovement.objects.create(
            code="MV-TESTE-000004",
            date=DATA,
            type=MovementType.TRANSFERENCIA,
            season=season,
            quantity=140,
            origin_farm=baixao,
            origin_lot=lote_baixao,
            origin_category=categoria_desmamados,
            destination_farm=sao_francisco,
            destination_lot=lote_sao_francisco,
            destination_category=categoria_desmamados,
            created_by=gestor,
        )
        with pytest.raises(DatabaseError, match="[Ss]oma"):
            with connection.cursor() as cur:
                cur.execute("BEGIN")
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
                cur.execute(
                    "INSERT INTO herd_herdledgerentry "
                    "(movement_id, date, farm_id, lot_id, category_id, quantity, "
                    "season_id, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now())",
                    [
                        movimento.pk,
                        DATA,
                        sao_francisco.pk,
                        lote_sao_francisco.pk,
                        categoria_desmamados.pk,
                        100,
                        season.pk,
                    ],  # devia ser +140
                )
                cur.execute("COMMIT")

    def test_linha_do_razao_e_append_only_em_python(
        self, baixao, lote_baixao, categoria_desmamados, season, gestor
    ):
        movimento = services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=10,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        linha = movimento.entries.first()

        with pytest.raises(PermissionError):
            linha.quantity = 999
            linha.save()

        with pytest.raises(PermissionError):
            linha.delete()

        with pytest.raises(PermissionError):
            HerdLedgerEntry.objects.filter(pk=linha.pk).update(quantity=1)

    def test_linha_do_razao_e_append_only_no_banco_mesmo_via_sql_direto(
        self, baixao, lote_baixao, categoria_desmamados, season, gestor
    ):
        movimento = services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=10,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        linha = movimento.entries.first()

        with pytest.raises(DatabaseError):
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE herd_herdledgerentry SET quantity = 1 WHERE id = %s",
                    [linha.pk],
                )


# --------------------------------------------------------------------------
# F1-07 — serviço de movimentação com partidas dobradas
# --------------------------------------------------------------------------


class TestRegistrarMovimentoSimples:
    def test_compra_gera_uma_linha_positiva(
        self, baixao, lote_baixao, categoria_desmamados, gestor
    ):
        movimento = services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=133,
            total_weight_kg=None,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )

        assert movimento.status == reversible.Status.CONFIRMADA
        assert movimento.entries.count() == 1
        linha = movimento.entries.first()
        assert linha.quantity == 133
        assert (
            services.saldo(farm=baixao, category=categoria_desmamados)["head_count"]
            == 133
        )

    def test_morte_gera_uma_linha_negativa_e_exige_motivo(
        self, baixao, lote_baixao, categoria_desmamados, gestor
    ):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=10,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )

        with pytest.raises(BusinessError, match="[Mm]otivo"):
            services.registrar_movimento(
                type=MovementType.MORTE,
                date=DATA,
                quantity=1,
                usuario=gestor,
                origin_farm=baixao,
                origin_lot=lote_baixao,
                origin_category=categoria_desmamados,
            )

        movimento = services.registrar_movimento(
            type=MovementType.MORTE,
            date=DATA,
            quantity=1,
            usuario=gestor,
            origin_farm=baixao,
            origin_lot=lote_baixao,
            origin_category=categoria_desmamados,
            reason="Encontrado morto no curral",
        )
        assert movimento.entries.first().quantity == -1


class TestRegistrarMovimentoDeDeslocamento:
    def test_transferencia_gera_duas_linhas_soma_zero(
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

        movimento = services.registrar_movimento(
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

        soma = sum(
            e.quantity for e in HerdLedgerEntry.objects.filter(movement=movimento)
        )
        assert soma == 0
        assert (
            services.saldo(farm=baixao, category=categoria_desmamados)["head_count"]
            == 0
        )
        assert (
            services.saldo(farm=sao_francisco, category=categoria_desmamados)[
                "head_count"
            ]
            == 140
        )

    def test_evolucao_muda_categoria_sem_alterar_o_total_do_rebanho(
        self, baixao, lote_baixao, categoria_desmamados, categoria_13_24, gestor
    ):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=60,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        total_antes = services.saldo(farm=baixao)["head_count"]

        services.registrar_movimento(
            type=MovementType.EVOLUCAO,
            date=DATA,
            quantity=60,
            usuario=gestor,
            origin_farm=baixao,
            origin_lot=lote_baixao,
            origin_category=categoria_desmamados,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_13_24,
        )

        total_depois = services.saldo(farm=baixao)["head_count"]
        assert total_antes == total_depois
        assert (
            services.saldo(farm=baixao, category=categoria_desmamados)["head_count"]
            == 0
        )
        assert services.saldo(farm=baixao, category=categoria_13_24)["head_count"] == 60


class TestInvarianteDeSaldoNaoNegativo:
    def test_saldo_insuficiente_e_bloqueado_com_mensagem_especifica(
        self, baixao, lote_baixao, categoria_13_24, gestor
    ):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=12,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_13_24,
        )

        with pytest.raises(BusinessError) as excinfo:
            services.registrar_movimento(
                type=MovementType.VENDA,
                date=DATA,
                quantity=20,
                usuario=gestor,
                origin_farm=baixao,
                origin_lot=lote_baixao,
                origin_category=categoria_13_24,
            )

        mensagem = str(excinfo.value)
        assert "12 cabeças" in mensagem
        assert "Machos 13 a 24 meses" in mensagem
        assert "Baixão" in mensagem
        assert "20" in mensagem

        assert (
            services.saldo(farm=baixao, category=categoria_13_24)["head_count"] == 12
        )  # nada mudou

    def test_data_futura_e_bloqueada(
        self, baixao, lote_baixao, categoria_desmamados, gestor
    ):
        futuro = datetime.date.today() + datetime.timedelta(days=1)
        with pytest.raises(BusinessError, match="futura"):
            services.registrar_movimento(
                type=MovementType.COMPRA,
                date=futuro,
                quantity=1,
                usuario=gestor,
                destination_farm=baixao,
                destination_lot=lote_baixao,
                destination_category=categoria_desmamados,
            )

    def test_ajuste_inventario_e_permissao_restrita(
        self, baixao, lote_baixao, categoria_desmamados, escritorio, gestor
    ):
        with pytest.raises(BusinessError, match="[Rr]estrita"):
            services.registrar_movimento(
                type=MovementType.AJUSTE_INVENTARIO,
                date=DATA,
                quantity=5,
                usuario=escritorio,
                destination_farm=baixao,
                destination_lot=lote_baixao,
                destination_category=categoria_desmamados,
                reason="Contagem física",
            )

        movimento = services.registrar_movimento(
            type=MovementType.AJUSTE_INVENTARIO,
            date=DATA,
            quantity=5,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
            reason="Contagem física",
        )
        assert movimento.entries.first().quantity == 5

    def test_campo_sem_acesso_de_escrita_a_fazenda_e_bloqueado(
        self, sao_francisco, lote_sao_francisco, categoria_desmamados, campo_baixao
    ):
        with pytest.raises(BusinessError, match="permissão"):
            services.registrar_movimento(
                type=MovementType.COMPRA,
                date=DATA,
                quantity=5,
                usuario=campo_baixao,
                destination_farm=sao_francisco,
                destination_lot=lote_sao_francisco,
                destination_category=categoria_desmamados,
            )

    def test_safra_encerrada_bloqueia_exceto_admin(
        self, baixao, lote_baixao, categoria_desmamados, season, gestor, admin
    ):
        season.status = SeasonStatus.ENCERRADA
        season.save(update_fields=["status"])

        with pytest.raises(BusinessError, match="encerrada"):
            services.registrar_movimento(
                type=MovementType.COMPRA,
                date=DATA,
                quantity=5,
                usuario=gestor,
                destination_farm=baixao,
                destination_lot=lote_baixao,
                destination_category=categoria_desmamados,
            )

        movimento = services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=5,
            usuario=admin,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )
        assert movimento.pk is not None


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason=(
        "select_for_update() em SQLite não bloqueia entre conexões/threads "
        "do jeito que faz no Postgres — validar via docker compose."
    ),
)
@pytest.mark.django_db(transaction=True)
def test_duas_saidas_concorrentes_da_mesma_posicao_uma_passa_a_outra_e_barrada():
    import datetime as dt

    from apps.accounts.models import Role, User
    from apps.livestock.models import AnimalCategory, Lot, Sex
    from apps.organizations.models import Company, Season
    from apps.properties.models import Farm

    usuario = User.objects.create_user(
        username="concorrente", password="x", role=Role.GESTOR
    )
    company = Company.objects.create(name="Fazendas Reunidas")
    season = Season.objects.create(
        company=company,
        name="2025/2026",
        start_date=dt.date(2025, 7, 1),
        end_date=dt.date(2026, 6, 30),
        is_current=True,
    )
    farm = Farm.objects.create(name="Baixão", code="BXO")
    categoria = AnimalCategory.objects.create(
        name="Machos 13 a 24 meses", sex=Sex.MACHO, age_order=3
    )
    lot = Lot.objects.create(
        code="LT-BXO-001", farm=farm, season=season, entry_date=dt.date(2025, 9, 1)
    )

    services.registrar_movimento(
        type=MovementType.COMPRA,
        date=DATA,
        quantity=20,
        usuario=usuario,
        destination_farm=farm,
        destination_lot=lot,
        destination_category=categoria,
    )

    resultados = []
    barreira = threading.Barrier(2)

    def tentar_vender():
        barreira.wait()
        try:
            services.registrar_movimento(
                type=MovementType.VENDA,
                date=DATA,
                quantity=15,
                usuario=usuario,
                origin_farm=farm,
                origin_lot=lot,
                origin_category=categoria,
            )
            resultados.append("ok")
        except BusinessError:
            resultados.append("erro")
        finally:
            connection.close()

    t1 = threading.Thread(target=tentar_vender)
    t2 = threading.Thread(target=tentar_vender)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(resultados) == ["erro", "ok"]
    assert services.saldo(farm=farm, category=categoria)["head_count"] == 5


# --------------------------------------------------------------------------
# F1-08 — HerdBalanceService
# --------------------------------------------------------------------------


class TestSaldo:
    def test_saldo_e_sempre_soma_do_razao_nunca_campo(
        self, baixao, lote_baixao, categoria_desmamados, gestor
    ):
        assert not hasattr(lote_baixao, "head_count")
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
            reason="Causa desconhecida",
        )
        assert (
            services.saldo(farm=baixao, category=categoria_desmamados)["head_count"]
            == 47
        )

    def test_correcao_de_fato_antigo_conserta_o_saldo_naquela_data(
        self, baixao, lote_baixao, categoria_desmamados, gestor
    ):
        """O teste central da F1-08: corrigir uma contagem de setembro em
        outubro tem que valer para trás — o saldo em 30/09 reflete a
        correção, feita com compensação datada do fato original."""
        movimento = services.registrar_movimento(
            type=MovementType.SALDO_INICIAL,
            date=datetime.date(2025, 9, 18),
            quantity=126,
            usuario=gestor,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_desmamados,
        )

        reversible.editar(
            movimento,
            {"quantity": 120},
            usuario=gestor,
            motivo="Contagem corrigida no curral",
        )

        saldo_em_30_09 = services.saldo(
            farm=baixao,
            category=categoria_desmamados,
            until=datetime.date(2025, 9, 30),
        )["head_count"]
        assert saldo_em_30_09 == 120

        # as 3 linhas existem: original +126, compensação -126, nova +120
        assert HerdLedgerEntry.objects.filter(movement=movimento).count() == 3
        original = HerdLedgerEntry.objects.get(
            movement=movimento, reverses_entry__isnull=True, quantity=126
        )
        compensacao = HerdLedgerEntry.objects.get(reverses_entry=original)
        assert compensacao.date == datetime.date(2025, 9, 18)
        assert compensacao.quantity == -126
