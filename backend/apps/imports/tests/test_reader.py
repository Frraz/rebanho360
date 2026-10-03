"""F2-09 — leitor de planilha. Verificado contra a planilha real do
produtor: `docs/fontes/planilhas/CONTROLE PASTO*.xlsx`."""

import datetime
from decimal import Decimal

import openpyxl
import pytest

from apps.imports import readers
from apps.imports.tests.conftest import PLANILHA_REAL, precisa_da_planilha

pytestmark = pytest.mark.django_db  # as fixtures automáticas de custos usam o banco

D = Decimal


class TestCelulas:
    def test_serial_de_data_do_excel_usa_origem_1899_12_30(self):
        # A doc dizia 2025-07-01; a conta (e a 1ª linha da aba CUSTOS) dá 02/07.
        assert readers.data_da_celula(45840) == datetime.date(2025, 7, 2)
        assert readers.data_da_celula(45840.0) == datetime.date(2025, 7, 2)

    def test_data_aceita_iso_e_formato_brasileiro(self):
        assert readers.data_da_celula("2025-07-02") == datetime.date(2025, 7, 2)
        assert readers.data_da_celula("02/07/2025") == datetime.date(2025, 7, 2)

    def test_numero_pequeno_nao_vira_data(self):
        """A quantidade 133 não é uma data de 1900."""
        assert readers.data_da_celula(133) is None

    def test_erros_de_celula_viram_pendencia_nunca_excecao(self):
        for erro in ("#DIV/0!", "#N/A", "#VALUE!", "#REF!"):
            valor = readers.valor_da_celula(erro)
            assert readers.eh_erro_de_celula(valor)
            assert readers.data_da_celula(valor) is None
            assert readers.decimal_da_celula(valor) is None
            assert not readers.tem_valor(valor)

    def test_traco_e_vazio_na_planilha(self):
        assert readers.valor_da_celula("-") is None
        assert readers.valor_da_celula("   ") is None

    def test_decimal_passa_por_texto_nao_por_float(self):
        assert readers.decimal_da_celula(869.15) == D("869.15")
        assert readers.decimal_da_celula(0.1 + 0.2) == D(
            "0.30000000000000004"
        )  # fiel ao que veio
        assert readers.decimal_da_celula("1.234,56") == D("1234.56")
        assert readers.decimal_da_celula("1234.56") == D("1234.56")

    def test_normalizar_casa_grafias_diferentes(self):
        assert readers.normalizar("Femeas + 36 meses") == readers.normalizar(
            "Fêmeas + 36 meses"
        )
        assert readers.normalizar("SAO JOSE DO GROTAO") == readers.normalizar(
            "São José do Grotão"
        )


