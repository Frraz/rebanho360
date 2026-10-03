"""F3-09 — o painel: pendências em primeiro lugar, indicador sem dado é "—",
e o mesmo número que o resto do sistema mostra para o mesmo indicador."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.dashboards import selectors
from apps.herd import services as herd
from apps.herd.models import MovementType, WeighingReason
from apps.herd.mortality import taxa_de_mortalidade
from apps.imports.models import (
    BatchStatus,
    ImportBatch,
    ImportKind,
    ImportRow,
    RowStatus,
)
from apps.sales import result
from apps.sales.tests.conftest import vender

pytestmark = pytest.mark.django_db

D = Decimal
HOJE = datetime.date(2025, 8, 20)


def chaves(user, **kw):
    kw.setdefault("hoje", HOJE)
    return {p.chave: p for p in selectors.pendencias_do_painel(user, **kw)}


class TestPendencias:
    def test_sem_nada_nao_ha_pendencia(self, gestor):
        assert selectors.pendencias_do_painel(gestor, hoje=HOJE) == []

    def test_venda_sem_carcaca(self, gestor, criar, confirmar, dados_abate):
        confirmar(criar(**{**dados_abate, "carcass_weight_kg": None}))

        p = chaves(gestor)["sem_carcaca"]

        assert p.texto == "1 venda sem peso de carcaça"
        assert "?sem_carcaca=1" in p.url

    def test_venda_com_carcaca_nao_e_pendencia(
        self, gestor, criar, confirmar, dados_abate
    ):
        confirmar(criar(**dados_abate))
        assert "sem_carcaca" not in chaves(gestor)

    def test_venda_vivo_nunca_e_sem_carcaca(
        self, gestor, criar, confirmar, dados_abate
    ):
        confirmar(criar(**{**dados_abate, "type": "VENDA", "carcass_weight_kg": None}))
        assert "sem_carcaca" not in chaves(gestor)

    def test_rendimento_fora_da_faixa(self, gestor, criar, confirmar, dados_abate):
        confirmar(criar(**{**dados_abate, "carcass_weight_kg": D("15000")}))  # 34%

        p = chaves(gestor)["rendimento"]

        assert p.texto == "1 venda com rendimento fora da faixa"
        assert "34,45%" in p.exemplos[0]

    def test_rendimento_dentro_da_faixa_nao_aparece(
        self, gestor, criar, confirmar, dados_abate
    ):
        confirmar(criar(**dados_abate))  # 51,33%
        assert "rendimento" not in chaves(gestor)

    def test_lote_a_saldo_zero_ainda_aberto(
        self, gestor, escritorio, lote_gordo, sao_francisco, categoria_25_36
    ):
        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 7, 20),
            quantity=100,
            usuario=escritorio,
            origin_farm=sao_francisco,
            origin_lot=lote_gordo,
            origin_category=categoria_25_36,
            reason="Enchente",
        )

        p = chaves(gestor)["zerado_aberto"]

        assert p.texto == "1 lote a saldo zero ainda aberto"
        assert "LT-SFR-010" in p.exemplos[0]

    def test_lote_que_nunca_teve_animal_nao_e_zerado(
        self, gestor, sao_francisco, season
    ):
        from apps.livestock.models import Lot

        Lot.objects.create(
            code="LT-SFR-777",
            farm=sao_francisco,
            season=season,
            entry_date=datetime.date(2025, 7, 1),
        )
        assert "zerado_aberto" not in chaves(gestor)

    def test_lote_encerrado_pela_venda_nao_e_pendencia(
        self, gestor, criar, confirmar, dados_abate
    ):
        confirmar(criar(**{**dados_abate, "head_count": 100}))  # zera e encerra
        assert "zerado_aberto" not in chaves(gestor)

    def test_lote_sem_pesagem_ha_mais_de_90_dias(self, gestor, lote_gordo):
        p = chaves(gestor, hoje=datetime.date(2025, 12, 1))["sem_pesagem"]

        assert p.texto == "1 lote sem pesagem há mais de 90 dias"
        assert "nunca pesado" in p.exemplos[0] and "LT-SFR-010" in p.exemplos[0]

    def test_lote_pesado_recentemente_nao_aparece(
        self, gestor, escritorio, lote_gordo, sao_francisco
    ):
        herd.registrar_pesagem(
            date=datetime.date(2025, 11, 20),
            farm=sao_francisco,
            lot=lote_gordo,
            reason=WeighingReason.CONFERENCIA,
            head_count=10,
            total_weight_kg=D("5000"),
            usuario=escritorio,
        )
        assert "sem_pesagem" not in chaves(gestor, hoje=datetime.date(2025, 12, 1))

    def test_lote_novo_sem_pesagem_ainda_nao_e_pendencia(self, gestor, lote_gordo):
        assert "sem_pesagem" not in chaves(gestor, hoje=datetime.date(2025, 8, 20))

    def test_mortalidade_acima_do_limite(
        self, gestor, escritorio, lote_gordo, sao_francisco, categoria_25_36, season
    ):
        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 7, 25),
            quantity=3,
            usuario=escritorio,
            origin_farm=sao_francisco,
            origin_lot=lote_gordo,
            origin_category=categoria_25_36,
            reason="Picada de cobra",
        )

        p = chaves(gestor, season=season, hoje=datetime.date(2025, 7, 31))[
            "mortalidade"
        ]

        assert p.texto == "1 fazenda com mortalidade acima do normal"
        assert "São Francisco" in p.exemplos[0] and "limite 2%" in p.exemplos[0]

    def test_mortalidade_dentro_do_limite_nao_aparece(
        self, gestor, escritorio, lote_gordo, sao_francisco, categoria_25_36, season
    ):
        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 7, 25),
            quantity=1,
            usuario=escritorio,
            origin_farm=sao_francisco,
            origin_lot=lote_gordo,
            origin_category=categoria_25_36,
            reason="Doença",
        )
        assert "mortalidade" not in chaves(
            gestor, season=season, hoje=datetime.date(2025, 7, 31)
        )

    def test_transferencia_da_planilha_sem_par_aparece_para_quem_importa(
        self, gestor, campo_baixao
    ):
        lote = ImportBatch.objects.create(
            kind=ImportKind.MOVIMENTACOES,
            original_name="x.xlsx",
            file_hash="a" * 64,
            created_by=gestor,
        )
        ImportRow.objects.create(
            batch=lote,
            sheet="GOIANO",
            row_number=20,
            status=RowStatus.PENDENTE,
            raw={"tipo": "TRANSF. S", "quantidade": 95},
        )

        assert chaves(gestor)["transferencias"].quantidade == 1
        # Campo não importa planilha: não vê a pendência da importação.
        assert "transferencias" not in chaves(campo_baixao)

    def test_importacao_cancelada_nao_gera_pendencia(self, gestor):
        lote = ImportBatch.objects.create(
            kind=ImportKind.MOVIMENTACOES,
            original_name="x.xlsx",
            file_hash="b" * 64,
            created_by=gestor,
            status=BatchStatus.CANCELADO,
        )
        ImportRow.objects.create(
            batch=lote,
            sheet="GOIANO",
            row_number=20,
            status=RowStatus.PENDENTE,
            raw={"tipo": "TRANSF. S", "quantidade": 95},
        )
        assert "transferencias" not in chaves(gestor)

    def test_custo_sem_centro_vem_das_linhas_pendentes_da_planilha(self, gestor):
        lote = ImportBatch.objects.create(
            kind=ImportKind.CUSTOS,
            original_name="c.xlsx",
            file_hash="c" * 64,
            created_by=gestor,
        )
        for n in (1, 2):
            ImportRow.objects.create(
                batch=lote,
                sheet="CUSTOS",
                row_number=n,
                status=RowStatus.PENDENTE,
                messages=[{"nivel": "pendencia", "campo": "cost_center", "texto": "x"}],
            )
        ImportRow.objects.create(  # pendente por outro motivo: não conta
            batch=lote,
            sheet="CUSTOS",
            row_number=3,
            status=RowStatus.PENDENTE,
            messages=[{"nivel": "pendencia", "campo": "description", "texto": "x"}],
        )

        assert chaves(gestor)["custos_sem_centro"].quantidade == 2

    def test_as_pendencias_respeitam_o_escopo_de_fazenda(
        self, campo_baixao, criar, confirmar, dados_abate
    ):
        """A venda sem carcaça é de São Francisco; o campo só tem o Baixão."""
        confirmar(criar(**{**dados_abate, "carcass_weight_kg": None}))
        assert chaves(campo_baixao) == {}

    def test_filtrar_por_fazenda_so_considera_a_escolhida(
        self, gestor, baixao, criar, confirmar, dados_abate
    ):
        confirmar(criar(**{**dados_abate, "carcass_weight_kg": None}))
        assert "sem_carcaca" not in chaves(gestor, farm=baixao)


class TestCartoes:
    def test_painel_vazio_nao_inventa_numero(self, gestor, season):
        rebanho = selectors.cartao_do_rebanho(gestor, hoje=HOJE)
        safra = selectors.cartao_da_safra(gestor, season=season, cabecas_atuais=0)

        assert rebanho.cabecas == 0
        assert safra.custo_por_cabeca is None  # sem rebanho, sem custo/cabeça
        assert safra.custo_por_arroba is None

    def test_cartao_do_rebanho(self, gestor, lote_gordo):
        r = selectors.cartao_do_rebanho(gestor, hoje=datetime.date(2025, 7, 31))

        assert r.cabecas == 100 and r.fazendas == 1 and r.lotes_abertos == 1
        assert r.entradas_do_mes == 100 and r.saidas_do_mes == 0

    def test_saidas_do_mes_contam_venda_e_morte(
        self, gestor, criar, confirmar, dados_abate
    ):
        confirmar(criar(**dados_abate))
        r = selectors.cartao_do_rebanho(gestor, hoje=datetime.date(2025, 8, 20))
        assert r.saidas_do_mes == 84 and r.cabecas == 16

    def test_o_custo_por_arroba_do_painel_e_o_mesmo_da_tela_do_lote(
        self, gestor, escritorio, lote_de_compra, frigorifico, categoria_25_36, season
    ):
        """Relatório e dashboard mostram o mesmo número para o mesmo indicador."""
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        lote_de_compra.refresh_from_db()

        safra = selectors.cartao_da_safra(gestor, season=season, cabecas_atuais=0)
        do_lote = result.resultado_do_lote(lote_de_compra)

        assert safra.custo_por_arroba == do_lote.custo_por_arroba == D("168.75")
        assert safra.lotes_encerrados == 1

    def test_comprado_e_vendido_da_safra(
        self, gestor, escritorio, lote_de_compra, frigorifico, categoria_25_36, season
    ):
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)

        safra = selectors.cartao_da_safra(gestor, season=season, cabecas_atuais=0)

        assert (safra.comprado_cabecas, safra.comprado_valor) == (100, D("250000"))
        assert (safra.vendido_cabecas, safra.vendido_valor) == (100, D("480000"))
        # Só os avulsos (3.000 + 12.000): os 255.000 da compra já estão em
        # "Comprado" — contar de novo dobraria a aquisição.
        assert safra.custos == D("15000")

    def test_custo_por_cabeca_e_custos_sobre_o_rebanho_atual(
        self, gestor, lote_de_compra, season
    ):
        safra = selectors.cartao_da_safra(gestor, season=season, cabecas_atuais=100)
        assert safra.custo_por_cabeca == D("150")  # 15.000 ÷ 100


class TestMortalidade:
    def test_sem_rebanho_a_taxa_e_none_nao_zero(self, sao_francisco):
        t = taxa_de_mortalidade(
            farm=sao_francisco,
            start=datetime.date(2025, 7, 1),
            end=datetime.date(2025, 7, 31),
        )
        assert t.taxa is None and t.saldo_medio is None and t.mortes == 0

    def test_taxa_e_mortes_sobre_o_saldo_medio_diario(
        self, escritorio, lote_gordo, sao_francisco, categoria_25_36
    ):
        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 7, 25),
            quantity=3,
            usuario=escritorio,
            origin_farm=sao_francisco,
            origin_lot=lote_gordo,
            origin_category=categoria_25_36,
            reason="x",
        )
        t = taxa_de_mortalidade(
            farm=sao_francisco,
            start=datetime.date(2025, 7, 1),
            end=datetime.date(2025, 7, 31),
        )
        # 100 cabeças de 10 a 24/07 (15 dias) e 97 de 25 a 31/07 (7 dias):
        # (100 × 15 + 97 × 7) = 2.179 cabeça-dia ÷ 31 dias = 70,29 de saldo
        # médio; 3 ÷ 70,29 = 4,27%.
        assert t.mortes == 3
        assert round(t.saldo_medio, 2) == D("70.29")
        assert round(t.taxa, 2) == D("4.27")


class TestTela:
    def test_pendencias_vem_antes_do_resto(self, client, gestor, lote_gordo):
        client.force_login(gestor)
        html = client.get(reverse("dashboards:inicio")).content.decode()

        # Os `id` das seções: "Rebanho" também aparece no menu lateral.
        assert (
            html.index('id="titulo-pendencias"')
            < html.index('id="titulo-rebanho"')
            < html.index('id="titulo-safra"')
            < html.index('id="titulo-ultimos"')
        )

    def test_indicador_sem_dado_e_travessao_nunca_zero(self, client, gestor, season):
        client.force_login(gestor)
        html = client.get(reverse("dashboards:inicio")).content.decode()

        assert "Nada pendente hoje" in html
        assert "Custo/@ (lotes encerrados)" in html
        assert "nenhum lote encerrou na safra ainda" in html
        assert "R$ 0,00" in html  # custos da safra: soma de nada É zero…
        # …mas custo/cabeça e custo/@ sem base NÃO viram R$ 0,00.
        assert html.count("—") >= 2

    def test_tela_mostra_pendencia_com_link(
        self, client, gestor, criar, confirmar, dados_abate
    ):
        confirmar(criar(**{**dados_abate, "carcass_weight_kg": None}))
        client.force_login(gestor)

        html = client.get(reverse("dashboards:inicio")).content.decode()

        assert "1 venda sem peso de carcaça" in html
        assert "sem_carcaca=1" in html

    def test_ultimos_lancamentos_com_escopo(
        self, client, gestor, campo_baixao, criar, confirmar, dados_abate
    ):
        confirmar(criar(**dados_abate))

        client.force_login(gestor)
        assert (
            "VD-2025/26-0001"
            in client.get(reverse("dashboards:inicio")).content.decode()
        )

        client.force_login(campo_baixao)
        assert (
            "VD-2025/26-0001"
            not in client.get(reverse("dashboards:inicio")).content.decode()
        )

    def test_precisa_de_login(self, client):
        resposta = client.get(reverse("dashboards:inicio"))
        assert resposta.status_code == 302


def test_o_painel_nao_calcula_no_template():
    """Template não calcula: nenhum filtro aritmético no painel."""
    import pathlib

    html = pathlib.Path("templates/dashboards/inicio.html").read_text()
    for proibido in ("|add:", "|mul", "|div", "widthratio"):
        assert proibido not in html
