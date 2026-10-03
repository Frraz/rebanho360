"""F2-08 — motor de importação: upload → staging → validação → prévia →
confirmação → importação, tudo ou nada. Ver docs/migracao/01."""

from decimal import Decimal

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.core.exceptions import BusinessError
from apps.costs.models import CostCenter, CostClass, CostEntry
from apps.imports import services
from apps.imports.importers import custos as importador_custos
from apps.imports.importers.base import ImportacaoFalhou
from apps.imports.models import BatchStatus, ImportBatch, ImportKind, RowStatus
from apps.imports.tests.conftest import (
    precisa_da_planilha,
    upload_de,
    upload_real,
)
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db

D = Decimal


def planilha_de_custos(linhas):
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
    import datetime

    for dia, item, valor, centro, classe in linhas:
        ws.append(
            [
                None,
                datetime.datetime(2025, 9, dia),
                "ONODA",
                item,
                valor,
                None,
                centro,
                classe,
            ]
        )
    return wb


def importar_custos(usuario, wb, **opcoes):
    batch = services.criar_importacao(
        kind=ImportKind.CUSTOS, arquivo=upload_de(wb), usuario=usuario
    )
    farm = Farm.objects.get(code="SFR")
    classe = CostClass.objects.get(name="CUSTEIO")
    return services.salvar_opcoes(
        batch,
        {"farm_id": farm.pk, "default_cost_class_id": classe.pk, **opcoes},
        usuario=usuario,
    )


class TestUploadEPrevia:
    def test_upload_so_grava_staging_nunca_tabela_final(self, usuario_escritorio):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])

        batch = services.criar_importacao(
            kind=ImportKind.CUSTOS, arquivo=upload_de(wb), usuario=usuario_escritorio
        )

        assert batch.status == BatchStatus.PREVIA
        assert batch.rows.count() == 1
        assert CostEntry.objects.count() == 0

    def test_cada_linha_guarda_a_linha_crua_e_o_numero_da_linha(
        self, usuario_escritorio
    ):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])

        batch = services.criar_importacao(
            kind=ImportKind.CUSTOS, arquivo=upload_de(wb), usuario=usuario_escritorio
        )

        linha = batch.rows.get()
        assert linha.row_number == 2
        assert linha.raw["item"] == "SALÁRIO"
        assert linha.raw["valor"] == 100

    def test_previa_mostra_prontas_pendentes_e_com_erro(self, usuario_escritorio):
        wb = planilha_de_custos(
            [
                (2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO"),
                (3, "SEM CENTRO", 50, None, "CUSTEIO"),
                (4, "CENTRO DESCONHECIDO", 20, "XYZ", "CUSTEIO"),
            ]
        )
        batch = importar_custos(usuario_escritorio, wb)

        resumo = services.resumo_da_previa(batch)

        assert (resumo["prontas"], resumo["pendentes"], resumo["erros"]) == (1, 2, 0)
        assert resumo["problemas"] == []

    def test_sem_fazenda_escolhida_a_previa_diz_o_que_falta(self, usuario_escritorio):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])
        batch = services.criar_importacao(
            kind=ImportKind.CUSTOS, arquivo=upload_de(wb), usuario=usuario_escritorio
        )

        resumo = services.resumo_da_previa(batch)

        assert "Escolha a fazenda" in resumo["problemas"][0]
        with pytest.raises(BusinessError, match="Escolha a fazenda"):
            services.importar(batch, usuario=usuario_escritorio)

    def test_cancelar_nao_deixa_residuo(self, usuario_escritorio):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])
        batch = importar_custos(usuario_escritorio, wb)

        services.cancelar_importacao(batch, usuario=usuario_escritorio)

        batch.refresh_from_db()
        assert batch.status == BatchStatus.CANCELADO
        assert CostEntry.objects.count() == 0
        assert AuditEvent.objects.filter(
            entity_type="ImportBatch", action="CANCEL"
        ).exists()
        with pytest.raises(BusinessError, match="cancelada"):
            services.importar(batch, usuario=usuario_escritorio)


class TestArquivoInvalido:
    def test_so_aceita_xlsx(self, usuario_escritorio):
        arquivo = SimpleUploadedFile("custos.csv", b"a,b,c")

        with pytest.raises(BusinessError, match=r"\.xlsx"):
            services.criar_importacao(
                kind=ImportKind.CUSTOS, arquivo=arquivo, usuario=usuario_escritorio
            )

    def test_arquivo_renomeado_que_nao_e_zip_e_recusado(self, usuario_escritorio):
        arquivo = SimpleUploadedFile("custos.xlsx", b"nao sou um zip")

        with pytest.raises(BusinessError, match="não é uma planilha"):
            services.criar_importacao(
                kind=ImportKind.CUSTOS, arquivo=arquivo, usuario=usuario_escritorio
            )

    def test_planilha_sem_a_aba_esperada_diz_o_que_faltou(self, usuario_escritorio):
        wb = openpyxl.Workbook()

        with pytest.raises(BusinessError, match="não tem a aba CUSTOS"):
            services.criar_importacao(
                kind=ImportKind.CUSTOS,
                arquivo=upload_de(wb),
                usuario=usuario_escritorio,
            )
        assert ImportBatch.objects.count() == 0

    def test_campo_nao_importa(self, usuario_campo):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])

        with pytest.raises(BusinessError, match="permissão"):
            services.criar_importacao(
                kind=ImportKind.CUSTOS, arquivo=upload_de(wb), usuario=usuario_campo
            )


