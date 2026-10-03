"""F5-14 a F5-17 — os relatórios do ciclo: mesmos números da tela, escopo,
papel, snapshot da comissão e "—" com o motivo."""

import dataclasses
import datetime

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.accounts.models import Role, User, UserFarmAccess
from apps.commercial.models import CommissionRule
from apps.documents import services as documentos
from apps.documents.models import DocumentStatus
from apps.procurement import closing, commitments
from apps.procurement.tests.conftest import DATA_ACERTO, D, tipo
from apps.reports import ciclo, services

pytestmark = pytest.mark.django_db

CICLO = [
    "programacao-de-embarque",
    "programacao-de-abate",
    "conferencia-do-acerto",
    "comissao-por-comprador",
    "fretes-e-quebra",
    "historico-por-pecuarista",
    "programado-x-realizado",
]


def montar(user, slug, season, **extras):
    return services.montar_relatorio(
        user, slug, season=season, farm=None, extras=extras
    )


def celulas(relatorio):
    """Cada linha como {chave: valor}, para conferir por nome de coluna."""
    return relatorio.linhas


class TestPapelEEscopo:
    @pytest.mark.parametrize("slug", CICLO)
    def test_campo_nao_abre_relatorio_do_ciclo(self, campo_baixao, season, slug):
        with pytest.raises(PermissionDenied):
            montar(campo_baixao, slug, season)

    @pytest.mark.parametrize("slug", CICLO)
    def test_campo_recebe_403_na_tela(self, client, campo_baixao, slug):
        client.force_login(campo_baixao)
        assert client.get(reverse("reports:relatorio", args=[slug])).status_code == 403

    def test_indice_esconde_do_campo_e_mostra_a_quem_pode(
        self, client, campo_baixao, escritorio
    ):
        client.force_login(campo_baixao)
        html = client.get(reverse("reports:indice")).content.decode()
        assert "Programação de abate" not in html
        client.force_login(escritorio)
        html = client.get(reverse("reports:indice")).content.decode()
        for titulo in (
            "Programação de abate",
            "Comissão por comprador",
            "Programado × realizado",
        ):
            assert titulo in html

    @pytest.mark.parametrize("slug", [s for s in CICLO if s != "conferencia-do-acerto"])
    def test_so_aparece_o_que_a_fazenda_do_usuario_alcanca(
        self,
        baixao,
        season,
        compromisso,
        viagem,
        recebimento,
        romaneio,
        acerto_aprovado,
        slug,
    ):
        de_outra = User.objects.create_user(
            username="o", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=de_outra, farm=baixao, can_write=True)
        assert montar(de_outra, slug, season).linhas == []

    def test_acerto_fora_do_escopo_nao_existe_para_o_relatorio(
        self, client, baixao, acerto
    ):
        de_outra = User.objects.create_user(
            username="o", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=de_outra, farm=baixao, can_write=True)
        client.force_login(de_outra)
        html = client.get(
            reverse("reports:relatorio", args=["conferencia-do-acerto"])
            + f"?acerto={acerto.pk}"
        ).content.decode()
        assert acerto.code not in html and "Nenhum acerto escolhido" in html