class TestLinhaEmBranco:
    def _planilha_de_custos(self, tmp_path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "CUSTOS"
        ws.append(
            [
                None,
                "DATA",
                "PAGADOR",
                "ITEM",
                "VALOR TOTAL",
                "SUB CENTRO",
                "CENTRO DE CUSTO",
                "CLASSE",
            ]
        )
        ws.append(
            [
                None,
                datetime.datetime(2025, 7, 2),
                "ONODA",
                "SALÁRIO",
                2967,
                None,
                "FUNCIONARIO",
                "CUSTEIO",
            ]
        )
        ws.append(
            [None, None, "ONODA", None, None, None, None, None]
        )  # pagador arrastado
        ws.append(
            [None, None, "ONODA", "item solto", None, None, None, None]
        )  # item, sem data nem valor
        ws.append(
            [
                None,
                datetime.datetime(2025, 7, 3),
                "ONODA",
                "sem valor",
                "#DIV/0!",
                None,
                None,
                None,
            ]
        )
        ws.append([None, None, None, None, None, None, None, None])
        caminho = tmp_path / "custos.xlsx"
        wb.save(caminho)
        return caminho

    def test_linha_sem_data_e_sem_valor_nao_e_lancamento_de_zero_reais(self, tmp_path):
        wb = readers.abrir_planilha(self._planilha_de_custos(tmp_path))

        leitura = readers.ler_custos(wb)

        assert leitura.stats == {"lidas": 5, "em_branco": 3, "lancamentos": 2}
        assert [lin.row_number for lin in leitura.linhas] == [2, 5]

    def test_valor_com_erro_de_celula_e_linha_real_pendente(self, tmp_path):
        wb = readers.abrir_planilha(self._planilha_de_custos(tmp_path))

        leitura = readers.ler_custos(wb)

        assert readers.eh_erro_de_celula(leitura.linhas[1].raw["valor"])

    def test_aba_inexistente_diz_quais_abas_existem(self, tmp_path):
        wb = openpyxl.Workbook()
        caminho = tmp_path / "x.xlsx"
        wb.save(caminho)

        with pytest.raises(readers.PlanilhaInvalida, match="não tem a aba CUSTOS"):
            readers.ler_custos(readers.abrir_planilha(caminho))

    def test_arquivo_que_nao_e_planilha_e_recusado_com_mensagem_clara(self, tmp_path):
        caminho = tmp_path / "lixo.xlsx"
        caminho.write_bytes(b"isto nao e um xlsx")

        with pytest.raises(readers.PlanilhaInvalida, match=r"\.xlsx"):
            readers.abrir_planilha(caminho)


@precisa_da_planilha
class TestPlanilhaReal:
    @pytest.fixture(scope="class")
    def wb(self):
        return readers.abrir_planilha(PLANILHA_REAL)

    def test_custos_devolve_235_lancamentos_nao_417(self, wb):
        leitura = readers.ler_custos(wb)

        assert leitura.stats["lidas"] == 417
        assert leitura.stats["em_branco"] == 182
        assert len(leitura.linhas) == 235

    def test_custos_somam_exatamente_1_046_907_76(self, wb):
        leitura = readers.ler_custos(wb)

        total = sum(
            readers.decimal_da_celula(lin.raw["valor"]) for lin in leitura.linhas
        )

        assert total == D("1046907.76")

    def test_custos_sem_centro_sem_descricao_e_sem_classe(self, wb):
        linhas = readers.ler_custos(wb).linhas

        sem_centro = [lin for lin in linhas if not readers.tem_valor(lin.raw["centro"])]
        assert len(sem_centro) == 106
        assert sum(
            readers.decimal_da_celula(lin.raw["valor"]) for lin in sem_centro
        ) == D("411132.64")
        assert sum(1 for lin in linhas if not readers.tem_valor(lin.raw["item"])) == 96
        assert (
            sum(1 for lin in linhas if not readers.tem_valor(lin.raw["classe"])) == 156
        )

    def test_compras_13_com_954_cabecas_e_2_457_752_15(self, wb):
        leitura = readers.ler_compras(wb)

        assert len(leitura.linhas) == 13
        assert (
            sum(
                readers.inteiro_da_celula(lin.raw["quantidade"])
                for lin in leitura.linhas
            )
            == 954
        )
        assert sum(
            readers.decimal_da_celula(lin.raw["valor"]) for lin in leitura.linhas
        ) == D("2457752.15")

    def test_compras_ignora_a_media_derivada_com_div_zero(self, wb):
        leitura = readers.ler_compras(wb)

        assert all("media" not in lin.raw for lin in leitura.linhas)

    def test_abas_de_fazenda_trazem_o_saldo_anterior_do_quadro_resumo(self, wb):
        leitura = readers.ler_movimentacoes(wb)

        saldos = {
            lin.raw["categoria"]: lin.raw["quantidade"]
            for lin in leitura.linhas
            if lin.raw.get("tipo") == "SALDO ANTERIOR"
        }
        assert saldos == {
            "Machos Desm. até 12m": 552,
            "Machos 13 a 24 meses": 171,
            "Machos 25 a 36 meses": 780,
        }

    def test_abas_de_fazenda_trazem_so_o_lancamento_real(self, wb):
        leitura = readers.ler_movimentacoes(wb)

        movimentos = [
            lin for lin in leitura.linhas if lin.raw.get("tipo") != "SALDO ANTERIOR"
        ]
        assert len(movimentos) == 39  # 37 em São Francisco + 2 em Goiano
        tipos = {lin.raw["tipo"] for lin in movimentos}
        assert tipos == {"MORTE", "COMPRA", "ABATE", "TRANSF. S"}
