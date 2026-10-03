"""F3-05 — `SaleResultService`: o boi pagou o que custou criar?

Cenário (tudo em números redondos, para a conta ser conferível de cabeça):

    compra de 100 cabeças: animais R$ 250.000 + frete R$ 5.000 = R$ 255.000
    custo direto no lote (vacina)                              = R$   3.000
    custo indireto da fazenda, rateado (só há este lote)       = R$  12.000
                                                       custo   = R$ 270.000
    abate de 100 cabeças, 24.000 kg de carcaça = 1.600 @, R$ 480.000 (R$ 300/@)

    resultado = 480.000 − 270.000 = 210.000
    custo/@   = 270.000 ÷ 1.600   = 168,75
    margem/@  = 300 − 168,75      = 131,25      (e 131,25 × 1.600 = 210.000)
"""

import datetime
from decimal import Decimal

import pytest

from apps.livestock.selectors import detalhe_do_lote
from apps.sales import result, services
from apps.sales.tests.conftest import vender  # noqa: F401

pytestmark = pytest.mark.django_db

D = Decimal


class TestResultadoDoLoteEncerrado:
    def test_receita_menos_aquisicao_diretos_e_rateados(
        self, escritorio, lote_de_compra, frigorifico, categoria_25_36
    ):
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        lote_de_compra.refresh_from_db()

        r = result.resultado_do_lote(lote_de_compra)

        assert r.encerrado and not r.parcial
        assert r.receita == D("480000")
        assert r.custo_aquisicao == D("255000")
        assert r.custos_diretos == D("3000")
        assert r.custos_rateados == D("12000")
        assert r.custo_total == D("270000")
        assert r.custo_considerado == D("270000")
        assert r.resultado == D("210000")
        assert r.resultado_por_cabeca == D("2100")

    def test_margem_por_arroba_e_a_pergunta_central(
        self, escritorio, lote_de_compra, frigorifico, categoria_25_36
    ):
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        lote_de_compra.refresh_from_db()

        r = result.resultado_do_lote(lote_de_compra)

        assert r.arrobas_vendidas == D("1600")
        assert r.valor_por_arroba == D("300")
        assert r.custo_por_arroba == D("168.75")
        assert r.margem_por_arroba == D("131.25")
        # A conta fecha: resultado = margem/@ × @ vendidas.
        assert r.margem_por_arroba * r.arrobas_vendidas == r.resultado

    def test_os_custos_nao_contam_duas_vezes(
        self, escritorio, lote_de_compra, frigorifico, categoria_25_36
    ):
        """Os custos que a compra gera (animais, frete) já estão na aquisição."""
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        lote_de_compra.refresh_from_db()
        r = result.resultado_do_lote(lote_de_compra)
        assert r.custo_total == r.custo_aquisicao + r.custos_diretos + r.custos_rateados

    def test_mortes_ficam_no_custo_de_quem_sobrou(
        self, escritorio, lote_de_compra, frigorifico, categoria_25_36, sao_francisco
    ):
        from apps.herd import services as herd
        from apps.herd.models import MovementType

        herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 7, 25),
            quantity=4,
            usuario=escritorio,
            origin_farm=sao_francisco,
            origin_lot=lote_de_compra,
            origin_category=categoria_25_36,
            reason="Picada de cobra",
        )
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36, head_count=96)
        lote_de_compra.refresh_from_db()

        r = result.resultado_do_lote(lote_de_compra)

        # 96 vendidas, saldo zero: o lote inteiro (os 4 mortos incluídos) é
        # absorvido pelos 96 — fração 1, nada de custo "perdido".
        assert r.saldo_atual == 0 and not r.parcial
        assert r.fracao_vendida == D("1")
        assert r.custo_considerado == r.custo_total

    def test_resultado_e_derivado_excluir_a_venda_o_faz_sumir(
        self, escritorio, gestor, lote_de_compra, frigorifico, categoria_25_36
    ):
        venda = vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        services.excluir_venda(venda, usuario=gestor, motivo="engano")
        lote_de_compra.refresh_from_db()

        r = result.resultado_do_lote(lote_de_compra)

        assert r.vendas == 0 and r.resultado is None
        assert "Nenhuma venda confirmada" in r.motivos[0]

    def test_nenhum_campo_do_resultado_e_gravado(self):
        from django.apps import apps

        gravados = {f.name for m in apps.get_models() for f in m._meta.get_fields()}
        for derivado in ("margin", "margem", "result", "resultado", "profit"):
            assert derivado not in gravados