class TestProgramacao:
    def test_embarque_traz_a_viagem_com_o_frete_previsto(
        self, escritorio, season, compromisso, viagem
    ):
        r = montar(escritorio, "programacao-de-embarque", season)
        (linha,) = r.linhas
        assert linha["viagem"] == viagem.code
        assert linha["cabecas"] == 10 and linha["frete"] == D("500.00")
        assert linha["situacao"] == "A caminho"
        assert r.totais["cabecas"] == 10

    def test_embarque_marca_recebida(
        self, escritorio, season, compromisso, recebimento
    ):
        r = montar(escritorio, "programacao-de-embarque", season)
        assert r.linhas[0]["situacao"] == "Recebida"

    def test_embarque_filtra_pela_data_da_retirada(
        self, escritorio, season, compromisso, viagem
    ):
        depois = datetime.date(2025, 9, 10)
        assert (
            montar(escritorio, "programacao-de-embarque", season, start=depois).linhas
            == []
        )

    def test_abate_traz_item_a_item_com_as_faixas_e_a_regra_gravada(
        self, escritorio, season, rascunho, regra_de_comissao, gestor
    ):
        commitments.aprovar_compromisso(rascunho, usuario=gestor)
        r = montar(escritorio, "programacao-de-abate", season)
        (linha,) = r.linhas
        assert linha["precos"] == "216,00 / 237,60 / 248,40 / 270,00 / 270,00"
        assert linha["comissao"] == "1,00% sobre o valor bruto dos animais"
        assert linha["pagamento"] == "30 dias" and linha["cabecas"] == 10
        assert linha["media_arrobas"] == D("17.00")

    def test_abate_nao_lista_o_que_nao_foi_aprovado(self, escritorio, season, rascunho):
        assert montar(escritorio, "programacao-de-abate", season).linhas == []

    def test_abate_item_por_cabeca_mostra_o_preco_por_cabeca(
        self, escritorio, gestor, season, criar_compromisso, categoria_desmamados
    ):
        from apps.procurement.tests.conftest import dados_item

        commitments.aprovar_compromisso(
            criar_compromisso(
                itens=[
                    dados_item(
                        categoria_desmamados,
                        price_basis="CABECA",
                        unit_price=D("3000"),
                        expected_band=None,
                    )
                ]
            ),
            usuario=gestor,
        )
        linha = montar(escritorio, "programacao-de-abate", season).linhas[0]
        assert "por cabeça" in linha["precos"]


class TestConferenciaDoAcerto:
    def test_resumo_secoes_e_totais_da_tela(
        self, escritorio, season, acerto, compromisso
    ):
        closing.registrar_linhas(
            acerto,
            [{"tax_type": tipo("Funrural"), "amount": D("300")}],
            usuario=escritorio,
        )
        from apps.procurement.settlement import calcular_acerto

        calculo = calcular_acerto(compromisso)
        r = montar(escritorio, "conferencia-do-acerto", season, acerto=acerto)

        por_item = {lin["item"]: lin["valor"] for lin in r.linhas}
        assert por_item["Valor dos animais"] == calculo.valor_dos_animais
        assert por_item["Custo de aquisição"] == calculo.custo_aquisicao
        assert por_item["Líquido a pagar ao vendedor"] == calculo.liquido_ao_produtor
        assert por_item["Funrural (tributo)"] == D("300")
        assert [s.titulo for s in r.secoes] == [
            "Previsto × realizado",
            "Detalhamento financeiro",
            "Romaneio de abate valorizado",
        ]

    def test_romaneio_com_totais(self, escritorio, season, acerto):
        r = montar(escritorio, "conferencia-do-acerto", season, acerto=acerto)
        romaneio = r.secoes[2]
        assert romaneio.linhas[0]["classificacao"] == "Gordura mediana"
        assert romaneio.linhas[0]["faixa"] == "Faixa 4"
        assert romaneio.totais["cabecas"] == 10 and romaneio.totais["liquido"] == D(
            "43200.00"
        )

    def test_titulos_so_depois_de_aprovar(self, escritorio, season, acerto, aprovar):
        antes = montar(escritorio, "conferencia-do-acerto", season, acerto=acerto)
        assert antes.secoes[1].linhas == []
        aprovar(acerto)
        depois = montar(escritorio, "conferencia-do-acerto", season, acerto=acerto)
        componentes = {t["componente"] for t in depois.secoes[1].linhas}
        assert {"Animais", "Frete"} <= componentes
        assert depois.secoes[1].totais["valor"] > 0

    def test_nao_leva_dado_bancario(
        self, escritorio, season, acerto, aprovar, produtor
    ):
        from apps.partners.models import BankAccount

        BankAccount.objects.create(
            partner=produtor,
            bank_code="001",
            bank_name="Banco do Brasil",
            branch="1303-X",
            account="4249-8",
            pix_key="chave-secreta",
            is_default=True,
        )
        aprovar(acerto)
        r = montar(escritorio, "conferencia-do-acerto", season, acerto=acerto)
        texto = repr([r.linhas, [s.linhas for s in r.secoes]])
        for sensivel in ("4249-8", "1303-X", "chave-secreta", "Banco do Brasil"):
            assert sensivel not in texto

    def test_pendencia_vai_nas_notas(
        self, escritorio, season, compromisso, recebimento
    ):
        acerto = closing.criar_acerto(
            usuario=escritorio, compromisso=compromisso, date=DATA_ACERTO
        )
        r = montar(escritorio, "conferencia-do-acerto", season, acerto=acerto)
        assert any("não tem romaneio" in n for n in r.notas)

    def test_sem_acerto_escolhido(self, escritorio, season):
        r = montar(escritorio, "conferencia-do-acerto", season)
        assert r.linhas == [] and "Nenhum acerto escolhido" in r.filtros

    def test_pdf_da_conferencia_sai_com_o_acerto_gravado_nos_parametros(
        self, escritorio, season, acerto
    ):
        documento = documentos.solicitar_documento(
            slug="conferencia-do-acerto",
            user=escritorio,
            season=season,
            farm=None,
            origem={"acerto": str(acerto.pk)},
        )
        assert documento.status == DocumentStatus.PRONTO
        assert documento.params["acerto_id"] == acerto.pk
        assert documento.file.read().startswith(b"%PDF")

    def test_botao_de_conferencia_na_tela_do_acerto(self, client, escritorio, acerto):
        client.force_login(escritorio)
        html = client.get(
            reverse("procurement:acerto_detalhe", args=[acerto.pk])
        ).content.decode()
        assert f"conferencia-do-acerto/?acerto={acerto.pk}" in html


