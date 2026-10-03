"""F3-01 a F3-04 — venda e abate: modelo, `CarcassService`, confirmação
transacional, edição e exclusão. Ver docs/regras-negocio/04-venda-e-abate.md
e 06-edicao-exclusao-e-auditoria.md."""

import datetime
import threading
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction

from apps.audit.models import AuditEvent
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.money import quantize_arroba, quantize_money, quantize_percent
from apps.core.reversible import Status
from apps.herd import services as herd
from apps.herd.models import HerdLedgerEntry, HerdMovement, MovementType
from apps.livestock.models import LotStatus
from apps.organizations.models import SeasonStatus
from apps.sales import carcass, services
from apps.sales.models import Sale, SaleType
from apps.sales.tests.conftest import DATA_VENDA

pytestmark = pytest.mark.django_db

D = Decimal


def saldo(lote):
    return herd.saldo(lot=lote)["head_count"]


# --------------------------------------------------------------------------
# F3-01 — modelo
# --------------------------------------------------------------------------


class TestModelo:
    def test_nenhum_dos_sete_derivados_da_planilha_e_campo(self):
        """Peso médio, carcaça média, rendimento, valor/cabeça, valor/@, mês e
        ano: a planilha grava os sete como valor. Aqui nenhum existe."""
        campos = {f.name for f in Sale._meta.get_fields()}
        for derivado in (
            "average_weight_kg",
            "average_weight",
            "avg_weight_kg",
            "carcass_average",
            "average_carcass_kg",
            "yield_pct",
            "yield_percent",
            "yield",
            "dressing",
            "value_per_head",
            "value_per_arroba",
            "price_per_arroba",
            "month",
            "year",
        ):
            assert derivado not in campos

    def test_codigo_por_safra(self, criar, dados_abate):
        primeira = criar(**dados_abate)
        segunda = criar(**dados_abate)

        assert primeira.code == "VD-2025/26-0001"
        assert segunda.code == "VD-2025/26-0002"

    def test_nasce_em_rascunho_e_nao_mexe_no_rebanho(
        self, criar, dados_abate, lote_gordo
    ):
        venda = criar(**dados_abate)

        assert venda.status == Status.RASCUNHO
        assert saldo(lote_gordo) == 100
        assert not HerdMovement.objects.filter(origin_sale=venda).exists()

    def test_carcaca_so_em_abate_no_banco(self, criar, dados_abate):
        dados = {**dados_abate, "type": "VENDA"}
        with pytest.raises(BusinessError, match="não tem peso de carcaça"):
            criar(**dados)

        # E mesmo contornando o serviço, o banco recusa.
        venda = criar(**{**dados_abate, "carcass_weight_kg": None})
        with pytest.raises(IntegrityError), transaction.atomic():
            Sale.objects.filter(pk=venda.pk).update(
                type=SaleType.VENDA, carcass_weight_kg=D("100")
            )

    def test_carcaca_nao_pode_pesar_mais_que_o_vivo(self, criar, dados_abate):
        with pytest.raises(BusinessError, match="100%"):
            criar(**{**dados_abate, "carcass_weight_kg": D("43540")})

        venda = criar(**dados_abate)
        with pytest.raises(IntegrityError), transaction.atomic():
            Sale.objects.filter(pk=venda.pk).update(carcass_weight_kg=D("50000"))

    @pytest.mark.parametrize(
        "campo,valor",
        [
            ("head_count", 0),
            ("total_weight_kg", D("0")),
            ("total_value", D("0")),
        ],
    )
    def test_quantidade_peso_e_valor_maiores_que_zero(
        self, criar, dados_abate, campo, valor
    ):
        with pytest.raises(BusinessError):
            criar(**{**dados_abate, campo: valor})

    def test_comprador_precisa_ter_papel_de_comprador_ou_frigorifico(
        self, criar, dados_abate, vendedor
    ):
        with pytest.raises(BusinessError, match="Comprador nem de Frigorífico"):
            criar(**{**dados_abate, "buyer": vendedor})

    def test_lote_de_outra_fazenda_e_recusado(self, criar, dados_abate, baixao):
        with pytest.raises(BusinessError, match="é da fazenda"):
            criar(**{**dados_abate, "farm": baixao})

    def test_data_futura_e_recusada(self, criar, dados_abate):
        amanha = datetime.date.today() + datetime.timedelta(days=1)
        with pytest.raises(BusinessError, match="futura"):
            criar(**{**dados_abate, "date": amanha})

    def test_campo_nao_lanca_venda(self, campo_baixao, dados_abate):
        with pytest.raises(BusinessError, match="permissão"):
            services.criar_venda(usuario=campo_baixao, **dados_abate)


