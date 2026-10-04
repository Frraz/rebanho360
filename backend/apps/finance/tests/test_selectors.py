"""F4-06, F4-07 e F4-08 — contas a pagar, fluxo de caixa e mapa financeiro.
Os números saem dos seletores, uma vez só (regra 6)."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.finance import selectors, services
from apps.finance.models import Direction
from apps.finance.tests.conftest import baixa

pytestmark = pytest.mark.django_db

D = Decimal
HOJE = datetime.date(2025, 10, 10)


def novo_titulo(
    usuario, farm, *, valor, vence, direcao=Direction.PAGAR, payee=None, comp="OUTRO"
):
    return services.criar_titulo(
        usuario=usuario,
        direction=direcao,
        component=comp,
        farm=farm,
        payee=payee,
        issue_date=datetime.date(2025, 9, 1),
        due_date=vence,
        amount=D(valor),
    )


class TestResumoNoBancoIgualAoDaLista:
    """`resumo_de_vencimentos` (agregado no banco) tem de dar o mesmo que
    `resumir_vencimentos` (percorrendo os títulos): é o número da tela."""

    def test_mesmo_resultado_com_baixa_parcial_e_faixas_variadas(
        self, financeiro, gestor, sao_francisco, vendedor
    ):
        dias = (-35, -1, 0, 0, 1, 6, 7, 8, 90)
        for i, d in enumerate(dias):
            titulo = novo_titulo(
                financeiro,
                sao_francisco,
                valor=str(100 * (i + 1)),
                vence=HOJE + datetime.timedelta(days=d),
                payee=vendedor,
            )
            if i == 4:  # uma baixa parcial no meio das faixas
                services.programar_titulo(
                    titulo, usuario=financeiro, data=datetime.date.today()
                )
                services.aprovar_titulo(titulo, usuario=gestor)
                baixa(titulo, financeiro, valor=D("150"))

        titulos = selectors.listar_titulos_para(
            financeiro, direction=Direction.PAGAR, situacao="abertos"
        )
        da_lista = selectors.resumir_vencimentos(list(titulos), hoje=HOJE)
        do_banco = selectors.resumo_de_vencimentos(titulos, hoje=HOJE)

        assert do_banco == da_lista
        assert do_banco.em_aberto.quantidade == len(dias)

    def test_sem_titulo_tudo_zera(self, financeiro):
        titulos = selectors.listar_titulos_para(financeiro, situacao="abertos")
        resumo = selectors.resumo_de_vencimentos(titulos, hoje=HOJE)
        assert (resumo.em_aberto.quantidade, resumo.em_aberto.valor) == (0, D("0"))

    def test_saldo_dos_titulos_desconta_o_baixado(
        self, financeiro, gestor, sao_francisco, vendedor
    ):
        a = novo_titulo(
            financeiro, sao_francisco, valor="1000", vence=HOJE, payee=vendedor
        )
        novo_titulo(financeiro, sao_francisco, valor="500", vence=HOJE, payee=vendedor)
        services.programar_titulo(a, usuario=financeiro, data=datetime.date.today())
        services.aprovar_titulo(a, usuario=gestor)
        baixa(a, financeiro, valor=D("400"))

        titulos = selectors.listar_titulos_para(financeiro, situacao="abertos")

        assert selectors.saldo_dos_titulos(titulos) == D("1100")
        assert selectors.saldo_dos_titulos(titulos) == sum(
            (t.balance for t in titulos), start=D("0")
        )


class TestResumoDeVencimentos:
    def test_o_que_vence_esta_semana_e_quanto(
        self, financeiro, sao_francisco, vendedor
    ):
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="100",
            vence=datetime.date(2025, 10, 1),
            payee=vendedor,
        )
        novo_titulo(financeiro, sao_francisco, valor="200", vence=HOJE, payee=vendedor)
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="300",
            vence=HOJE + datetime.timedelta(days=3),
            payee=vendedor,
        )
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="400",
            vence=HOJE + datetime.timedelta(days=6),
            payee=vendedor,
        )
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="500",
            vence=HOJE + datetime.timedelta(days=7),
            payee=vendedor,
        )

        titulos = selectors.listar_titulos_para(
            financeiro, direction=Direction.PAGAR, situacao="abertos"
        )
        resumo = selectors.resumir_vencimentos(titulos, hoje=HOJE)

        assert (resumo.vencidos.quantidade, resumo.vencidos.valor) == (1, D("100"))
        assert (resumo.hoje.quantidade, resumo.hoje.valor) == (1, D("200"))
        assert (resumo.proximos_7_dias.quantidade, resumo.proximos_7_dias.valor) == (
            2,
            D("700"),
        )
        assert (resumo.depois.quantidade, resumo.depois.valor) == (1, D("500"))
        assert resumo.em_aberto.valor == D("1500")

    def test_conta_so_o_que_falta_depois_de_baixa_parcial(
        self, financeiro, gestor, sao_francisco, vendedor
    ):
        titulo = novo_titulo(
            financeiro, sao_francisco, valor="1000", vence=HOJE, payee=vendedor
        )
        services.programar_titulo(
            titulo, usuario=financeiro, data=datetime.date.today()
        )
        services.aprovar_titulo(titulo, usuario=gestor)
        baixa(titulo, financeiro, valor=D("400"))

        titulos = selectors.listar_titulos_para(financeiro, direction=Direction.PAGAR)
        resumo = selectors.resumir_vencimentos(titulos, hoje=HOJE)

        assert resumo.hoje.valor == D("600")

    def test_quitado_e_cancelado_nao_entram(
        self, financeiro, gestor, sao_francisco, vendedor
    ):
        a = novo_titulo(
            financeiro, sao_francisco, valor="100", vence=HOJE, payee=vendedor
        )
        novo_titulo(financeiro, sao_francisco, valor="200", vence=HOJE, payee=vendedor)
        services.excluir_titulo(a, usuario=gestor, motivo="Pago fora")

        titulos = selectors.listar_titulos_para(financeiro, situacao="abertos")

        assert [t.amount for t in titulos] == [D("200")]

    def test_lista_so_o_escopo_do_usuario(
        self, financeiro, sao_francisco, baixao, vendedor, consulta
    ):
        novo_titulo(financeiro, sao_francisco, valor="100", vence=HOJE, payee=vendedor)
        novo_titulo(financeiro, baixao, valor="999", vence=HOJE, payee=vendedor)

        # `consulta` só enxerga São Francisco.
        assert [t.amount for t in selectors.listar_titulos_para(consulta)] == [D("100")]

    def test_filtros_de_favorecido_situacao_e_periodo(
        self, financeiro, sao_francisco, vendedor, outro_parceiro
    ):
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="100",
            vence=datetime.date(2025, 10, 1),
            payee=vendedor,
        )
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="200",
            vence=datetime.date(2025, 11, 1),
            payee=outro_parceiro,
        )

        por_favorecido = selectors.listar_titulos_para(financeiro, payee=outro_parceiro)
        por_periodo = selectors.listar_titulos_para(
            financeiro, de=datetime.date(2025, 10, 15), ate=datetime.date(2025, 11, 30)
        )

        assert [t.amount for t in por_favorecido] == [D("200")]
        assert [t.amount for t in por_periodo] == [D("200")]


class TestFluxoDeCaixa:
    def test_previsto_e_realizado_separados_por_mes(
        self, financeiro, gestor, sao_francisco, vendedor, frigorifico, season
    ):
        # saída prevista em outubro/2025, entrada prevista em novembro/2025
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="1000",
            vence=datetime.date(2025, 10, 20),
            payee=vendedor,
        )
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="3000",
            vence=datetime.date(2025, 11, 20),
            direcao=Direction.RECEBER,
            payee=frigorifico,
            comp="VENDA",
        )
        # uma saída já realizada (hoje), em outro título
        pago = novo_titulo(
            financeiro,
            sao_francisco,
            valor="500",
            vence=datetime.date(2025, 9, 30),
            payee=vendedor,
        )
        services.programar_titulo(pago, usuario=financeiro, data=datetime.date.today())
        services.aprovar_titulo(pago, usuario=gestor)
        baixa(pago, financeiro, valor=D("500"), data=datetime.date(2025, 10, 5))

        fluxo = selectors.fluxo_de_caixa(
            financeiro, season=season, hoje=datetime.date(2025, 10, 10)
        )

        por_mes = {linha.rotulo: linha for linha in fluxo.linhas}
        outubro, novembro = por_mes["out/2025"], por_mes["nov/2025"]
        assert outubro.saidas_previstas == D("1000")
        assert outubro.saidas_realizadas == D("500")  # baixa de 5/10
        assert outubro.entradas_previstas == D("0")
        assert novembro.entradas_previstas == D("3000")
        assert novembro.saldo_do_mes == D("3000")
        # acumulado: ago..set = 0; out = −1500; nov = +1500
        assert outubro.saldo_acumulado == D("-1500")
        assert novembro.saldo_acumulado == D("1500")
        assert fluxo.total.saldo_acumulado == D("1500")
        # o mês não tem previsto de coisa já paga
        assert fluxo.vencido_nao_pago == D("0")

    def test_doze_meses_da_safra_e_linhas_extras_so_quando_ha_movimento(
        self, financeiro, sao_francisco, vendedor, season
    ):
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="100",
            vence=datetime.date(2026, 8, 1),
            payee=vendedor,
        )

        fluxo = selectors.fluxo_de_caixa(financeiro, season=season)

        rotulos = [linha.rotulo for linha in fluxo.linhas]
        assert rotulos[0] == "jul/2025" and "jun/2026" in rotulos
        assert rotulos[-1] == "Depois da safra"
        assert "Antes da safra" not in rotulos

    def test_vencido_e_nao_pago_e_sinalizado(
        self, financeiro, sao_francisco, vendedor, season
    ):
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="700",
            vence=datetime.date(2025, 9, 1),
            payee=vendedor,
        )

        fluxo = selectors.fluxo_de_caixa(
            financeiro, season=season, hoje=datetime.date(2025, 10, 10)
        )

        assert fluxo.vencido_nao_pago == D("700")


class TestMapaFinanceiro:
    def test_pago_a_pagar_e_vencido_por_favorecido_tipo_e_safra(
        self, financeiro, gestor, sao_francisco, vendedor, outro_parceiro, season
    ):
        a = novo_titulo(
            financeiro,
            sao_francisco,
            valor="1000",
            vence=datetime.date(2025, 9, 1),
            payee=vendedor,
            comp="FRETE",
        )
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="500",
            vence=datetime.date(2099, 1, 1),
            payee=vendedor,
            comp="FRETE",
        )
        novo_titulo(
            financeiro,
            sao_francisco,
            valor="200",
            vence=datetime.date(2099, 1, 1),
            payee=outro_parceiro,
        )
        services.programar_titulo(a, usuario=financeiro, data=datetime.date.today())
        services.aprovar_titulo(a, usuario=gestor)
        baixa(a, financeiro, valor=D("400"))

        mapa = selectors.mapa_financeiro(financeiro, hoje=datetime.date(2025, 10, 10))

        vend = next(x for x in mapa["favorecido"] if x.rotulo == vendedor.name)
        assert (vend.titulos, vend.total, vend.pago) == (2, D("1500"), D("400"))
        assert vend.vencido == D("600")  # 1000 − 400, vencido
        assert vend.a_pagar == D("500")
        frete = next(x for x in mapa["tipo"] if x.rotulo == "Frete")
        assert frete.total == D("1500")
        assert mapa["safra"][0].rotulo == season.name

    def test_sem_favorecido_aparece_com_nome_claro(self, financeiro, sao_francisco):
        novo_titulo(
            financeiro, sao_francisco, valor="10", vence=datetime.date(2099, 1, 1)
        )

        mapa = selectors.mapa_financeiro(financeiro)

        assert mapa["favorecido"][0].rotulo == "Sem favorecido definido"


class TestPainel:
    def test_vencido_vira_pendencia_do_painel_para_quem_ve_o_financeiro(
        self, client, financeiro, escritorio, campo_baixao, titulo
    ):
        # O título da compra vence em 18/10/2025 — já venceu.
        from apps.dashboards import selectors as painel

        for usuario in (financeiro, escritorio):
            chaves = [p.chave for p in painel.pendencias_do_painel(usuario)]
            assert "titulos_vencidos" in chaves
        chaves_campo = [p.chave for p in painel.pendencias_do_painel(campo_baixao)]
        assert "titulos_vencidos" not in chaves_campo

        client.force_login(financeiro)
        html = client.get(reverse("dashboards:inicio")).content.decode()
        assert "título a pagar vencido" in html

    def test_programado_aguarda_aprovacao_aparece_para_quem_aprova(
        self, titulo, escritorio, gestor
    ):
        from apps.dashboards import selectors as painel
        from apps.finance.tests.conftest import programado

        programado(titulo, escritorio)

        assert "a_aprovar" in [p.chave for p in painel.pendencias_do_painel(gestor)]
        assert "a_aprovar" not in [
            p.chave for p in painel.pendencias_do_painel(escritorio)
        ]
