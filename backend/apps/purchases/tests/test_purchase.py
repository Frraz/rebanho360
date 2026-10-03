"""F2-04 a F2-07 — compra de gado: modelo, confirmação transacional,
`PurchaseCostService`, edição e exclusão com cascata. Ver
docs/regras-negocio/03-compra-de-gado.md e 06-edicao-exclusao-e-auditoria.md."""

import datetime
import threading
from decimal import Decimal

import pytest
from django.db import connection
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.herd import services as herd
from apps.herd.models import HerdMovement, MovementType
from apps.livestock.models import Lot, LotStatus
from apps.organizations.models import SeasonStatus
from apps.purchases import services
from apps.purchases.models import Purchase

pytestmark = pytest.mark.django_db

D = Decimal


def confirmada(criar, escritorio, dados):
    compra = criar(**dados)
    return services.confirmar_compra(compra, usuario=escritorio)


def saldo_do_lote(compra):
    return herd.saldo(lot=compra.lot)["head_count"]


# --------------------------------------------------------------------------
# F2-04 — modelo e cálculo
# --------------------------------------------------------------------------


class TestCriacaoECodigo:
    def test_codigo_cp_por_safra_em_sequencia(self, criar, dados_compra):
        a = criar(**dados_compra)
        b = criar(**dados_compra)

        assert a.code == "CP-2025/26-0001"
        assert b.code == "CP-2025/26-0002"

    def test_nasce_rascunho_e_nao_afeta_rebanho_nem_custo(self, criar, dados_compra):
        compra = criar(**dados_compra)

        assert compra.status == Status.RASCUNHO
        assert HerdMovement.objects.count() == 0
        assert CostEntry.objects.count() == 0
        assert Lot.objects.count() == 0

    def test_peso_e_opcional(self, criar, dados_compra):
        assert criar(**dados_compra).total_weight_kg is None

    @pytest.mark.parametrize(
        "campo, valor, trecho",
        [
            ("head_count", 0, "cabeças"),
            ("animal_value", D("0"), "valor dos animais"),
            ("freight_value", D("-1"), "frete"),
            ("total_weight_kg", D("0"), "peso total"),
        ],
    )
    def test_validacoes_de_valores(self, criar, dados_compra, campo, valor, trecho):
        with pytest.raises(BusinessError, match=trecho):
            criar(**{**dados_compra, campo: valor})

    def test_data_futura_e_recusada(self, criar, dados_compra):
        amanha = datetime.date.today() + datetime.timedelta(days=1)

        with pytest.raises(BusinessError, match="futura"):
            criar(**{**dados_compra, "date": amanha})

    def test_vendedor_precisa_ser_fornecedor_ou_produtor(self, criar, dados_compra):
        from apps.partners.models import Partner

        sem_papel = Partner.objects.create(name="Sem papel")

        with pytest.raises(BusinessError, match="Fornecedor nem de Produtor"):
            criar(**{**dados_compra, "seller": sem_papel})

    def test_fazenda_fora_do_escopo_de_escrita_e_recusada(
        self, campo_baixao, dados_compra
    ):
        from apps.accounts.models import Role

        campo_baixao.role = Role.ESCRITORIO
        campo_baixao.save()

        with pytest.raises(BusinessError, match="permissão de lançamento"):
            services.criar_compra(usuario=campo_baixao, **dados_compra)

    def test_campo_nao_lanca_compra(self, campo_baixao, dados_compra):
        with pytest.raises(BusinessError, match="permissão para lançar compras"):
            services.criar_compra(usuario=campo_baixao, **dados_compra)

    def test_safra_encerrada_recusa_compra_de_escritorio(
        self, criar, dados_compra, season
    ):
        season.status = SeasonStatus.ENCERRADA
        season.save()

        with pytest.raises(BusinessError, match="encerrada"):
            criar(**dados_compra)