# --------------------------------------------------------------------------
# F3-02 — CarcassService
# --------------------------------------------------------------------------


class TestCarcassService:
    def test_os_seis_numeros_do_abate_de_agosto_2025(self, criar, dados_abate):
        """É o teste que trava o serviço: os seis já foram conferidos contra
        a planilha, casa a casa."""
        ind = carcass.indicadores_da_venda(criar(**dados_abate))

        assert quantize_money(ind.peso_medio_vivo) == D("518.33")
        assert quantize_money(ind.carcaca_media) == D("266.08")
        assert quantize_money(ind.rendimento) == D("51.33")
        assert quantize_arroba(ind.arrobas_carcaca) == D("1490.03")
        assert quantize_money(ind.valor_por_cabeca) == D("4779.79")
        assert quantize_money(ind.valor_por_arroba) == D("269.46")

    def test_rendimento_bate_com_a_planilha_a_4_casas(self, criar, dados_abate):
        ind = carcass.indicadores_da_venda(criar(**dados_abate))
        # A planilha guarda 0,5133 (fração); o serviço devolve percentual.
        assert quantize_percent(ind.rendimento / 100) == D("0.5133")

    def test_venda_sem_carcaca_devolve_none_nos_indicadores_de_carcaca(self):
        ind = carcass.calcular_carcaca(
            head_count=84, total_weight_kg=D("43540"), total_value=D("401502.68")
        )

        assert ind.carcaca_media is None
        assert ind.rendimento is None
        assert ind.arrobas_carcaca is None
        assert ind.valor_por_arroba is None
        # O que não depende da carcaça continua existindo.
        assert quantize_money(ind.peso_medio_vivo) == D("518.33")
        assert quantize_money(ind.valor_por_cabeca) == D("4779.79")
        assert ind.valor_por_kg_vivo is not None

    def test_divisor_zero_devolve_none_nunca_erro_nem_zero(self):
        ind = carcass.calcular_carcaca(
            head_count=0,
            total_weight_kg=D("0"),
            total_value=D("100"),
            carcass_weight_kg=D("50"),
        )

        assert ind.peso_medio_vivo is None
        assert ind.carcaca_media is None
        assert ind.rendimento is None  # peso vivo zero
        assert ind.valor_por_cabeca is None
        assert ind.valor_por_kg_vivo is None

    def test_tudo_vazio_e_tudo_none(self):
        ind = carcass.calcular_carcaca(
            head_count=None, total_weight_kg=None, total_value=None
        )
        assert all(v is None for v in vars(ind).values())

    def test_faixa_de_rendimento_e_alerta_nao_bloqueio(self):
        assert carcass.rendimento_fora_da_faixa(D("39.9"))
        assert carcass.rendimento_fora_da_faixa(D("65.1"))
        assert not carcass.rendimento_fora_da_faixa(D("40"))
        assert not carcass.rendimento_fora_da_faixa(D("65"))
        assert not carcass.rendimento_fora_da_faixa(None)
        assert "fora da faixa" in carcass.alertas_de_rendimento(D("30"))[0]
        assert carcass.alertas_de_rendimento(D("51")) == []

    def test_agregado_so_considera_as_vendas_com_carcaca(self, criar, dados_abate):
        com = criar(**dados_abate)
        sem = criar(**{**dados_abate, "carcass_weight_kg": None})

        agregado = carcass.agregar([com, sem])

        assert agregado.vendas == 2
        assert agregado.com_carcaca == 1 and agregado.sem_carcaca == 1
        assert agregado.cabecas == 168
        # O rendimento é o da venda que TEM carcaça: somar o vivo das duas e
        # dividir pela carcaça de uma só daria ~25,7%.
        assert quantize_money(agregado.indicadores.rendimento) == D("51.33")
        assert quantize_money(agregado.indicadores.valor_por_arroba) == D("269.46")

    def test_agregado_sem_nenhuma_carcaca_e_none(self, criar, dados_abate):
        sem = criar(**{**dados_abate, "carcass_weight_kg": None})
        agregado = carcass.agregar([sem])
        assert agregado.indicadores.rendimento is None
        assert agregado.indicadores.valor_por_arroba is None


# --------------------------------------------------------------------------
# F3-03 — confirmação
# --------------------------------------------------------------------------


