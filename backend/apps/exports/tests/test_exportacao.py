"""A exportação de ponta a ponta: pede, executa, lê o arquivo que saiu."""

import csv
import hashlib
import io
from decimal import Decimal

import openpyxl
import pytest

from apps.audit.models import AuditEvent
from apps.core.exceptions import BusinessError
from apps.exports import catalog, services
from apps.exports.models import ExportStatus
from apps.livestock.models import Lot

pytestmark = pytest.mark.django_db

D = Decimal


def linhas_csv(bruto: bytes, delimitador=";"):
    texto = bruto.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(texto), delimiter=delimitador))


class TestTudoDeUmaVez:
    def test_exporta_todo_conjunto_que_o_gestor_pode_em_todos_os_formatos(
        self, pedir, conteudo, gestor, operacao, lote_de_compra
    ):
        chaves = [c.chave for c in catalog.conjuntos_para(gestor)]
        job = pedir(
            gestor,
            conjuntos=chaves,
            relatorios=[s for s, _, _ in catalog.relatorios_para(gestor)],
            formatos=["csv", "xlsx", "json", "pdf"],
        )

        assert job.status == ExportStatus.PRONTO, job.error
        arquivos = conteudo(job)
        assert "LEIA-ME.txt" in arquivos and "manifesto.json" in arquivos
        for chave in chaves:
            assert f"csv/{chave}.csv" in arquivos, chave
            assert f"json/{chave}.json" in arquivos, chave
        assert "xlsx/dados.xlsx" in arquivos
        assert any(n.startswith("pdf/lotes") for n in arquivos)
        assert any(n.startswith("relatorios/") for n in arquivos)
        assert all(i["estado"] in ("ok", "vazio") for i in job.items), [
            i for i in job.items if i["estado"] not in ("ok", "vazio")
        ]
        assert job.percentual == 100 and job.expires_at and job.finished_at

    def test_o_manifesto_confere_o_sha256_de_cada_arquivo(
        self, pedir, conteudo, ler_json, gestor, operacao
    ):
        job = pedir(gestor, conjuntos=["lotes", "compras"], formatos=["csv", "json"])
        arquivos = conteudo(job)

        manifesto = ler_json(arquivos["manifesto.json"])
        assert manifesto["sistema"] == "Rebanho360"
        listados = {a["caminho"]: a for a in manifesto["arquivos"]}
        assert set(listados) == {
            n
            for n in arquivos
            if n.endswith((".csv", ".json")) and n != "manifesto.json"
        }
        for caminho, entrada in listados.items():
            assert entrada["sha256"] == hashlib.sha256(arquivos[caminho]).hexdigest()
            assert entrada["bytes"] == len(arquivos[caminho])
        dicionario = {c["chave"]: c for c in manifesto["conjuntos"]}
        assert dicionario["lotes"]["registros"] == Lot.objects.count()
        assert any(
            c["aponta_para"] == "fazendas"
            for c in dicionario["lotes"]["colunas"]
            if c["chave"] == "farm"
        )

    def test_um_unico_arquivo_sai_sem_zip(self, pedir, conteudo, gestor, operacao):
        job = pedir(gestor, conjuntos=["lotes", "compras"], formatos=["xlsx"])

        assert job.content_type.endswith("spreadsheetml.sheet")
        assert job.file_name.endswith(".xlsx")
        ((nome, bruto),) = conteudo(job).items()
        planilha = openpyxl.load_workbook(io.BytesIO(bruto))
        assert planilha.sheetnames == ["Resumo", "Lotes", "Compras"]
        assert job.file_hash == hashlib.sha256(bruto).hexdigest()

    def test_dois_formatos_de_um_conjunto_viram_zip(
        self, pedir, conteudo, gestor, operacao
    ):
        job = pedir(gestor, conjuntos=["lotes"], formatos=["csv", "json"])
        assert job.content_type == "application/zip" and job.file_name.endswith(".zip")