class TestImportarONoMesmoArquivoDuasVezes:
    def test_mesmo_arquivo_depois_de_importado_e_detectado(self, usuario_escritorio):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])
        arquivo_bytes = upload_de(wb).read()
        primeira = services.criar_importacao(
            kind=ImportKind.CUSTOS,
            arquivo=SimpleUploadedFile("c.xlsx", arquivo_bytes),
            usuario=usuario_escritorio,
        )
        services.salvar_opcoes(
            primeira,
            {
                "farm_id": Farm.objects.get(code="SFR").pk,
                "default_cost_class_id": CostClass.objects.get(name="CUSTEIO").pk,
            },
            usuario=usuario_escritorio,
        )
        services.importar(primeira, usuario=usuario_escritorio)

        with pytest.raises(services.ImportacaoDuplicada, match="já foi importado"):
            services.criar_importacao(
                kind=ImportKind.CUSTOS,
                arquivo=SimpleUploadedFile("c.xlsx", arquivo_bytes),
                usuario=usuario_escritorio,
            )

    def test_com_confirmacao_cria_nova_importacao_marcada_como_reimportacao(
        self, usuario_escritorio
    ):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])
        arquivo_bytes = upload_de(wb).read()
        primeira = services.criar_importacao(
            kind=ImportKind.CUSTOS,
            arquivo=SimpleUploadedFile("c.xlsx", arquivo_bytes),
            usuario=usuario_escritorio,
        )
        services.salvar_opcoes(
            primeira,
            {
                "farm_id": Farm.objects.get(code="SFR").pk,
                "default_cost_class_id": CostClass.objects.get(name="CUSTEIO").pk,
            },
            usuario=usuario_escritorio,
        )
        services.importar(primeira, usuario=usuario_escritorio)

        segunda = services.criar_importacao(
            kind=ImportKind.CUSTOS,
            arquivo=SimpleUploadedFile("c.xlsx", arquivo_bytes),
            usuario=usuario_escritorio,
            confirmar_reimportacao=True,
        )

        assert segunda.duplicate_confirmed is True
        assert segunda.pk != primeira.pk

    def test_arquivo_so_cancelado_ou_em_previa_nao_conta_como_ja_importado(
        self, usuario_escritorio
    ):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])
        arquivo_bytes = upload_de(wb).read()
        primeira = services.criar_importacao(
            kind=ImportKind.CUSTOS,
            arquivo=SimpleUploadedFile("c.xlsx", arquivo_bytes),
            usuario=usuario_escritorio,
        )
        services.cancelar_importacao(primeira, usuario=usuario_escritorio)

        outra = services.criar_importacao(
            kind=ImportKind.CUSTOS,
            arquivo=SimpleUploadedFile("c.xlsx", arquivo_bytes),
            usuario=usuario_escritorio,
        )

        assert outra.pk != primeira.pk


class TestTudoOuNada:
    def test_falha_no_meio_nao_deixa_nenhum_lancamento(
        self, usuario_escritorio, monkeypatch
    ):
        wb = planilha_de_custos(
            [(d, f"ITEM {d}", 100 + d, "FUNCIONARIO", "CUSTEIO") for d in range(2, 7)]
        )
        batch = importar_custos(usuario_escritorio, wb)
        real = importador_custos.registrar_custo
        chamadas = []

        def quebra_na_terceira(**kwargs):
            chamadas.append(1)
            if len(chamadas) == 3:
                raise BusinessError("Falha simulada na terceira linha.")
            return real(**kwargs)

        monkeypatch.setattr(importador_custos, "registrar_custo", quebra_na_terceira)

        with pytest.raises(ImportacaoFalhou, match="Falha simulada"):
            services.importar(batch, usuario=usuario_escritorio)

        assert CostEntry.objects.count() == 0  # as duas primeiras foram desfeitas
        batch.refresh_from_db()
        assert batch.status == BatchStatus.PREVIA  # dá para corrigir e tentar de novo
        assert "Falha simulada" in batch.failure_message
        assert not batch.rows.filter(status=RowStatus.IMPORTADA).exists()

    def test_importacao_concluida_audita_o_que_entrou(self, usuario_escritorio):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])
        batch = importar_custos(usuario_escritorio, wb)

        resultado = services.importar(batch, usuario=usuario_escritorio)

        assert resultado["importadas"] == 1
        evento = AuditEvent.objects.get(entity_type="ImportBatch", action="IMPORT")
        assert "1 linhas importadas" in evento.reason

    def test_nao_importa_duas_vezes_o_mesmo_lote(self, usuario_escritorio):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])
        batch = importar_custos(usuario_escritorio, wb)
        services.importar(batch, usuario=usuario_escritorio)

        with pytest.raises(BusinessError, match="importada"):
            services.importar(batch, usuario=usuario_escritorio)

        assert CostEntry.objects.count() == 1

    def test_rastreabilidade_linha_aponta_para_o_registro_que_criou(
        self, usuario_escritorio
    ):
        wb = planilha_de_custos([(2, "SALÁRIO", 100, "FUNCIONARIO", "CUSTEIO")])
        batch = importar_custos(usuario_escritorio, wb)

        services.importar(batch, usuario=usuario_escritorio)

        linha = batch.rows.get()
        assert linha.status == RowStatus.IMPORTADA
        assert isinstance(linha.target, CostEntry)
        assert linha.target.amount == D("100")


@precisa_da_planilha
class TestPlanilhaRealNoMotor:
    def test_planilha_real_sobe_para_a_previa_sem_gravar_nada_final(
        self, usuario_escritorio
    ):
        batch = services.criar_importacao(
            kind=ImportKind.CUSTOS, arquivo=upload_real(), usuario=usuario_escritorio
        )

        assert batch.rows.count() == 235
        assert batch.read_stats == {"lidas": 417, "em_branco": 182, "lancamentos": 235}
        assert CostEntry.objects.count() == 0
        assert CostCenter.objects.count() == 11
