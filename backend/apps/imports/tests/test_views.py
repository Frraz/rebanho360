"""Telas de importação: o fluxo upload → prévia → decisões → confirmação."""

import datetime

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.costs.models import CostCenter, CostClass, CostEntry
from apps.imports.models import BatchStatus, ImportBatch, ImportKind, RowStatus
from apps.imports.tests.conftest import upload_de
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db


def planilha():
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
            datetime.datetime(2025, 9, 2),
            "ONODA",
            "SALÁRIO ALDEMAR",
            2967,
            None,
            "FUNCIONARIO",
            "CUSTEIO",
        ]
    )
    ws.append(
        [
            None,
            datetime.datetime(2025, 9, 3),
            "ONODA",
            "SALÁRIO PRETO",
            2567,
            None,
            None,
            "CUSTEIO",
        ]
    )
    return wb


def enviar(client, nome="custos.xlsx", **extra):
    return client.post(
        reverse("imports:nova"),
        {"kind": ImportKind.CUSTOS, "file": upload_de(planilha(), nome), **extra},
    )


@pytest.fixture
def logado(client, usuario_escritorio):
    client.force_login(usuario_escritorio)
    return client


class TestAcesso:
    def test_campo_nao_abre_a_tela_de_importacao(self, client, usuario_campo):
        client.force_login(usuario_campo)

        assert client.get(reverse("imports:lista")).status_code == 403
        assert client.get(reverse("imports:nova")).status_code == 403

    def test_anonimo_vai_para_o_login(self, client, db):
        resposta = client.get(reverse("imports:lista"))

        assert resposta.status_code == 302
        assert "/contas/entrar/" in resposta.url

    def test_post_sem_csrf_e_recusado(self, usuario_escritorio):
        client = Client(enforce_csrf_checks=True)
        client.force_login(usuario_escritorio)

        resposta = client.post(reverse("imports:nova"), {"kind": "CUSTOS"})

        assert resposta.status_code == 403


class TestFluxo:
    def test_upload_leva_para_a_previa_sem_importar_nada(self, logado):
        resposta = enviar(logado)

        lote = ImportBatch.objects.get()
        assert resposta.status_code == 302
        assert resposta.url == reverse("imports:detalhe", args=[lote.pk])
        assert CostEntry.objects.count() == 0

    def test_previa_mostra_contagens_e_pede_as_opcoes(self, logado):
        enviar(logado)
        lote = ImportBatch.objects.get()

        html = logado.get(reverse("imports:detalhe", args=[lote.pk])).content.decode()

        assert "Prévia" in html
        assert "Escolha a fazenda" in html  # o que falta, dito com todas as letras
        assert "Opções da importação" in html

    def test_fluxo_completo_pela_tela(self, logado):
        enviar(logado)
        lote = ImportBatch.objects.get()
        url = reverse("imports:detalhe", args=[lote.pk])

        # 1) opções
        logado.post(
            url,
            {
                "acao": "opcoes",
                "farm_id": Farm.objects.get(code="SFR").pk,
                "default_cost_class_id": CostClass.objects.get(name="CUSTEIO").pk,
            },
        )
        # 2) decisão para a linha sem centro
        pendente = lote.rows.get(status=RowStatus.PENDENTE)
        logado.post(
            url,
            {
                "acao": "decisoes",
                f"r{pendente.pk}__cost_center": CostCenter.objects.get(
                    name="FUNCIONARIO"
                ).pk,
            },
        )
        # 3) importar exige a confirmação
        sem = logado.post(url, {"acao": "importar"}, follow=True)
        assert "Marque a confirmação" in sem.content.decode()
        assert CostEntry.objects.count() == 0

        com = logado.post(url, {"acao": "importar", "confirmo": "1"}, follow=True)

        assert CostEntry.objects.count() == 2
        lote.refresh_from_db()
        assert lote.status == BatchStatus.IMPORTADO
        mensagens = [str(m) for m in com.context["messages"]]
        assert any("2 lançamentos de custo entraram" in m for m in mensagens)
        assert "Ver os custos importados" in com.content.decode()  # próximo passo

    def test_aceitar_sugestao_so_depois_de_marcar(self, logado):
        enviar(logado)
        lote = ImportBatch.objects.get()
        url = reverse("imports:detalhe", args=[lote.pk])
        logado.post(
            url,
            {
                "acao": "opcoes",
                "farm_id": Farm.objects.get(code="SFR").pk,
                "default_cost_class_id": CostClass.objects.get(name="CUSTEIO").pk,
            },
        )
        html = logado.get(url).content.decode()
        assert "Sugestões do sistema" in html
        assert "texto começa com" in html
        assert lote.rows.get(status=RowStatus.PENDENTE).resolution == {}

    def test_cancelar_pela_tela_nao_importa_nada(self, logado):
        enviar(logado)
        lote = ImportBatch.objects.get()

        logado.post(reverse("imports:detalhe", args=[lote.pk]), {"acao": "cancelar"})

        lote.refresh_from_db()
        assert lote.status == BatchStatus.CANCELADO
        assert CostEntry.objects.count() == 0

    def test_arquivo_invalido_mostra_o_motivo_na_tela(self, logado):
        resposta = logado.post(
            reverse("imports:nova"),
            {"kind": "CUSTOS", "file": SimpleUploadedFile("x.xlsx", b"nao sou zip")},
        )

        assert resposta.status_code == 200
        assert "não é uma planilha" in resposta.content.decode()
        assert ImportBatch.objects.count() == 0

    def test_reenviar_o_mesmo_arquivo_ja_importado_pede_confirmacao(self, logado):
        enviar(logado)
        lote = ImportBatch.objects.get()
        url = reverse("imports:detalhe", args=[lote.pk])
        logado.post(
            url,
            {
                "acao": "opcoes",
                "farm_id": Farm.objects.get(code="SFR").pk,
                "default_cost_class_id": CostClass.objects.get(name="CUSTEIO").pk,
            },
        )
        logado.post(
            url,
            {
                "acao": "decisoes",
                f"r{lote.rows.get(status=RowStatus.PENDENTE).pk}__cost_center": CostCenter.objects.get(
                    name="FUNCIONARIO"
                ).pk,
            },
        )
        logado.post(url, {"acao": "importar", "confirmo": "1"})

        resposta = enviar(logado)

        html = resposta.content.decode()
        assert resposta.status_code == 200
        assert "já foi importado" in html
        assert "importar de novo mesmo assim" in html
        assert ImportBatch.objects.count() == 1