class TestComissaoPorComprador:
    def test_mostra_a_regra_gravada_nao_a_do_cadastro_de_hoje(
        self, escritorio, season, rascunho, regra_de_comissao, comissionado, gestor
    ):
        compromisso = commitments.aprovar_compromisso(rascunho, usuario=gestor)
        regra_de_comissao.value = D("9")
        regra_de_comissao.base = "LIQUIDO"
        regra_de_comissao.save()
        CommissionRule.objects.create(
            type="POR_CABECA", value=D("500"), valid_from=datetime.date(2025, 9, 1)
        )

        r = montar(escritorio, "comissao-por-comprador", season)
        (linha,) = r.linhas
        assert (
            linha["regra"] == "1,00% sobre o valor bruto dos animais"
        )  # a de janeiro, não a de hoje
        assert linha["comprador"] == comissionado.name
        assert linha["compromisso"] == compromisso.code

    def test_comissao_so_aparece_com_animal_recebido(
        self, escritorio, season, rascunho, regra_de_comissao, gestor
    ):
        commitments.aprovar_compromisso(rascunho, usuario=gestor)
        linha = montar(escritorio, "comissao-por-comprador", season).linhas[0]
        assert linha["comissao"] is None and linha["cabecas"] is None  # "—", não 0
        assert linha["situacao"] == "Sem acerto"

    def test_valor_machos_femeas_e_total(
        self,
        escritorio,
        season,
        rascunho,
        regra_de_comissao,
        viagem,
        recebimento,
        romaneio,
    ):
        # a regra de 1% foi gravada na aprovação; aqui o escritório a corrige
        # neste compromisso, com motivo
        compromisso = rascunho
        commitments.definir_comissao(
            compromisso,
            tipo="PERCENTUAL",
            base="BRUTO",
            valor=D("1.5"),
            favorecido=compromisso.commissioned,
            usuario=escritorio,
            motivo="Negociado em 1,5%",
        )
        r = montar(escritorio, "comissao-por-comprador", season)
        (linha,) = r.linhas
        assert linha["machos"] == 10 and linha["femeas"] == 0 and linha["cabecas"] == 10
        assert linha["comissao"] == D("648.00")  # 1,5% de R$ 43.200
        assert r.totais["comissao"] == D("648.00") and r.totais["machos"] == 10

    def test_compromisso_sem_comissao_nao_entra(self, escritorio, season, compromisso):
        assert montar(escritorio, "comissao-por-comprador", season).linhas == []