class TestConteudo:
    def test_csv_brasileiro(self, pedir, conteudo, gestor, operacao):
        job = pedir(gestor, conjuntos=["compras"], formatos=["csv"])
        # Um CSV, um conjunto, sem anexos: o próprio .csv.
        bruto = next(iter(conteudo(job).values()))
        assert bruto.startswith("﻿".encode())  # BOM: o Excel acerta os acentos
        tabela = linhas_csv(bruto)
        cabecalho = tabela[0]
        assert cabecalho[:2] == ["ID", "Código"]  # o que o produtor procura, à esquerda
        corpo = {linha[cabecalho.index("Código")]: linha for linha in tabela[1:]}
        assert len(corpo) == 2
        valores = {
            linha[cabecalho.index("Valor dos animais (R$)")] for linha in corpo.values()
        }
        assert "90000,50" in valores  # vírgula decimal, sem milhar, sem arredondar
        datas = {linha[cabecalho.index("Data da compra")] for linha in corpo.values()}
        assert datas == {"10/07/2025"}
        situacao = {linha[cabecalho.index("Situação")] for linha in corpo.values()}
        assert situacao == {"Confirmada"}  # rótulo, não código

    def test_csv_internacional_usa_ponto_e_data_iso(
        self, pedir, conteudo, gestor, operacao
    ):
        job = pedir(gestor, conjuntos=["compras"], formatos=["csv"], estilo_csv="intl")
        bruto = next(iter(conteudo(job).values()))
        assert not bruto.startswith("﻿".encode())
        tabela = linhas_csv(bruto, ",")
        cabecalho = tabela[0]
        data = tabela[1][cabecalho.index("Data da compra")]
        assert len(data) == 10 and data[4] == "-"

    def test_json_traz_valor_exato_vinculo_como_id_e_decimal_como_texto(
        self, pedir, conteudo, ler_json, gestor, operacao
    ):
        job = pedir(gestor, conjuntos=["compras"], formatos=["json"])
        doc = ler_json(next(iter(conteudo(job).values())))

        assert doc["conjunto"] == "compras" and doc["formato"].startswith("exportacao-")
        tipos = {c["chave"]: c["tipo"] for c in doc["colunas"]}
        assert (
            tipos["animal_value"] == "decimal"
            and tipos["destination_farm"] == "inteiro"
        )
        valores = {r["animal_value"] for r in doc["registros"]}
        assert "90000.50" in valores or "90000.500" in valores
        assert all(isinstance(r["animal_value"], str) for r in doc["registros"])
        assert all(isinstance(r["destination_farm"], int) for r in doc["registros"])
        assert {r["status"] for r in doc["registros"]} == {
            "CONFIRMADA"
        }  # código, não rótulo

    def test_planilha_tem_numeros_de_verdade_e_datas_de_verdade(
        self, pedir, conteudo, gestor, operacao
    ):
        import datetime

        job = pedir(gestor, conjuntos=["compras"], formatos=["xlsx"])
        planilha = openpyxl.load_workbook(
            io.BytesIO(next(iter(conteudo(job).values())))
        )
        aba = planilha["Compras"]
        cabecalho = [c.value for c in aba[1]]
        linha = [c.value for c in aba[2]]
        valor = linha[cabecalho.index("Valor dos animais (R$)")]
        assert isinstance(valor, int | float) and valor > 0
        assert isinstance(linha[cabecalho.index("Data da compra")], datetime.datetime)
        assert aba.freeze_panes == "A2"

    def test_pdf_abre_e_diz_que_so_traz_as_colunas_principais(
        self, pedir, conteudo, gestor, operacao
    ):
        job = pedir(gestor, conjuntos=["compras"], formatos=["pdf"])
        bruto = next(iter(conteudo(job).values()))
        assert bruto.startswith(b"%PDF")

    def test_relatorio_pronto_usa_o_mesmo_servico_da_tela(
        self, pedir, conteudo, gestor, operacao, season
    ):
        from apps.reports import services as relatorios

        job = pedir(
            gestor, relatorios=["compras-do-periodo"], formatos=["csv"], safra=season
        )
        bruto = next(iter(conteudo(job).values()))
        esperado = relatorios.csv_do_relatorio(
            relatorios.montar_relatorio(
                gestor, "compras-do-periodo", season=season, farm=None
            )
        )
        assert bruto.decode("utf-8") == esperado


