"""Programação de pagamentos (documento funcional, seções 4.3 e 10): o que há a
pagar, com favorecido, vencimento, valor e conta — e o dado bancário só para
quem pode vê-lo."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.finance import services as fin
from apps.finance.tests.conftest import (
    AMANHA,
    DATA_COMPRA,
    HOJE,
    aprovado,
    baixa,
    programado,
)
from apps.reports import services

pytestmark = pytest.mark.django_db

D = Decimal
SLUG = "programacao-de-pagamentos"


def _montar(usuario, sao_francisco, **kwargs):
    return services.montar_relatorio(
        usuario, SLUG, season=None, farm=sao_francisco, extras=kwargs
    )


def _linha(relatorio, codigo):
    return next(lin for lin in relatorio.linhas if lin["titulo"] == codigo)


def _titulo_manual(escritorio, sao_francisco, vencimento, valor="1000.00", **extra):
    return fin.criar_titulo(
        usuario=escritorio,
        direction="PAGAR",
        farm=sao_francisco,
        issue_date=DATA_COMPRA,
        due_date=vencimento,
        amount=D(valor),
        **extra,
    )


def test_financeiro_ve_favorecido_conta_e_compra(
    financeiro, sao_francisco, titulo, compra
):
    relatorio = _montar(financeiro, sao_francisco)
    linha = _linha(relatorio, titulo.code)

    assert linha["compra"] == compra.code
    assert linha["favorecido"] == titulo.payee.name
    assert linha["banco"] == "Banco do Brasil"
    assert linha["agencia"] == "1234"
    assert linha["conta"] == "98765-4"
    assert linha["atencao"] == ""
    assert {"banco", "agencia", "conta"} <= {c.chave for c in relatorio.colunas}


def test_quem_nao_ve_dado_bancario_nao_recebe_banco_agencia_nem_conta(
    escritorio, sao_francisco, titulo
):
    relatorio = _montar(escritorio, sao_francisco)

    chaves = {c.chave for c in relatorio.colunas}
    assert chaves.isdisjoint({"banco", "agencia", "conta"})
    # Nem escondido na linha: o CSV e o PDF montam a partir daqui.
    texto = services.csv_do_relatorio(relatorio)
    assert "98765-4" not in texto and "Banco do Brasil" not in texto
    assert any("dado bancário" in n for n in relatorio.notas)


def test_campo_recebe_403(client, campo_baixao, titulo):
    client.force_login(campo_baixao)

    assert client.get(reverse("reports:relatorio", args=[SLUG])).status_code == 403


def test_programados_vem_primeiro_depois_pelo_vencimento(
    escritorio, financeiro, sao_francisco, titulo, vendedor
):
    cedo = _titulo_manual(
        escritorio, sao_francisco, HOJE + datetime.timedelta(days=2), "10.00"
    )
    # Título sem favorecido não se programa (regra do financeiro).
    tarde = _titulo_manual(
        escritorio,
        sao_francisco,
        HOJE + datetime.timedelta(days=90),
        "20.00",
        payee=vendedor,
    )
    programado(tarde, escritorio, AMANHA)

    ordem = [lin["titulo"] for lin in _montar(financeiro, sao_francisco).linhas]

    # `tarde` tem data de pagamento; os outros vão pelo vencimento.
    assert ordem.index(tarde.code) < ordem.index(cedo.code)
    # O da compra venceu em 2025: pelo vencimento, vem antes do que vence em 2 dias.
    assert ordem.index(titulo.code) < ordem.index(cedo.code)
    assert _linha(_montar(financeiro, sao_francisco), tarde.code)["programado"] == (
        f"{AMANHA:%d/%m/%Y}"
    )


def test_titulo_sem_favorecido_e_sem_conta_aparecem_como_atencao(
    escritorio, financeiro, sao_francisco, titulo, outro_parceiro
):
    sem_favorecido = _titulo_manual(escritorio, sao_francisco, AMANHA)
    sem_conta = _titulo_manual(
        escritorio, sao_francisco, AMANHA, payee=outro_parceiro, valor="5.00"
    )

    relatorio = _montar(financeiro, sao_francisco)

    assert _linha(relatorio, sem_favorecido.code)["atencao"] == "Sem favorecido"
    assert _linha(relatorio, sem_favorecido.code)["favorecido"] == "A definir"
    assert _linha(relatorio, sem_conta.code)["atencao"] == "Sem conta bancária"
    assert _linha(relatorio, titulo.code)["atencao"] == ""
    assert any("2 título(s)" in n for n in relatorio.notas)


def test_titulo_quitado_cancelado_e_a_receber_nao_entram(
    escritorio, gestor, financeiro, sao_francisco, titulo, titulo_a_receber, vendedor
):
    quitado = _titulo_manual(escritorio, sao_francisco, AMANHA, "7.00", payee=vendedor)
    aprovado(quitado, escritorio, gestor)
    baixa(quitado, financeiro, valor=quitado.amount)
    cancelado = _titulo_manual(escritorio, sao_francisco, AMANHA, "9.00")
    fin.excluir_titulo(cancelado, usuario=gestor, motivo="Lançado em duplicidade")

    codigos = {lin["titulo"] for lin in _montar(financeiro, sao_francisco).linhas}

    assert titulo.code in codigos
    assert quitado.code not in codigos
    assert cancelado.code not in codigos
    assert titulo_a_receber.code not in codigos


def test_total_soma_valor_e_saldo_do_que_esta_em_aberto(
    escritorio, gestor, financeiro, sao_francisco, titulo, vendedor
):
    parcial = _titulo_manual(
        escritorio, sao_francisco, AMANHA, "100.00", payee=vendedor
    )
    aprovado(parcial, escritorio, gestor)
    baixa(parcial, financeiro, valor=D("40.00"))

    relatorio = _montar(financeiro, sao_francisco)

    assert relatorio.totais["valor"] == titulo.amount + D("100.00")
    assert relatorio.totais["saldo"] == titulo.amount + D("60.00")


def test_filtro_de_periodo_usa_o_vencimento(
    escritorio, financeiro, sao_francisco, titulo
):
    longe = _titulo_manual(
        escritorio, sao_francisco, HOJE + datetime.timedelta(days=200), "3.00"
    )

    relatorio = _montar(
        financeiro, sao_francisco, start=HOJE, end=HOJE + datetime.timedelta(days=5)
    )

    codigos = {lin["titulo"] for lin in relatorio.linhas}
    assert longe.code not in codigos


def test_escopo_de_fazenda_outra_fazenda_nao_aparece(
    escritorio, sao_francisco, baixao, titulo, django_user_model
):
    from apps.accounts.models import Role, UserFarmAccess

    so_baixao = django_user_model.objects.create_user(
        username="fin.baixao", password="x", role=Role.FINANCEIRO
    )
    UserFarmAccess.objects.create(user=so_baixao, farm=baixao, can_write=True)

    relatorio = services.montar_relatorio(
        so_baixao, SLUG, season=None, farm=None, extras={}
    )

    assert titulo.code not in {lin["titulo"] for lin in relatorio.linhas}


def test_tela_csv_e_xlsx_abrem_para_o_financeiro(client, financeiro, titulo):
    client.force_login(financeiro)
    url = reverse("reports:relatorio", args=[SLUG])

    assert client.get(url).status_code == 200
    csv = client.get(url, {"formato": "csv"})
    assert csv.status_code == 200
    assert "98765-4" in csv.content.decode("utf-8-sig")
    assert client.get(url, {"formato": "xlsx"}).status_code == 200


def test_menu_do_financeiro_aponta_para_a_programacao(client, financeiro, titulo):
    client.force_login(financeiro)

    html = client.get(reverse("dashboards:inicio")).content.decode()

    assert reverse("reports:relatorio", args=[SLUG]) in html