class TestResultadoParcial:
    def test_lote_ainda_com_animais_e_marcado_como_parcial(
        self, escritorio, lote_de_compra, frigorifico, categoria_25_36
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

        r = result.resultado_do_lote(lote_de_compra)

        assert r.parcial and not r.encerrado
        assert r.saldo_atual == 60
        assert r.fracao_vendida == D("0.4")
        assert r.custo_considerado == D("108000")  # 40% de 270.000
        assert r.resultado == D("84000")  # 192.000 − 108.000
        assert any("Resultado parcial" in m for m in r.motivos)


class TestSemDado:
    def test_lote_sem_compra_nao_tem_resultado_mas_tem_receita(
        self, criar, confirmar, dados_abate
    ):
        """O lote "saldo anterior" da planilha não tem custo de aquisição:
        mostrar lucro seria inventar."""
        confirmar(criar(**dados_abate))
        lote = dados_abate["lot"]

        r = result.resultado_do_lote(lote)

        assert r.receita == D("401502.68")
        assert r.resultado is None
        assert r.margem_por_arroba is None
        assert r.custo_por_arroba is None
        assert any("não tem compra registrada" in m for m in r.motivos)

    def test_venda_sem_carcaca_tem_resultado_em_reais_mas_nao_por_arroba(
        self, escritorio, lote_de_compra, frigorifico, categoria_25_36
    ):
        vender(
            escritorio,
            lote_de_compra,
            frigorifico,
            categoria_25_36,
            carcass_weight_kg=None,
        )
        lote_de_compra.refresh_from_db()

        r = result.resultado_do_lote(lote_de_compra)

        assert r.resultado == D("210000")
        assert r.arrobas_vendidas is None
        assert r.valor_por_arroba is None
        assert r.custo_por_arroba is None
        assert r.margem_por_arroba is None
        assert r.vendas_sem_carcaca == 1
        assert any("sem peso de carcaça" in m for m in r.motivos)

    def test_lote_sem_venda_nao_gera_aviso_de_resultado(self, lote_de_compra):
        detalhe = detalhe_do_lote(lote_de_compra)
        assert detalhe["resultado"].vendas == 0
        assert not any("Nenhuma venda" in a for a in detalhe["avisos"])


class TestTelaDoLote:
    def test_tela_do_lote_mostra_o_resultado(
        self, client, gestor, escritorio, lote_de_compra, frigorifico, categoria_25_36
    ):
        from django.urls import reverse

        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        client.force_login(gestor)

        html = client.get(
            reverse("livestock:lote_detalhe", args=[lote_de_compra.pk])
        ).content.decode()

        assert "Resultado do lote" in html and "Lote encerrado" in html
        assert "R$ 210.000,00" in html  # resultado
        assert "R$ 131,25" in html  # margem por @
        assert "R$ 168,75" in html  # custo por @

    def test_tela_do_lote_sem_compra_diz_porque_nao_ha_resultado(
        self, client, gestor, criar, confirmar, dados_abate
    ):
        from django.urls import reverse

        confirmar(criar(**dados_abate))
        client.force_login(gestor)
        html = client.get(
            reverse("livestock:lote_detalhe", args=[dados_abate["lot"].pk])
        ).content.decode()

        assert "não tem compra registrada" in html
        assert "Sem custo" not in html