class TestEscopo:
    def test_quem_so_enxerga_o_baixao_so_exporta_o_baixao_em_todo_formato(
        self, pedir, conteudo, ler_json, escritorio_baixao, gestor, operacao
    ):
        tudo = pedir(gestor, conjuntos=["compras", "lotes"], formatos=["json"])
        suas = pedir(
            escritorio_baixao, conjuntos=["compras", "lotes"], formatos=["json"]
        )

        do_gestor = ler_json(conteudo(tudo)["json/compras.json"])["registros"]
        do_escritorio = ler_json(conteudo(suas)["json/compras.json"])["registros"]
        assert len(do_gestor) == 2 and len(do_escritorio) == 1
        assert do_escritorio[0]["destination_farm"] == operacao["lote_bxo"].farm_id
        lotes = ler_json(conteudo(suas)["json/lotes.json"])["registros"]
        assert {linha["farm"] for linha in lotes} == {operacao["lote_bxo"].farm_id}

    def test_linhas_de_documento_seguem_a_fazenda_do_pai(
        self, pedir, conteudo, ler_json, escritorio_baixao, gestor, operacao
    ):
        suas = pedir(
            escritorio_baixao,
            conjuntos=["razao-do-rebanho", "movimentacoes", "vendas"],
            formatos=["json"],
        )
        arquivos = conteudo(suas)
        baixao_id = operacao["lote_bxo"].farm_id
        razao = ler_json(arquivos["json/razao-do-rebanho.json"])["registros"]
        assert razao and {r["farm"] for r in razao} == {baixao_id}
        movimentos = ler_json(arquivos["json/movimentacoes.json"])["registros"]
        assert all(
            baixao_id in (m["origin_farm"], m["destination_farm"]) for m in movimentos
        )
        assert (
            ler_json(arquivos["json/vendas.json"])["registros"] == []
        )  # a venda é de São Francisco

    def test_filtro_de_fazenda(
        self, pedir, conteudo, ler_json, gestor, baixao, operacao
    ):
        job = pedir(gestor, conjuntos=["lotes"], formatos=["json"], fazenda=baixao)
        registros = ler_json(next(iter(conteudo(job).values())))["registros"]
        assert {r["farm"] for r in registros} == {baixao.pk}
        assert "Fazenda: Baixão" in job.filters

    def test_fazenda_fora_do_acesso_e_recusada(
        self, pedir, escritorio_baixao, sao_francisco
    ):
        with pytest.raises(BusinessError, match="não está no seu acesso"):
            pedir(
                escritorio_baixao,
                conjuntos=["lotes"],
                formatos=["csv"],
                fazenda=sao_francisco,
            )

    def test_conjunto_sem_permissao_e_recusado_no_pedido(
        self, pedir, escritorio, financeiro
    ):
        with pytest.raises(BusinessError, match="usuarios"):
            pedir(escritorio, conjuntos=["usuarios"], formatos=["csv"])
        with pytest.raises(BusinessError, match="contas-bancarias"):
            pedir(escritorio, conjuntos=["contas-bancarias"], formatos=["csv"])
        assert (
            pedir(financeiro, conjuntos=["contas-bancarias"], formatos=["csv"]).status
            == "PRONTO"
        )

    def test_o_acesso_e_conferido_de_novo_na_hora_de_executar(
        self, pedir, conteudo, monkeypatch, financeiro, operacao
    ):
        """O papel mudou entre o pedido e o processamento: o conjunto sai da
        exportação, com aviso, em vez de vazar."""
        from apps.accounts.models import Role
        from apps.exports import tasks

        monkeypatch.setattr(tasks.executar, "delay", lambda pk: None)
        job = services.solicitar_exportacao(
            user=financeiro, conjuntos=["titulos", "lotes"], formatos=["csv"]
        )
        financeiro.role = Role.CAMPO
        financeiro.save()

        job = services.executar_exportacao(job.pk)

        assert job.status == ExportStatus.ERRO
        assert "acesso" in job.error

    def test_conjunto_que_o_papel_perdeu_sai_do_pacote_com_aviso(
        self, pedir, conteudo, monkeypatch, financeiro, operacao
    ):
        from apps.accounts.models import Role
        from apps.exports import tasks

        monkeypatch.setattr(tasks.executar, "delay", lambda pk: None)
        job = services.solicitar_exportacao(
            user=financeiro,
            conjuntos=["titulos", "contas-bancarias", "lotes"],
            formatos=["csv"],
        )
        financeiro.role = Role.ESCRITORIO  # ainda exporta, mas perdeu o dado bancário
        financeiro.save()

        job = services.executar_exportacao(job.pk)

        assert job.status == ExportStatus.PRONTO
        arquivos = conteudo(job)
        assert (
            "csv/contas-bancarias.csv" not in arquivos and "csv/titulos.csv" in arquivos
        )
        assert any("contas-bancarias" in aviso for aviso in job.warnings)
        estados = {i["id"]: i["estado"] for i in job.items}
        assert (
            estados["dados:contas-bancarias"] == "erro"
            and estados["dados:titulos"] != "erro"
        )

    def test_papel_sem_exportacao_e_barrado(self, pedir, consulta, campo_baixao):
        from django.core.exceptions import PermissionDenied

        with pytest.raises(PermissionDenied):
            pedir(consulta, conjuntos=["lotes"], formatos=["csv"])
        with pytest.raises(PermissionDenied):
            pedir(campo_baixao, conjuntos=["lotes"], formatos=["csv"])