class TestFretesEQuebra:
    def test_frete_previsto_realizado_e_quebra(
        self, escritorio, season, viagem, recebimento
    ):
        trips = __import__("apps.procurement.trips", fromlist=["editar_viagem"])
        trips.editar_viagem(
            viagem,
            {"freight_actual": D("620")},
            None,
            usuario=escritorio,
            motivo="Nota do transportador",
        )
        (linha,) = montar(escritorio, "fretes-e-quebra", season).linhas
        assert linha["previsto"] == D("500.00") and linha["realizado"] == D("620")
        assert linha["diferenca"] == D("120.00")
        assert linha["origem"] == D("5000") and linha["recebido"] == D("4900")
        # a quebra não é calculada dos pesos: só vale a digitada (cliente, #23)
        assert linha["quebra"] is None

    def test_sem_recebimento_a_quebra_e_none(self, escritorio, season, viagem):
        (linha,) = montar(escritorio, "fretes-e-quebra", season).linhas
        assert linha["quebra"] is None
        assert linha["realizado"] is None and linha["diferenca"] is None

    def test_quebra_informada_sai_no_relatorio_sem_marca_de_limite(
        self, escritorio, season, compromisso, item, transportador
    ):
        from apps.procurement import receivings, trips

        v = trips.criar_viagem(
            usuario=escritorio,
            compromisso=compromisso,
            pickup_date=datetime.date(2025, 9, 3),
            carrier=transportador,
            cargas=[
                {
                    "item": item,
                    "planned_qty": 10,
                    "shipped_qty": 10,
                    "origin_weight_kg": D("5000"),
                }
            ],
        )
        receivings.criar_recebimento(
            usuario=escritorio,
            viagem=v,
            date=datetime.date(2025, 9, 4),
            trip_loss_percent=D("6"),
            linhas=[
                {
                    "load": v.loads.get(),
                    "received_qty": 10,
                    "received_weight_kg": D("4700"),
                }
            ],
        )
        relatorio = montar(escritorio, "fretes-e-quebra", season)
        (linha,) = relatorio.linhas
        assert linha["quebra"] == D("6")
        assert "alerta" not in linha


class TestHistoricoPorPecuarista:
    def test_so_acerto_aprovado_entra(self, escritorio, season, acerto, compromisso):
        assert montar(escritorio, "historico-por-pecuarista", season).linhas == []

    def test_indicadores_de_arroba(
        self, escritorio, season, acerto_aprovado, compromisso
    ):
        (linha,) = montar(escritorio, "historico-por-pecuarista", season).linhas
        assert linha["pecuarista"] == "Waldemar Secchi"
        assert linha["cabecas"] == 10 and linha["peso"] == D("2400")
        assert linha["media_arrobas"] == D("16")  # 160 @ ÷ 10 cabeças
        assert linha["valor"] == D("43200.00") and linha["frete"] == D("500.00")
        assert linha["preco_arroba"] == D("270")  # R$ 43.200 ÷ 160 @
        # custo/@ = (animais + frete) ÷ @ = 43.700 ÷ 160
        assert linha["custo_arroba"] == D("43700.00") / D("160")
        assert linha["pagamento"] == "30 dias" and linha["distancia"] == 100

    def test_item_por_cabeca_deixa_arroba_em_none(
        self, escritorio, season, compromisso_duplo, acerto_duplo, gestor
    ):
        closing.aprovar_acerto(acerto_duplo, usuario=gestor)
        (linha,) = montar(escritorio, "historico-por-pecuarista", season).linhas
        assert linha["preco_arroba"] is None and linha["custo_arroba"] is None
        assert linha["media_arrobas"] is None

    def test_o_relatorio_usa_o_servico_do_acerto_e_nao_calcula_por_conta(
        self, escritorio, season, acerto_aprovado, monkeypatch
    ):
        real = ciclo.calcular_acerto

        def falso(c):
            return dataclasses.replace(real(c), valor_dos_animais=D("123456.78"))

        monkeypatch.setattr(ciclo, "calcular_acerto", falso)
        (linha,) = montar(escritorio, "historico-por-pecuarista", season).linhas
        assert linha["valor"] == D("123456.78")