class TestPurchaseCostService:
    def test_105_bezerros_por_260172_15_da_2477_83_por_cabeca(self):
        """O caso de conferência com a planilha (regras 03 e 05)."""
        custo = services.calcular_custo_da_compra(
            head_count=105, animal_value=D("260172.15")
        )

        assert custo.media_por_cabeca.quantize(D("0.01")) == D("2477.83")
        assert custo.custo_aquisicao == D("260172.15")

    def test_custo_de_aquisicao_soma_os_quatro_valores(self):
        custo = services.calcular_custo_da_compra(
            head_count=100,
            animal_value=D("260172.15"),
            freight_value=D("4500"),
            commission_value=D("2600"),
            tax_value=D("780"),
        )

        assert custo.custo_aquisicao == D("268052.15")
        assert custo.media_por_cabeca == D("2601.7215")  # só os animais
        assert custo.custo_por_cabeca == D("2680.5215")

    def test_compra_sem_peso_mostra_none_nunca_zero(self):
        custo = services.calcular_custo_da_compra(
            head_count=105, animal_value=D("260172.15")
        )

        assert custo.custo_por_arroba is None
        assert custo.custo_por_kg is None
        assert custo.peso_medio_kg is None

    def test_com_peso_calcula_arroba_e_kg_sem_arredondar_no_meio(self):
        custo = services.calcular_custo_da_compra(
            head_count=133, animal_value=D("300000"), total_weight_kg=D("27668")
        )

        assert custo.peso_medio_kg.quantize(D("0.01")) == D("208.03")  # planilha
        assert custo.custo_por_kg == D("300000") / D("27668")
        assert custo.custo_por_arroba == D("300000") / (D("27668") / 15)

    def test_sem_cabecas_tudo_none(self):
        custo = services.calcular_custo_da_compra(head_count=0, animal_value=D("10"))

        assert custo.media_por_cabeca is None
        assert custo.custo_por_cabeca is None

    def test_tela_mostra_traco_e_nao_zero_quando_nao_ha_peso(
        self, client, escritorio, criar, dados_compra
    ):
        compra = criar(**dados_compra)
        client.force_login(escritorio)

        html = client.get(
            reverse("purchases:detalhe", args=[compra.pk])
        ).content.decode()

        assert "Custo por @ (peso vivo)</span> <span>—</span>" in html
        assert "falta o peso total da compra" in html


# --------------------------------------------------------------------------
# F2-05 — confirmação transacional
# --------------------------------------------------------------------------