class TestFiltrosEOpcoes:
    def test_periodo_filtra_pela_data_do_proprio_conjunto(
        self, pedir, conteudo, ler_json, gestor, operacao
    ):
        import datetime

        job = pedir(
            gestor,
            conjuntos=["vendas", "compras"],
            formatos=["json"],
            de=datetime.date(2025, 8, 1),
            ate=datetime.date(2025, 8, 31),
        )
        arquivos = conteudo(job)
        assert len(ler_json(arquivos["json/vendas.json"])["registros"]) == 1
        assert (
            ler_json(arquivos["json/compras.json"])["registros"] == []
        )  # compras são de julho
        assert any("Período: 01/08/2025 a 31/08/2025" == f for f in job.filters)

    def test_registro_excluido_so_sai_se_pedido(
        self, pedir, conteudo, ler_json, gestor, escritorio, operacao
    ):
        from apps.purchases import services as compras
        from apps.purchases.models import Purchase

        compra = Purchase.objects.filter(head_count=40).get()
        compras.excluir_compra(compra, usuario=gestor, motivo="lançada por engano")

        sem = pedir(gestor, conjuntos=["compras"], formatos=["json"])
        com = pedir(
            gestor, conjuntos=["compras"], formatos=["json"], incluir_excluidos=True
        )

        registros_sem = ler_json(next(iter(conteudo(sem).values())))["registros"]
        registros_com = ler_json(next(iter(conteudo(com).values())))["registros"]
        assert len(registros_sem) == 1
        assert len(registros_com) == 2
        assert {r["status"] for r in registros_com} == {"CONFIRMADA", "EXCLUIDA"}

    def test_texto_que_parece_formula_e_neutralizado_no_csv_e_na_planilha(
        self, pedir, conteudo, gestor
    ):
        from apps.partners.models import Partner

        Partner.objects.create(name='=HYPERLINK("http://x","clique")')
        job = pedir(gestor, conjuntos=["parceiros"], formatos=["csv", "xlsx"])
        arquivos = conteudo(job)

        tabela = linhas_csv(arquivos["csv/parceiros.csv"])
        nomes = [linha[tabela[0].index("Nome")] for linha in tabela[1:]]
        assert '\'=HYPERLINK("http://x","clique")' in nomes
        aba = openpyxl.load_workbook(io.BytesIO(arquivos["xlsx/dados.xlsx"]))[
            "Parceiros"
        ]
        celulas = [c.value for c in aba["B"]]
        assert not any(isinstance(v, str) and v.startswith("=") for v in celulas)


class TestAuditoria:
    def test_pedido_conclusao_e_download_ficam_na_auditoria_sem_o_conteudo(
        self, pedir, gestor, operacao, client
    ):
        job = pedir(gestor, conjuntos=["lotes"], formatos=["csv"])
        client.force_login(gestor)
        client.get(f"/exportacoes/{job.job_id}/baixar/")

        eventos = AuditEvent.objects.filter(
            entity_type="Exportacao", entity_id=str(job.job_id)
        ).order_by("pk")
        razoes = [e.reason for e in eventos]
        assert len(razoes) == 3
        assert razoes[0].startswith("Pedido:") and razoes[1].startswith(
            "Exportação concluída"
        )
        assert razoes[2].startswith("download de ")
        assert all(e.action == "EXPORT" and e.actor == gestor for e in eventos)
        assert "LT-SFR" not in " ".join(razoes)  # o dado exportado não vai para o log
