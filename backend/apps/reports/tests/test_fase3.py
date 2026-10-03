"""F3-10 — relatórios de vendas, desempenho, resultado e pesagens.

Regra que o teste trava: **todos chamam os serviços de cálculo**; nenhum
reimplementa uma conta. Relatório e tela mostram o mesmo número."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.herd import services as herd
from apps.herd.models import WeighingReason
from apps.reports import services
from apps.sales import carcass, result
from apps.sales.tests.conftest import vender

pytestmark = pytest.mark.django_db

D = Decimal


def linha(relatorio, chave, valor):
    return next(lin for lin in relatorio.linhas if lin[chave] == valor)


class TestVendasEAbates:
    def test_os_seis_numeros_do_abate_de_agosto_no_relatorio(
        self, gestor, criar, confirmar, dados_abate, season
    ):
        confirmar(criar(**dados_abate))

        rel = services.vendas_e_abates(gestor, season=season, farm=None)
        lin = rel.linhas[0]

        assert lin["cabecas"] == 84
        assert round(lin["valor_cabeca"], 2) == D("4779.79")
        assert round(lin["rendimento"], 2) == D("51.33")
        assert round(lin["valor_arroba"], 2) == D("269.46")

    def test_chama_o_carcass_service_nao_reimplementa(
        self, gestor, criar, confirmar, dados_abate, season, monkeypatch
    ):
        confirmar(criar(**dados_abate))
        falso = carcass.IndicadoresDaVenda(
            peso_medio_vivo=None,
            carcaca_media=None,
            rendimento=D("99.99"),
            arrobas_carcaca=None,
            valor_por_cabeca=D("1.11"),
            valor_por_arroba=D("2.22"),
            valor_por_kg_vivo=None,
            arrobas_vivas=None,
        )
        monkeypatch.setattr(services.carcass, "indicadores_da_venda", lambda v: falso)

        lin = services.vendas_e_abates(gestor, season=season, farm=None).linhas[0]

        assert (lin["rendimento"], lin["valor_cabeca"], lin["valor_arroba"]) == (
            D("99.99"),
            D("1.11"),
            D("2.22"),
        )

    def test_venda_sem_carcaca_mostra_travessao_e_avisa(
        self, gestor, criar, confirmar, dados_abate, season
    ):
        confirmar(criar(**{**dados_abate, "carcass_weight_kg": None}))

        rel = services.vendas_e_abates(gestor, season=season, farm=None)
        tela = services.tabela(rel)

        assert rel.linhas[0]["rendimento"] is None
        assert any("sem peso de carcaça" in n for n in rel.notas)
        corpo = tela[1]
        assert corpo[tela[0].index("Rendimento")] == "—"
        assert "0,00%" not in " ".join(corpo)

    def test_total_so_considera_as_vendas_com_carcaca_no_rendimento(
        self, gestor, criar, confirmar, dados_abate, season, lote_gordo
    ):
        confirmar(criar(**dados_abate))
        confirmar(
            criar(
                **{
                    **dados_abate,
                    "carcass_weight_kg": None,
                    "head_count": 10,
                    "total_weight_kg": D("5000"),
                    "total_value": D("50000"),
                }
            )
        )

        rel = services.vendas_e_abates(gestor, season=season, farm=None)

        assert rel.totais["cabecas"] == 94
        assert round(rel.totais["rendimento"], 2) == D("51.33")  # só a que tem carcaça

    def test_secoes_por_mes_e_por_comprador_substituem_o_dash_vendas(
        self, gestor, criar, confirmar, dados_abate, season
    ):
        confirmar(criar(**dados_abate))
        rel = services.vendas_e_abates(gestor, season=season, farm=None)

        assert [s.titulo for s in rel.secoes] == [
            "Vendas por mês",
            "Vendas por comprador",
        ]
        assert rel.secoes[0].linhas[0]["nome"] == "2025-08"
        assert rel.secoes[1].linhas[0]["nome"] == "COPERFRIGU"

    def test_filtro_de_periodo_entra_nos_filtros_do_relatorio(
        self, gestor, criar, confirmar, dados_abate, season
    ):
        confirmar(criar(**dados_abate))
        rel = services.vendas_e_abates(
            gestor,
            season=season,
            farm=None,
            start=datetime.date(2025, 9, 1),
            end=datetime.date(2025, 9, 30),
        )

        assert rel.linhas == []
        assert "Período: 01/09/2025 a 30/09/2025" in rel.filtros
        assert "Safra 2025/2026" in rel.filtros

    def test_respeita_o_escopo_de_fazenda(
        self, campo_baixao, criar, confirmar, dados_abate, season
    ):
        confirmar(criar(**dados_abate))
        assert (
            services.vendas_e_abates(campo_baixao, season=season, farm=None).linhas
            == []
        )


class TestResultadoDoLote:
    def test_margem_por_arroba_e_resultado(
        self, gestor, escritorio, lote_de_compra, frigorifico, categoria_25_36, season
    ):
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)

        rel = services.resultado_dos_lotes(gestor, season=season, farm=None)
        lin = rel.linhas[0]

        assert lin["situacao"] == "Encerrado"
        assert lin["resultado"] == D("210000")
        assert (lin["valor_arroba"], lin["custo_arroba"], lin["margem_arroba"]) == (
            D("300"),
            D("168.75"),
            D("131.25"),
        )
        assert rel.totais["resultado"] == D("210000")

    def test_e_o_mesmo_numero_da_tela_do_lote(
        self, gestor, escritorio, lote_de_compra, frigorifico, categoria_25_36, season
    ):
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        lote_de_compra.refresh_from_db()

        rel = services.resultado_dos_lotes(gestor, season=season, farm=None)
        do_servico = result.resultado_do_lote(lote_de_compra)

        assert rel.linhas[0]["margem_arroba"] == do_servico.margem_por_arroba
        assert rel.linhas[0]["resultado"] == do_servico.resultado

    def test_chama_o_servico_nao_reimplementa(
        self,
        gestor,
        escritorio,
        lote_de_compra,
        frigorifico,
        categoria_25_36,
        season,
        monkeypatch,
    ):
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        real = result.resultado_do_lote(lote_de_compra)
        falso = result.ResultadoDoLote(
            lote=lote_de_compra,
            receita=D("1"),
            custo_considerado=D("2"),
            resultado=D("-1"),
            margem_por_arroba=D("7.77"),
            cabecas_vendidas=real.cabecas_vendidas,
            arrobas_vendidas=D("1"),
        )
        monkeypatch.setattr(services, "resultado_do_lote", lambda lote: falso)

        lin = services.resultado_dos_lotes(gestor, season=season, farm=None).linhas[0]

        assert (lin["resultado"], lin["margem_arroba"]) == (D("-1"), D("7.77"))

    def test_lote_sem_custo_de_aquisicao_fica_fora_do_total_e_a_nota_diz_qual(
        self,
        gestor,
        escritorio,
        criar,
        confirmar,
        dados_abate,
        lote_de_compra,
        frigorifico,
        categoria_25_36,
        season,
    ):
        confirmar(criar(**dados_abate))  # lote_gordo: sem compra registrada
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)

        rel = services.resultado_dos_lotes(gestor, season=season, farm=None)

        assert len(rel.linhas) == 2
        sem_custo = linha(rel, "lote", "LT-SFR-010")
        assert (
            sem_custo["resultado"] is None
            and "não tem compra" in sem_custo["observacao"]
        )
        # O total soma só o lote que tem custo (o rateio da fazenda agora é
        # dividido entre os dois lotes, por isso não é mais 210.000 redondo).
        com_custo = linha(rel, "lote", lote_de_compra.code)
        assert rel.totais["resultado"] == com_custo["resultado"]
        assert rel.totais["receita"] == com_custo["receita"]
        assert any("Fora do total" in n and "LT-SFR-010" in n for n in rel.notas)

    def test_lote_aberto_aparece_como_parcial(
        self, gestor, escritorio, lote_de_compra, frigorifico, categoria_25_36, season
    ):
        vender(
            escritorio,
            lote_de_compra,
            frigorifico,
            categoria_25_36,
            head_count=40,
            total_weight_kg=D("19200"),
            carcass_weight_kg=D("9600"),
            total_value=D("192000"),
        )
        lin = services.resultado_dos_lotes(gestor, season=season, farm=None).linhas[0]
        assert lin["situacao"] == "Parcial" and lin["resultado"] == D("84000")

    def test_sem_vendas_o_relatorio_e_vazio_nao_quebra(self, gestor, season):
        rel = services.resultado_dos_lotes(gestor, season=season, farm=None)
        assert rel.linhas == [] and rel.totais is None


class TestDesempenho:
    def test_lote_sem_pesagem_mostra_travessao_e_o_motivo(
        self, gestor, lote_gordo, season
    ):
        rel = services.desempenho_dos_lotes(
            gestor, season=season, farm=None, hoje=datetime.date(2025, 9, 1)
        )
        lin = rel.linhas[0]

        assert lin["gmd"] is None and lin["arrobas"] is None
        assert "sem pesagem registrada" in lin["observacao"]
        assert lin["dias"] == 53

    def test_gmd_de_duas_pesagens(
        self, gestor, escritorio, lote_gordo, sao_francisco, season
    ):
        for dia, kg in (
            (datetime.date(2025, 8, 1), "20000"),
            (datetime.date(2025, 8, 21), "21000"),
        ):
            herd.registrar_pesagem(
                date=dia,
                farm=sao_francisco,
                lot=lote_gordo,
                reason=WeighingReason.CONFERENCIA,
                head_count=100,
                total_weight_kg=D(kg),
                usuario=escritorio,
            )
        lin = services.desempenho_dos_lotes(gestor, season=season, farm=None).linhas[0]

        assert lin["gmd"] == D("0.5")  # 10 kg por cabeça em 20 dias
        assert lin["desde_entrada"] == "Não"

    def test_arroba_estimada_vem_marcada_no_filtro(self, gestor, lote_gordo, season):
        rel = services.desempenho_dos_lotes(
            gestor, season=season, farm=None, rendimento_entrada=D("48")
        )
        assert any("ESTIMATIVA" in f and "48,00%" in f for f in rel.filtros)

    def test_sem_rendimento_informado_a_nota_explica(self, gestor, lote_gordo, season):
        rel = services.desempenho_dos_lotes(gestor, season=season, farm=None)
        assert any("sem um rendimento de entrada estimado" in n for n in rel.notas)


class TestPesagens:
    @pytest.fixture
    def pesagens(self, escritorio, lote_gordo, sao_francisco):
        for dia, kg in (
            (datetime.date(2025, 8, 1), "20000"),
            (datetime.date(2025, 8, 21), "21000"),
            (datetime.date(2025, 9, 20), "22500"),
        ):
            herd.registrar_pesagem(
                date=dia,
                farm=sao_francisco,
                lot=lote_gordo,
                reason=WeighingReason.CONFERENCIA,
                head_count=100,
                total_weight_kg=D(kg),
                usuario=escritorio,
            )

    def test_evolucao_do_peso_e_gmd_do_trecho(self, gestor, pesagens, season):
        rel = services.pesagens_do_periodo(gestor, season=season, farm=None)

        primeira, segunda, terceira = rel.linhas
        assert primeira["ganho"] is None and primeira["gmd"] is None  # sem anterior
        assert (segunda["ganho"], segunda["gmd"]) == (D("10"), D("0.5"))
        assert (terceira["ganho"], terceira["gmd"]) == (D("15"), D("0.5"))
        assert segunda["peso_medio"] == D("210")

    def test_filtra_por_periodo_e_por_lote(self, gestor, pesagens, season, lote_gordo):
        rel = services.pesagens_do_periodo(
            gestor,
            season=season,
            farm=None,
            lote=lote_gordo,
            start=datetime.date(2025, 8, 15),
            end=datetime.date(2025, 8, 31),
        )
        assert len(rel.linhas) == 1
        assert f"Lote {lote_gordo.code}" in rel.filtros
        # O trecho continua sendo o do lote inteiro: a 2ª pesagem tem GMD.
        assert rel.linhas[0]["gmd"] == D("0.5")

    def test_respeita_o_escopo(self, campo_baixao, pesagens, season):
        assert (
            services.pesagens_do_periodo(campo_baixao, season=season, farm=None).linhas
            == []
        )


class TestTelas:
    @pytest.mark.parametrize(
        "slug",
        ["vendas-e-abates", "desempenho-do-lote", "resultado-do-lote", "pesagens"],
    )
    def test_cada_relatorio_abre_e_mostra_os_filtros(
        self, client, gestor, season, slug
    ):
        client.force_login(gestor)
        html = client.get(reverse("reports:relatorio", args=[slug])).content.decode()
        assert "Filtros:" in html and "Safra 2025/2026" in html

    def test_indice_lista_os_9_relatorios(self, client, gestor):
        client.force_login(gestor)
        html = client.get(reverse("reports:indice")).content.decode()
        for titulo in (
            "Vendas e abates",
            "Desempenho do lote",
            "Resultado do lote",
            "Pesagens",
        ):
            assert titulo in html

    def test_parametro_de_outro_relatorio_e_ignorado(self, client, gestor, season):
        """`rendimento_entrada` não é parâmetro de Vendas: não passa."""
        client.force_login(gestor)
        resposta = client.get(
            reverse("reports:relatorio", args=["vendas-e-abates"])
            + "?rendimento_entrada=48"
        )
        assert resposta.status_code == 200

    def test_lote_de_outra_fazenda_no_filtro_e_ignorado(
        self, client, campo_baixao, season, lote_gordo
    ):
        client.force_login(campo_baixao)
        html = client.get(
            reverse("reports:relatorio", args=["pesagens"]) + f"?lote={lote_gordo.pk}"
        ).content.decode()
        assert "Lote LT-SFR-010" not in html

    def test_a_tela_no_celular_vira_cartao(
        self, client, gestor, criar, confirmar, dados_abate, season
    ):
        confirmar(criar(**dados_abate))
        client.force_login(gestor)
        html = client.get(
            reverse("reports:relatorio", args=["vendas-e-abates"])
        ).content.decode()
        assert "sm:hidden" in html and "hidden sm:block" in html