class TestConfirmacao:
    def test_confirmar_da_saida_no_rebanho(
        self, criar, confirmar, dados_abate, lote_gordo, categoria_25_36
    ):
        venda = confirmar(criar(**dados_abate))

        assert venda.status == Status.CONFIRMADA
        movimento = HerdMovement.objects.get(origin_sale=venda)
        assert movimento.type == MovementType.ABATE
        assert movimento.quantity == 84
        assert movimento.total_weight_kg == D("43540")
        assert movimento.partner == venda.buyer
        assert movimento.date == DATA_VENDA
        assert saldo(lote_gordo) == 16
        assert lote_gordo.status == LotStatus.ABERTO

    def test_venda_de_animal_vivo_gera_movimento_de_venda(
        self, criar, confirmar, dados_abate
    ):
        dados = {**dados_abate, "type": "VENDA", "carcass_weight_kg": None}
        venda = confirmar(criar(**dados))

        assert HerdMovement.objects.get(origin_sale=venda).type == MovementType.VENDA

    def test_saldo_insuficiente_diz_quanto_ha(self, criar, confirmar, dados_abate):
        venda = criar(**{**dados_abate, "head_count": 120})

        with pytest.raises(BusinessError) as exc:
            confirmar(venda)

        assert "Saldo insuficiente: há 100 cabeças de Machos 25 a 36 meses" in str(
            exc.value
        )
        assert "LT-SFR-010" in str(exc.value)
        assert "foram informadas 120" in str(exc.value)
        venda.refresh_from_db()
        assert venda.status == Status.RASCUNHO

    def test_confirmacao_que_falha_nao_deixa_resto(
        self, criar, confirmar, dados_abate, lote_gordo
    ):
        venda = criar(**{**dados_abate, "head_count": 120})
        antes = HerdLedgerEntry.objects.count()

        with pytest.raises(BusinessError):
            confirmar(venda)

        assert HerdLedgerEntry.objects.count() == antes
        assert not HerdMovement.objects.filter(origin_sale=venda).exists()

    def test_confirmar_duas_vezes_e_recusado(self, criar, confirmar, dados_abate):
        venda = confirmar(criar(**dados_abate))
        with pytest.raises(BusinessError, match="já foi confirmada"):
            confirmar(venda)

    def test_abate_sem_carcaca_confirma_e_fica_pendente(
        self, criar, confirmar, dados_abate, lote_gordo
    ):
        """Pendência #13: as cabeças já saíram; o romaneio chega depois."""
        venda = confirmar(criar(**{**dados_abate, "carcass_weight_kg": None}))

        assert venda.status == Status.CONFIRMADA
        assert venda.sem_carcaca
        assert saldo(lote_gordo) == 16
        assert any("sem peso de carcaça" in a for a in services.alertas_da_venda(venda))

    def test_rendimento_fora_da_faixa_alerta_mas_nao_bloqueia(
        self, criar, confirmar, dados_abate
    ):
        venda = confirmar(criar(**{**dados_abate, "carcass_weight_kg": D("15000")}))

        assert venda.status == Status.CONFIRMADA
        assert any("fora da faixa" in a for a in services.alertas_da_venda(venda))

    def test_vender_tudo_encerra_o_lote(
        self, criar, confirmar, dados_abate, lote_gordo
    ):
        confirmar(criar(**{**dados_abate, "head_count": 100}))

        lote_gordo.refresh_from_db()
        assert lote_gordo.status == LotStatus.ENCERRADO
        assert lote_gordo.exit_date == DATA_VENDA
        assert saldo(lote_gordo) == 0

    def test_venda_parcial_nao_encerra(self, criar, confirmar, dados_abate, lote_gordo):
        confirmar(criar(**dados_abate))
        lote_gordo.refresh_from_db()
        assert lote_gordo.status == LotStatus.ABERTO
        assert lote_gordo.exit_date is None

    def test_auditoria_da_confirmacao_e_do_movimento(
        self, criar, confirmar, dados_abate
    ):
        venda = confirmar(criar(**dados_abate))
        tipos = set(AuditEvent.objects.values_list("entity_type", flat=True))

        assert {"Sale", "HerdMovement"} <= tipos
        assert AuditEvent.objects.filter(
            entity_type="Sale", entity_id=str(venda.pk), action="CONFIRM"
        ).exists()

    def test_alerta_quando_peso_da_venda_difere_do_peso_do_razao(
        self, criar, confirmar, dados_abate
    ):
        venda = confirmar(criar(**dados_abate))
        movimento = HerdMovement.objects.get(origin_sale=venda)
        assert services.alertas_da_venda(venda) == []

        HerdMovement.objects.filter(pk=movimento.pk).update(total_weight_kg=D("47040"))
        alertas = services.alertas_da_venda(venda)
        assert any("pendência #12" in a for a in alertas)


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="select_for_update() só bloqueia entre conexões no Postgres.",
)
@pytest.mark.django_db(transaction=True)
def test_duas_vendas_da_mesma_posicao_uma_passa_a_outra_e_barrada():
    """F3-03: fora da transação, duas vendas simultâneas furariam o saldo."""
    from apps.accounts.models import Role, User
    from apps.livestock.models import AnimalCategory, Lot, Sex
    from apps.organizations.models import Company, Season
    from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
    from apps.properties.models import Farm

    usuario = User.objects.create_user(username="dupla", password="x", role=Role.GESTOR)
    company = Company.objects.create(name="Fazendas Reunidas")
    season = Season.objects.create(
        company=company,
        name="2025/2026",
        start_date=datetime.date(2025, 7, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    farm = Farm.objects.create(name="São Francisco", code="SFR")
    categoria = AnimalCategory.objects.create(name="Machos 25 a 36", sex=Sex.MACHO)
    lote = Lot.objects.create(
        code="LT-SFR-001",
        farm=farm,
        season=season,
        entry_date=datetime.date(2025, 7, 1),
    )
    comprador = Partner.objects.create(name="COPERFRIGU")
    PartnerRole.objects.create(partner=comprador, role=PartnerRoleChoice.FRIGORIFICO)
    herd.registrar_movimento(
        type=MovementType.COMPRA,
        date=datetime.date(2025, 7, 2),
        quantity=20,
        usuario=usuario,
        destination_farm=farm,
        destination_lot=lote,
        destination_category=categoria,
    )

    def nova_venda():
        return services.criar_venda(
            usuario=usuario,
            date=datetime.date(2025, 8, 3),
            type="ABATE",
            buyer=comprador,
            farm=farm,
            lot=lote,
            category=categoria,
            head_count=15,
            total_weight_kg=D("8000"),
            total_value=D("90000"),
        )

    vendas = [nova_venda(), nova_venda()]
    resultados = []
    barreira = threading.Barrier(2)

    def vender(venda):
        barreira.wait()
        try:
            services.confirmar_venda(venda, usuario=usuario)
            resultados.append(("ok", ""))
        except BusinessError as exc:
            resultados.append(("erro", str(exc)))
        finally:
            connection.close()

    threads = [threading.Thread(target=vender, args=(v,)) for v in vendas]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(r[0] for r in resultados) == ["erro", "ok"]
    barrada = next(texto for estado, texto in resultados if estado == "erro")
    assert "Saldo insuficiente: há 5 cabeças" in barrada
    assert herd.saldo(lot=lote)["head_count"] == 5
    assert Sale.objects.filter(status=Status.CONFIRMADA).count() == 1
    assert HerdMovement.objects.filter(origin_sale__isnull=False).count() == 1


# --------------------------------------------------------------------------
# F3-04 — editar, excluir, restaurar
# --------------------------------------------------------------------------


class TestEdicaoEExclusao:
    def test_editar_confirmada_exige_motivo(
        self, criar, confirmar, dados_abate, escritorio
    ):
        venda = confirmar(criar(**dados_abate))
        with pytest.raises(BusinessError, match="Motivo é obrigatório"):
            services.editar_venda(
                venda, {"head_count": 80}, usuario=escritorio, motivo="  "
            )

    def test_editar_quantidade_desfaz_e_reaplica(
        self, criar, confirmar, dados_abate, escritorio, lote_gordo
    ):
        venda = confirmar(criar(**dados_abate))

        venda = services.editar_venda(
            venda,
            {"head_count": 80, "total_weight_kg": D("41000")},
            usuario=escritorio,
            motivo="Contagem corrigida no curral",
        )

        assert venda.version == 2
        assert saldo(lote_gordo) == 20
        ativos = HerdMovement.objects.filter(
            origin_sale=venda, status=Status.CONFIRMADA
        )
        assert ativos.count() == 1
        assert ativos.get().quantity == 80
        assert ativos.get().total_weight_kg == D("41000")

    def test_editar_para_alem_do_saldo_desfaz_tudo(
        self, criar, confirmar, dados_abate, escritorio, lote_gordo
    ):
        venda = confirmar(criar(**dados_abate))

        with pytest.raises(BusinessError, match="Saldo insuficiente"):
            services.editar_venda(
                venda,
                {"head_count": 120},
                usuario=escritorio,
                motivo="erro de digitação",
            )

        venda.refresh_from_db()
        assert venda.head_count == 84 and venda.version == 1
        assert saldo(lote_gordo) == 16

    def test_excluir_reabre_o_lote_e_restaura_o_saldo_na_data_original(
        self, criar, confirmar, dados_abate, gestor, lote_gordo
    ):
        """F3-04: excluir venda reabre o lote encerrado e restaura o saldo
        **na data original** — o razão é append-only, a correção vale para
        trás."""
        venda = confirmar(criar(**{**dados_abate, "head_count": 100}))
        lote_gordo.refresh_from_db()
        assert lote_gordo.status == LotStatus.ENCERRADO

        services.excluir_venda(
            venda, usuario=gestor, motivo="Venda lançada em duplicidade"
        )

        lote_gordo.refresh_from_db()
        assert lote_gordo.status == LotStatus.ABERTO
        assert lote_gordo.exit_date is None
        assert saldo(lote_gordo) == 100
        # No dia anterior à venda o saldo já era 100 e continua sendo — e no
        # dia da venda volta a ser 100 (a compensação leva a data original).
        assert herd.saldo(lot=lote_gordo, until=DATA_VENDA)["head_count"] == 100
        compensacoes = HerdLedgerEntry.objects.filter(
            reverses_entry__isnull=False, movement__origin_sale=venda
        )
        assert compensacoes.count() == 1
        assert compensacoes.get().date == DATA_VENDA
        venda.refresh_from_db()
        assert venda.status == Status.EXCLUIDA
        assert venda.delete_reason == "Venda lançada em duplicidade"

    def test_exclusao_nunca_apaga_linha_do_banco(
        self, criar, confirmar, dados_abate, gestor
    ):
        venda = confirmar(criar(**dados_abate))
        services.excluir_venda(venda, usuario=gestor, motivo="engano")

        assert Sale.objects.filter(pk=venda.pk).exists()
        assert HerdMovement.objects.filter(origin_sale=venda).exists()

    def test_exclusao_agrupa_efeitos_na_mesma_cascata_da_auditoria(
        self, criar, confirmar, dados_abate, gestor
    ):
        venda = confirmar(criar(**{**dados_abate, "head_count": 100}))
        services.excluir_venda(venda, usuario=gestor, motivo="engano")

        eventos = AuditEvent.objects.filter(action="DELETE", cascade_root__isnull=False)
        assert {e.entity_type for e in eventos} >= {"Sale", "HerdMovement"}
        assert len({e.cascade_root for e in eventos}) == 1

    def test_escritorio_edita_mas_nao_exclui_confirmada(
        self, criar, confirmar, dados_abate, escritorio
    ):
        venda = confirmar(criar(**dados_abate))
        with pytest.raises(BusinessError, match="permissão para excluir"):
            services.excluir_venda(venda, usuario=escritorio, motivo="x")

    def test_restaurar_reaplica_a_saida_e_reencerra_o_lote(
        self, criar, confirmar, dados_abate, gestor, lote_gordo
    ):
        venda = confirmar(criar(**{**dados_abate, "head_count": 100}))
        services.excluir_venda(venda, usuario=gestor, motivo="engano")

        services.restaurar_venda(venda, usuario=gestor)

        lote_gordo.refresh_from_db()
        assert saldo(lote_gordo) == 0
        assert lote_gordo.status == LotStatus.ENCERRADO
        venda.refresh_from_db()
        assert venda.status == Status.CONFIRMADA

    def test_restaurar_sem_saldo_diz_porque(
        self, criar, confirmar, dados_abate, gestor, escritorio, lote_gordo
    ):
        venda = confirmar(criar(**{**dados_abate, "head_count": 84}))
        services.excluir_venda(venda, usuario=gestor, motivo="engano")
        # Os animais são vendidos de novo, em outra venda.
        confirmar(criar(**{**dados_abate, "head_count": 90}))

        with pytest.raises(BusinessError, match="Saldo insuficiente"):
            services.restaurar_venda(venda, usuario=gestor)

    def test_safra_encerrada_bloqueia_edicao_e_exclusao_explicando(
        self, criar, confirmar, dados_abate, gestor, escritorio, season
    ):
        venda = confirmar(criar(**dados_abate))
        season.status = SeasonStatus.ENCERRADA
        season.save()

        with pytest.raises(
            BlockingDependencyError, match="safra 2025/2026 está encerrada"
        ):
            services.excluir_venda(venda, usuario=gestor, motivo="engano")
        with pytest.raises(BlockingDependencyError):
            services.editar_venda(
                venda, {"head_count": 80}, usuario=escritorio, motivo="contagem"
            )

    def test_rascunho_edita_sem_motivo_e_exclui(self, criar, dados_abate, escritorio):
        venda = criar(**dados_abate)
        venda = services.editar_rascunho(venda, {"head_count": 50}, usuario=escritorio)
        assert venda.head_count == 50 and venda.version == 2

        services.excluir_venda(venda, usuario=escritorio, motivo="desisti")
        venda.refresh_from_db()
        assert venda.status == Status.EXCLUIDA


# --------------------------------------------------------------------------
# Vínculo com a saída que a aba da fazenda já registrou (importação)
# --------------------------------------------------------------------------


class TestVinculoComSaidaExistente:
    def _saida_existente(self, dados_abate, escritorio, peso=D("47040")):
        return herd.registrar_movimento(
            type=MovementType.ABATE,
            date=datetime.date(2025, 8, 3),
            quantity=84,
            total_weight_kg=peso,
            usuario=escritorio,
            origin_farm=dados_abate["farm"],
            origin_lot=dados_abate["lot"],
            origin_category=dados_abate["category"],
        )

    def test_a_venda_adota_a_saida_sem_debitar_de_novo(
        self, criar, confirmar, dados_abate, escritorio, lote_gordo
    ):
        movimento = self._saida_existente(dados_abate, escritorio)
        assert saldo(lote_gordo) == 16

        venda = criar(**dados_abate)
        services.vincular_a_saida_existente(venda, movimento, usuario=escritorio)
        venda = confirmar(venda)

        assert saldo(lote_gordo) == 16  # NÃO virou -68: a saída é a mesma
        movimento.refresh_from_db()
        assert movimento.origin_sale_id == venda.pk
        assert HerdMovement.objects.filter(type=MovementType.ABATE).count() == 1
        # O peso do movimento NÃO foi corrigido em silêncio: vira aviso.
        assert movimento.total_weight_kg == D("47040")
        assert any("pendência #12" in a for a in services.alertas_da_venda(venda))

    def test_excluir_a_venda_adotada_devolve_as_cabecas(
        self, criar, confirmar, dados_abate, escritorio, gestor, lote_gordo
    ):
        movimento = self._saida_existente(dados_abate, escritorio)
        venda = criar(**dados_abate)
        services.vincular_a_saida_existente(venda, movimento, usuario=escritorio)
        venda = confirmar(venda)

        services.excluir_venda(venda, usuario=gestor, motivo="engano")

        assert saldo(lote_gordo) == 100

    def test_editar_a_venda_adotada_sincroniza_o_movimento(
        self, criar, confirmar, dados_abate, escritorio, lote_gordo
    ):
        movimento = self._saida_existente(dados_abate, escritorio)
        venda = criar(**dados_abate)
        services.vincular_a_saida_existente(venda, movimento, usuario=escritorio)
        venda = confirmar(venda)

        services.editar_venda(
            venda, {"notes": "conferido"}, usuario=escritorio, motivo="conferência"
        )

        ativo = HerdMovement.objects.get(origin_sale=venda, status=Status.CONFIRMADA)
        assert ativo.total_weight_kg == D("43540")  # agora o do documento
        assert saldo(lote_gordo) == 16

    def test_nao_vincula_saida_de_outra_quantidade(
        self, criar, dados_abate, escritorio
    ):
        movimento = self._saida_existente(dados_abate, escritorio)
        venda = criar(**{**dados_abate, "head_count": 80})
        with pytest.raises(BusinessError, match="não é a mesma saída"):
            services.vincular_a_saida_existente(venda, movimento, usuario=escritorio)

    def test_nao_vincula_saida_que_ja_tem_dono(
        self, criar, confirmar, dados_abate, escritorio
    ):
        movimento = self._saida_existente(dados_abate, escritorio)
        primeira = criar(**dados_abate)
        services.vincular_a_saida_existente(primeira, movimento, usuario=escritorio)
        segunda = criar(**dados_abate)
        with pytest.raises(BusinessError, match="já pertence a outro documento"):
            services.vincular_a_saida_existente(segunda, movimento, usuario=escritorio)