class TestProgramadoXRealizado:
    def test_previsto_e_realizado_lado_a_lado(
        self, escritorio, season, compromisso, viagem, recebimento, romaneio
    ):
        (linha,) = montar(escritorio, "programado-x-realizado", season).linhas
        assert (linha["previstas"], linha["recebidas"], linha["diferenca"]) == (
            10,
            10,
            0,
        )
        assert (linha["peso_previsto"], linha["peso_recebido"]) == (
            D("4800"),
            D("4900"),
        )
        assert linha["valor_previsto"] == D("45900.00")
        assert linha["valor_realizado"] == D("43200.00")
        assert linha["retirada_prevista"] == linha["retirada_real"] == "03/09/2025"
        assert linha["porque"] is None

    def test_sem_recebimento_diz_o_porque_do_traco(
        self, escritorio, season, compromisso
    ):
        (linha,) = montar(escritorio, "programado-x-realizado", season).linhas
        assert linha["recebidas"] is None and linha["diferenca"] is None
        assert "sem recebimento" in linha["porque"]
        assert linha["valor_realizado"] is None  # "—", não 0

    def test_recebido_sem_romaneio_avisa(
        self, escritorio, season, compromisso, viagem, recebimento
    ):
        linha = montar(escritorio, "programado-x-realizado", season).linhas[0]
        assert "sem romaneio" in linha["porque"]

    def test_diferenca_negativa_quando_chegou_menos(
        self, escritorio, season, compromisso, viagem, item
    ):
        from apps.procurement import receivings

        receivings.criar_recebimento(
            usuario=escritorio,
            viagem=viagem,
            date=datetime.date(2025, 9, 4),
            linhas=[{"load": viagem.loads.get(), "received_qty": 8}],
        )
        assert (
            montar(escritorio, "programado-x-realizado", season).linhas[0]["diferenca"]
            == -2
        )


class TestExportacoes:
    @pytest.mark.parametrize("slug", [s for s in CICLO if s != "conferencia-do-acerto"])
    def test_tela_csv_e_xlsx_abrem(
        self, client, escritorio, compromisso, viagem, recebimento, romaneio, slug
    ):
        client.force_login(escritorio)
        url = reverse("reports:relatorio", args=[slug])
        assert client.get(url).status_code == 200
        csv = client.get(url + "?formato=csv")
        assert csv.status_code == 200 and csv.content.startswith("﻿".encode())
        assert client.get(url + "?formato=xlsx").status_code == 200

    @pytest.mark.parametrize("slug", [s for s in CICLO if s != "conferencia-do-acerto"])
    def test_pdf_sai_com_o_filtro_impresso(
        self, escritorio, season, compromisso, viagem, recebimento, slug
    ):
        documento = documentos.solicitar_documento(
            slug=slug, user=escritorio, season=season, farm=None, origem={}
        )
        assert documento.status == DocumentStatus.PRONTO
        assert any("Safra" in f for f in documento.filters)

    def test_csv_do_conferencia_traz_as_tres_secoes(self, client, escritorio, acerto):
        client.force_login(escritorio)
        csv = client.get(
            reverse("reports:relatorio", args=["conferencia-do-acerto"])
            + f"?acerto={acerto.pk}&formato=csv"
        ).content.decode("utf-8-sig")
        for secao in (
            "Previsto × realizado",
            "Detalhamento financeiro",
            "Romaneio de abate valorizado",
        ):
            assert secao in csv