class TestConfirmacao:
    def test_confirmar_cria_lote_da_entrada_e_um_custo_por_valor(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(
            criar,
            escritorio,
            {
                **dados_compra,
                "freight_value": D("4500"),
                "commission_value": D("2600"),
                "tax_value": D("780"),
            },
        )

        compra.refresh_from_db()
        assert compra.status == Status.CONFIRMADA
        assert compra.lot.code == "LT-SFR-001"
        assert compra.lot.origin_purchase == compra
        assert saldo_do_lote(compra) == 126

        movimento = compra.movements.get()
        assert movimento.type == MovementType.COMPRA
        assert movimento.status == Status.CONFIRMADA

        custos = {c.description: c for c in compra.cost_entries.all()}
        assert len(custos) == 4
        assert {c.cost_center.name for c in custos.values()} == {
            "DESPESA GADO",
            "FRETE",
            "COMISSÃO",
            "IMPOSTO E TAXAS",
        }
        assert sum(c.amount for c in custos.values()) == D(
            "396.0".replace("396.0", "395960.00")
        )
        assert all(c.lot_id == compra.lot_id for c in custos.values())  # custo direto
        assert all(c.source_purchase_id == compra.pk for c in custos.values())

    def test_so_gera_custo_dos_valores_preenchidos(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        custos = list(compra.cost_entries.all())

        assert len(custos) == 1
        assert custos[0].cost_center.name == "DESPESA GADO"
        assert custos[0].amount == D("388080.00")

    def test_compra_em_lote_existente_nao_cria_lote(
        self, criar, escritorio, dados_compra, lote_sao_francisco
    ):
        compra = confirmada(
            criar, escritorio, {**dados_compra, "lot": lote_sao_francisco}
        )

        assert Lot.objects.count() == 1
        assert saldo_do_lote(compra) == 126

    def test_confirmar_de_novo_diz_que_ja_foi_confirmada(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        with pytest.raises(BusinessError, match="já foi confirmada"):
            services.confirmar_compra(compra, usuario=escritorio)

        assert HerdMovement.objects.count() == 1

    def test_falha_no_meio_nao_deixa_residuo(self, criar, escritorio, dados_compra):
        """Tudo ou nada: sem o centro DESPESA GADO, nada entra."""
        from apps.costs.models import CostCenter

        compra = criar(**dados_compra)
        CostCenter.objects.filter(name="DESPESA GADO").delete()

        with pytest.raises(BusinessError, match="DESPESA GADO"):
            services.confirmar_compra(compra, usuario=escritorio)

        compra.refresh_from_db()
        assert compra.status == Status.RASCUNHO
        assert HerdMovement.objects.count() == 0
        assert Lot.objects.count() == 0
        assert CostEntry.objects.count() == 0

    def test_consultor_nao_confirma(self, criar, dados_compra):
        from apps.accounts.models import Role, User

        consulta = User.objects.create_user(
            username="c", password="x", role=Role.CONSULTA
        )
        compra = criar(**dados_compra)

        with pytest.raises(BusinessError, match="permissão para confirmar"):
            services.confirmar_compra(compra, usuario=consulta)

    def test_confirmar_gera_auditoria_da_compra_do_movimento_e_dos_custos(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        tipos = set(AuditEvent.objects.values_list("entity_type", flat=True))

        assert {"Purchase", "HerdMovement", "CostEntry", "Lot"} <= tipos
        assert AuditEvent.objects.filter(
            entity_type="Purchase", entity_id=str(compra.pk), action="CONFIRM"
        ).exists()


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="select_for_update() só bloqueia entre conexões no Postgres.",
)
@pytest.mark.django_db(transaction=True)
def test_confirmacao_concorrente_da_mesma_compra_cria_um_movimento_nao_dois():
    """O clique duplo é cenário real com a rede da fazenda (F2-05)."""
    from apps.accounts.models import Role, User
    from apps.costs.models import CostCenter, CostClass
    from apps.livestock.models import AnimalCategory, Sex
    from apps.organizations.models import Company, Season
    from apps.properties.models import Farm

    for nome in ("CUSTEIO",):
        CostClass.objects.get_or_create(name=nome)
    for nome in ("DESPESA GADO", "FRETE", "COMISSÃO", "IMPOSTO E TAXAS"):
        CostCenter.objects.get_or_create(name=nome)

    usuario = User.objects.create_user(username="dupla", password="x", role=Role.GESTOR)
    company = Company.objects.create(name="Fazendas Reunidas")
    Season.objects.create(
        company=company,
        name="2025/2026",
        start_date=datetime.date(2025, 7, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    farm = Farm.objects.create(name="São Francisco", code="SFR")
    categoria = AnimalCategory.objects.create(name="Machos Desm.", sex=Sex.MACHO)
    compra = services.criar_compra(
        usuario=usuario,
        date=DATA,
        destination_farm=farm,
        category=categoria,
        head_count=126,
        animal_value=D("388080"),
    )

    resultados = []
    barreira = threading.Barrier(2)

    def clicar():
        barreira.wait()
        try:
            services.confirmar_compra(compra, usuario=usuario)
            resultados.append("ok")
        except BusinessError:
            resultados.append("erro")
        finally:
            connection.close()

    threads = [threading.Thread(target=clicar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(resultados) == ["erro", "ok"]
    assert HerdMovement.objects.filter(origin_purchase=compra).count() == 1
    assert CostEntry.objects.filter(source_purchase=compra).count() == 1
    assert Lot.objects.count() == 1


DATA = datetime.date(2025, 9, 18)


# --------------------------------------------------------------------------
# F2-07 — editar, excluir e restaurar com cascata
# --------------------------------------------------------------------------


class TestEdicao:
    def test_editar_confirmada_corrige_saldo_e_custos_e_o_saldo_na_data_original(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        services.editar_compra(
            compra,
            {"head_count": 120, "animal_value": D("369600.00")},
            usuario=escritorio,
            motivo="Contagem corrigida no curral",
        )

        compra.refresh_from_db()
        assert compra.version == 2
        assert saldo_do_lote(compra) == 120
        # O fato foi em 18/09: o saldo de setembro sempre foi 120, não 126.
        assert (
            herd.saldo(lot=compra.lot, until=datetime.date(2025, 9, 30))["head_count"]
            == 120
        )
        ativos = compra.cost_entries.filter(status=Status.CONFIRMADA)
        assert [c.amount for c in ativos] == [D("369600.00")]
        assert compra.cost_entries.filter(status=Status.EXCLUIDA).count() == 1
        # O movimento é o mesmo documento, reaplicado
        assert compra.movements.count() == 1

    def test_editar_confirmada_sem_motivo_e_recusado(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        with pytest.raises(BusinessError, match="Motivo"):
            services.editar_compra(
                compra, {"head_count": 120}, usuario=escritorio, motivo=" "
            )
        assert saldo_do_lote(compra) == 126

    def test_editar_registra_auditoria_com_motivo_before_e_after(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        services.editar_compra(
            compra, {"head_count": 120}, usuario=escritorio, motivo="Contagem"
        )

        evento = AuditEvent.objects.get(
            entity_type="Purchase", entity_id=str(compra.pk), action="UPDATE"
        )
        assert evento.reason == "Contagem"
        assert evento.before["head_count"] == 126
        assert evento.after["head_count"] == 120
        assert "head_count" in evento.changed_fields

    def test_adicionar_valor_acessorio_gera_o_custo_novo(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        services.editar_compra(
            compra,
            {"freight_value": D("4500")},
            usuario=escritorio,
            motivo="Faltou o frete",
        )

        ativos = compra.cost_entries.filter(status=Status.CONFIRMADA)
        assert sorted(c.amount for c in ativos) == [D("4500"), D("388080.00")]

    def test_reduzir_cabecas_quando_animais_ja_sairam_e_bloqueado_com_o_caminho(
        self,
        criar,
        escritorio,
        gestor,
        dados_compra,
        categoria_desmamados,
        sao_francisco,
    ):
        compra = confirmada(criar, escritorio, dados_compra)
        herd.registrar_movimento(
            type=MovementType.VENDA,
            date=datetime.date(2025, 9, 20),
            quantity=100,
            usuario=gestor,
            origin_farm=sao_francisco,
            origin_lot=compra.lot,
            origin_category=categoria_desmamados,
        )

        with pytest.raises(BlockingDependencyError, match="já saíram do lote"):
            services.editar_compra(
                compra, {"head_count": 50}, usuario=escritorio, motivo="Contagem"
            )
        assert saldo_do_lote(compra) == 26  # nada mudou


class TestExclusao:
    def test_excluir_desfaz_os_quatro_efeitos(
        self, criar, escritorio, gestor, dados_compra
    ):
        compra = confirmada(
            criar,
            escritorio,
            {**dados_compra, "freight_value": D("4500")},
        )
        lote = compra.lot

        services.excluir_compra(compra, usuario=gestor, motivo="Duplicada — mesma nota")

        compra.refresh_from_db()
        lote.refresh_from_db()
        assert compra.status == Status.EXCLUIDA
        assert herd.saldo(lot=lote)["head_count"] == 0  # movimento desfeito
        assert compra.movements.get().status == Status.EXCLUIDA
        assert not compra.cost_entries.filter(status=Status.CONFIRMADA).exists()
        assert lote.status == LotStatus.EXCLUIDO  # criado por ela, sem mais nada
        # Nada saiu do banco
        assert Purchase.objects.filter(pk=compra.pk).exists()
        assert CostEntry.objects.filter(source_purchase=compra).count() == 2

    def test_a_compensacao_leva_a_data_do_fato_original(
        self, criar, escritorio, gestor, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        services.excluir_compra(compra, usuario=gestor, motivo="Duplicada")

        datas = set(compra.movements.get().entries.values_list("date", flat=True))
        assert datas == {DATA}

    def test_excluir_em_lote_preexistente_nao_exclui_o_lote(
        self, criar, escritorio, gestor, dados_compra, lote_sao_francisco
    ):
        compra = confirmada(
            criar, escritorio, {**dados_compra, "lot": lote_sao_francisco}
        )

        services.excluir_compra(compra, usuario=gestor, motivo="Duplicada")

        lote_sao_francisco.refresh_from_db()
        assert lote_sao_francisco.status == LotStatus.ABERTO

    def test_excluir_exige_motivo(self, criar, escritorio, gestor, dados_compra):
        compra = confirmada(criar, escritorio, dados_compra)

        with pytest.raises(BusinessError, match="Motivo"):
            services.excluir_compra(compra, usuario=gestor, motivo="")

    def test_escritorio_nao_exclui_compra_confirmada(
        self, criar, escritorio, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)

        with pytest.raises(BusinessError, match="permissão para excluir"):
            services.excluir_compra(compra, usuario=escritorio, motivo="x")

    def test_escritorio_exclui_o_proprio_rascunho(
        self, criar, escritorio, dados_compra
    ):
        compra = criar(**dados_compra)

        services.excluir_compra(compra, usuario=escritorio, motivo="Errei")

        compra.refresh_from_db()
        assert compra.status == Status.EXCLUIDA

    def test_com_dependente_e_sem_cascata_recusa_listando_os_dependentes(
        self,
        criar,
        escritorio,
        gestor,
        dados_compra,
        categoria_desmamados,
        sao_francisco,
    ):
        compra = confirmada(criar, escritorio, dados_compra)
        morte = herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 9, 20),
            quantity=2,
            usuario=gestor,
            origin_farm=sao_francisco,
            origin_lot=compra.lot,
            origin_category=categoria_desmamados,
            reason="Causa desconhecida",
        )

        with pytest.raises(DependencyError) as erro:
            services.excluir_compra(compra, usuario=gestor, motivo="Duplicada")

        assert morte in erro.value.dependents
        compra.refresh_from_db()
        assert compra.status == Status.CONFIRMADA  # nada foi desfeito

    def test_em_cascata_desfaz_a_compra_e_o_que_dependia_dela(
        self,
        criar,
        escritorio,
        gestor,
        dados_compra,
        categoria_desmamados,
        sao_francisco,
    ):
        compra = confirmada(criar, escritorio, dados_compra)
        morte = herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 9, 20),
            quantity=2,
            usuario=gestor,
            origin_farm=sao_francisco,
            origin_lot=compra.lot,
            origin_category=categoria_desmamados,
            reason="Causa desconhecida",
        )

        services.excluir_compra(
            compra, usuario=gestor, motivo="Duplicada", cascata=True
        )

        morte.refresh_from_db()
        assert morte.status == Status.EXCLUIDA
        assert herd.saldo(lot=compra.lot)["head_count"] == 0
        eventos = AuditEvent.objects.filter(action="DELETE", cascade_root__isnull=False)
        assert eventos.values("cascade_root").distinct().count() == 1
        assert eventos.filter(entity_type="HerdMovement").count() >= 2

    def test_em_cascata_se_um_dependente_nao_puder_ser_desfeito_nada_e_alterado(
        self,
        criar,
        escritorio,
        gestor,
        dados_compra,
        categoria_desmamados,
        sao_francisco,
        season,
    ):
        """Tudo ou nada: safra encerrada bloqueia o dependente → a compra fica."""
        compra = confirmada(criar, escritorio, dados_compra)
        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 9, 20),
            quantity=2,
            usuario=gestor,
            origin_farm=sao_francisco,
            origin_lot=compra.lot,
            origin_category=categoria_desmamados,
            reason="x",
        )
        season.status = SeasonStatus.ENCERRADA
        season.save()

        with pytest.raises(BlockingDependencyError, match="reabrir a safra"):
            services.excluir_compra(
                compra, usuario=gestor, motivo="Duplicada", cascata=True
            )

        compra.refresh_from_db()
        assert compra.status == Status.CONFIRMADA
        assert herd.saldo(lot=compra.lot)["head_count"] == 124

    def test_lote_preexistente_com_animais_que_ja_sairam_bloqueia_explicando(
        self,
        criar,
        escritorio,
        gestor,
        dados_compra,
        lote_sao_francisco,
        categoria_desmamados,
        sao_francisco,
    ):
        """Sem dependente declarável (o lote não é da compra), a checagem de
        saldo bloqueia e diz o que fazer."""
        compra = confirmada(
            criar, escritorio, {**dados_compra, "lot": lote_sao_francisco}
        )
        herd.registrar_movimento(
            type=MovementType.VENDA,
            date=datetime.date(2025, 9, 20),
            quantity=126,
            usuario=gestor,
            origin_farm=sao_francisco,
            origin_lot=lote_sao_francisco,
            origin_category=categoria_desmamados,
        )

        with pytest.raises(BlockingDependencyError) as erro:
            services.excluir_compra(compra, usuario=gestor, motivo="Duplicada")

        assert "Saldo insuficiente" in str(erro.value)
        assert "Desfaça antes as saídas" in str(erro.value)
        compra.refresh_from_db()
        assert compra.status == Status.CONFIRMADA

    def test_restaurar_reaplica_exatamente_os_efeitos(
        self, criar, escritorio, gestor, dados_compra
    ):
        compra = confirmada(
            criar, escritorio, {**dados_compra, "freight_value": D("4500")}
        )
        lote = compra.lot
        services.excluir_compra(compra, usuario=gestor, motivo="Engano")

        services.restaurar_compra(compra, usuario=gestor)

        compra.refresh_from_db()
        lote.refresh_from_db()
        assert compra.status == Status.CONFIRMADA
        assert lote.status == LotStatus.ABERTO
        assert herd.saldo(lot=lote)["head_count"] == 126
        ativos = compra.cost_entries.filter(status=Status.CONFIRMADA)
        assert sorted(c.amount for c in ativos) == [D("4500"), D("388080.00")]

    def test_safra_encerrada_bloqueia_exclusao(
        self, criar, escritorio, gestor, dados_compra, season
    ):
        compra = confirmada(criar, escritorio, dados_compra)
        season.status = SeasonStatus.ENCERRADA
        season.save()

        with pytest.raises(BlockingDependencyError, match="encerrada"):
            services.excluir_compra(compra, usuario=gestor, motivo="x")


# --------------------------------------------------------------------------
# Telas
# --------------------------------------------------------------------------


class TestTelas:
    def _post(self, **extra):
        return {
            "date": "2025-09-18",
            "destination_farm": "",
            "category": "",
            "head_count": "126",
            "animal_value": "388080.00",
            "acao": "confirmar",
            **extra,
        }

    def test_confirma_pela_tela_e_diz_o_que_aconteceu(
        self, client, escritorio, sao_francisco, categoria_desmamados
    ):
        client.force_login(escritorio)

        resposta = client.post(
            reverse("purchases:nova"),
            self._post(
                destination_farm=sao_francisco.pk, category=categoria_desmamados.pk
            ),
            follow=True,
        )

        assert resposta.status_code == 200
        mensagens = [str(m) for m in resposta.context["messages"]]
        assert any(
            "126 cabeças deram entrada no lote LT-SFR-001" in m for m in mensagens
        )

    def test_erro_de_negocio_aparece_na_tela_sem_perder_o_digitado(
        self, client, escritorio, sao_francisco, categoria_desmamados
    ):
        client.force_login(escritorio)

        resposta = client.post(
            reverse("purchases:nova"),
            self._post(
                destination_farm=sao_francisco.pk,
                category=categoria_desmamados.pk,
                date="2999-01-01",
            ),
        )

        assert resposta.status_code == 200
        assert "futura" in resposta.content.decode()
        assert 'value="126"' in resposta.content.decode()

    def test_previa_de_custo_vem_do_servico(self, client, escritorio):
        client.force_login(escritorio)

        resposta = client.get(
            reverse("purchases:previa_custo"),
            {"head_count": "105", "animal_value": "260172.15"},
        )

        html = resposta.content.decode()
        assert "R$ 260.172,15" in html
        assert "R$ 2.477,83" in html

    def test_movimento_gerado_por_compra_nao_edita_direto(
        self, client, criar, escritorio, gestor, dados_compra
    ):
        compra = confirmada(criar, escritorio, dados_compra)
        movimento = compra.movements.get()
        client.force_login(gestor)

        resposta = client.get(reverse("herd:movimento_editar", args=[movimento.pk]))

        assert resposta.status_code == 302
        assert resposta.url == reverse("purchases:detalhe", args=[compra.pk])
        resposta = client.post(
            reverse("herd:movimento_excluir", args=[movimento.pk]), {"motivo": "x"}
        )
        movimento.refresh_from_db()
        assert movimento.status == Status.CONFIRMADA

    def test_exclusao_mostra_a_analise_de_impacto_antes(
        self, client, criar, escritorio, gestor, dados_compra
    ):
        compra = confirmada(
            criar, escritorio, {**dados_compra, "freight_value": D("4500")}
        )
        client.force_login(gestor)

        html = client.get(
            reverse("purchases:excluir", args=[compra.pk])
        ).content.decode()

        assert "Isto vai desfazer" in html
        assert "entrada de 126 cabeças" in html
        assert "DESPESA GADO" in html
        assert "criado por esta compra" in html

    def test_exclusao_com_dependente_pede_cascata_explicita(
        self,
        client,
        criar,
        escritorio,
        gestor,
        dados_compra,
        categoria_desmamados,
        sao_francisco,
    ):
        compra = confirmada(criar, escritorio, dados_compra)
        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 9, 20),
            quantity=2,
            usuario=gestor,
            origin_farm=sao_francisco,
            origin_lot=compra.lot,
            origin_category=categoria_desmamados,
            reason="x",
        )
        client.force_login(gestor)

        html = client.get(
            reverse("purchases:excluir", args=[compra.pk])
        ).content.decode()
        assert "dependem deste" in html
        assert "Excluir em cascata" in html

        sem = client.post(
            reverse("purchases:excluir", args=[compra.pk]), {"motivo": "dup"}
        )
        compra.refresh_from_db()
        assert compra.status == Status.CONFIRMADA
        assert sem.status_code == 200

        com = client.post(
            reverse("purchases:excluir", args=[compra.pk]),
            {"motivo": "dup", "cascata": "1"},
        )
        compra.refresh_from_db()
        assert com.status_code == 302
        assert compra.status == Status.EXCLUIDA

    def test_compra_de_outra_fazenda_devolve_404(
        self, client, criar, escritorio, campo_baixao, dados_compra
    ):
        compra = criar(**dados_compra)  # São Francisco
        client.force_login(campo_baixao)  # só enxerga o Baixão

        assert (
            client.get(reverse("purchases:detalhe", args=[compra.pk])).status_code
            == 404
        )
        assert (
            client.get(reverse("purchases:excluir", args=[compra.pk])).status_code
            == 404
        )

    def test_campo_nao_abre_o_formulario_de_compra(self, client, campo_baixao):
        client.force_login(campo_baixao)

        assert client.get(reverse("purchases:nova")).status_code == 403


# --------------------------------------------------------------------------
# Tela do lote: o financeiro deixa de ser "—" quando há compra
# --------------------------------------------------------------------------


class TestFinanceiroDoLote:
    def test_aquisicao_e_custo_por_cabeca_vem_da_compra(
        self, criar, escritorio, dados_compra
    ):
        from apps.livestock.selectors import detalhe_do_lote

        compra = confirmada(
            criar, escritorio, {**dados_compra, "freight_value": D("4500")}
        )

        financeiro = detalhe_do_lote(compra.lot)["financeiro"]

        assert financeiro["aquisicao"] == D("392580.00")
        # Os custos gerados pela compra já estão na aquisição: não contam duas vezes
        assert financeiro["custos_diretos"] is None
        assert financeiro["custo_total"] == D("392580.00")
        assert financeiro["custo_por_cabeca"] == D("392580.00") / 126
        assert financeiro["custo_por_arroba"] is None  # falta peso de carcaça

    def test_custo_direto_avulso_soma_ao_total(
        self,
        criar,
        escritorio,
        gestor,
        dados_compra,
        centro_funcionario,
        custeio,
        sao_francisco,
    ):
        from apps.costs import services as costs
        from apps.livestock.selectors import detalhe_do_lote

        compra = confirmada(criar, escritorio, dados_compra)
        costs.registrar_custo(
            date=datetime.date(2025, 9, 25),
            farm=sao_francisco,
            cost_center=centro_funcionario,
            cost_class=custeio,
            amount=D("1000.00"),
            description="Vacina do lote",
            usuario=gestor,
            lot=compra.lot,
        )

        financeiro = detalhe_do_lote(compra.lot)["financeiro"]

        assert financeiro["custos_diretos"] == D("1000.00")
        assert financeiro["custo_total"] == D("389080.00")
