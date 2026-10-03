"""As telas: acesso, escopo, andamento por HTMX e download."""

import re

import pytest
from django.test import Client
from django.urls import reverse

from apps.exports import services
from apps.exports.models import ExportJob, ExportStatus

pytestmark = pytest.mark.django_db


def entrar(client, user):
    client.force_login(user)
    return client


class TestAcesso:
    @pytest.mark.parametrize("nome", ["lista", "nova"])
    def test_anonimo_vai_para_o_login(self, client, nome):
        resposta = client.get(reverse(f"exports:{nome}"))
        assert resposta.status_code == 302 and "/contas/" in resposta.url

    @pytest.mark.parametrize("fixture", ["consulta", "campo_baixao"])
    @pytest.mark.parametrize(
        "metodo,nome", [("get", "lista"), ("get", "nova"), ("post", "nova")]
    )
    def test_consulta_e_campo_nao_exportam(
        self, client, request, fixture, metodo, nome
    ):
        entrar(client, request.getfixturevalue(fixture))
        resposta = getattr(client, metodo)(
            reverse(f"exports:{nome}"), {"conjuntos": ["lotes"], "formatos": ["csv"]}
        )
        assert resposta.status_code == 403

    def test_o_menu_so_mostra_exportacoes_a_quem_pode(self, client, gestor, consulta):
        url = reverse("exports:lista")
        assert (
            f'href="{url}"'
            in entrar(client, gestor).get(reverse("dashboards:inicio")).content.decode()
        )
        assert (
            f'href="{url}"'
            not in entrar(Client(), consulta)
            .get(reverse("dashboards:inicio"))
            .content.decode()
        )


class TestFormulario:
    def test_mostra_so_o_que_o_papel_pode_e_o_tamanho_de_cada_conjunto(
        self, client, escritorio_baixao, admin, operacao
    ):
        pagina = entrar(client, admin).get(reverse("exports:nova")).content.decode()
        assert 'value="auditoria"' in pagina and 'value="usuarios"' in pagina
        assert 'value="lotes"' in pagina and 'name="formatos" value="pdf"' in pagina
        assert 'name="relatorios" value="custos-por-centro"' in pagina

        suas = (
            entrar(Client(), escritorio_baixao)
            .get(reverse("exports:nova"))
            .content.decode()
        )
        assert 'value="lotes"' in suas
        assert 'value="auditoria"' not in suas and 'value="usuarios"' not in suas
        assert 'value="contas-bancarias"' not in suas
        # O total de cada conjunto é o do escopo de quem pede.
        total = re.search(r'value="lotes"[^>]*data-total="(\d+)"', suas).group(1)
        assert (
            total == "2"
        )  # os dois lotes do Baixão; os de São Francisco ficam de fora
        assert (
            f'option value="{operacao["lote_sfr"].farm_id}"' not in suas
        )  # nem a fazenda no filtro

    def test_comeca_sem_filtro_mesmo_com_safra_e_fazenda_no_topo(
        self, client, gestor, season, baixao
    ):
        """Quem exporta tudo para guardar não leva só a safra do topo sem perceber."""
        entrar(client, gestor)
        sessao = client.session
        sessao["ctx_farm_id"] = baixao.pk
        sessao.save()
        pagina = client.get(reverse("exports:nova")).content.decode()
        assert "selected>Baixão" not in pagina and "selected>2025/2026" not in pagina
        assert "Todas as safras" in pagina

    def test_links_de_outras_telas_pre_marcam(self, client, gestor):
        pagina = (
            entrar(client, gestor)
            .get(reverse("exports:nova") + "?conjuntos=lotes&conjuntos=compras")
            .content.decode()
        )
        assert re.search(r'value="lotes"[^>]*checked', pagina)
        assert re.search(r'value="compras"[^>]*checked', pagina)
        assert not re.search(r'value="pesagens"[^>]*checked', pagina)

    def test_pedir_cria_a_exportacao_e_leva_para_o_andamento(self, client, gestor):
        entrar(client, gestor)
        resposta = client.post(
            reverse("exports:nova"),
            {
                "conjuntos": ["lotes", "compras"],
                "formatos": ["csv", "json"],
                "csv": "br",
            },
        )
        job = ExportJob.objects.get()
        assert resposta.status_code == 302
        assert resposta.url == reverse("exports:detalhe", args=[job.job_id])
        assert job.requested_by == gestor and job.status == ExportStatus.PENDENTE
        assert job.params["conjuntos"] == ["lotes", "compras"]

    def test_pedido_vazio_volta_com_o_motivo_e_sem_perder_o_que_foi_marcado(
        self, client, gestor
    ):
        resposta = entrar(client, gestor).post(
            reverse("exports:nova"),
            {"conjuntos": ["lotes"], "formatos": [], "csv": "br"},
        )
        pagina = resposta.content.decode()
        assert resposta.status_code == 200
        assert "Escolha pelo menos um formato" in pagina
        assert re.search(r'value="lotes"[^>]*checked', pagina)
        assert not ExportJob.objects.exists()

    def test_conjunto_forjado_no_post_e_recusado(self, client, escritorio):
        resposta = entrar(client, escritorio).post(
            reverse("exports:nova"),
            {"conjuntos": ["usuarios"], "formatos": ["csv"], "csv": "br"},
        )
        assert resposta.status_code == 200 and not ExportJob.objects.exists()

    def test_sem_csrf_o_post_e_recusado(self, gestor):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(gestor)
        resposta = cliente.post(
            reverse("exports:nova"), {"conjuntos": ["lotes"], "formatos": ["csv"]}
        )
        assert resposta.status_code == 403 and not ExportJob.objects.exists()


@pytest.fixture
def pronta(pedir, gestor, operacao):
    return pedir(gestor, conjuntos=["lotes"], formatos=["csv", "json"])


class TestAndamento:
    def test_enquanto_roda_a_tela_pergunta_de_2_em_2_segundos(
        self, client, gestor, pedir, monkeypatch
    ):
        from apps.exports import tasks

        monkeypatch.setattr(tasks.executar, "delay", lambda pk: None)
        job = services.solicitar_exportacao(
            user=gestor, conjuntos=["lotes"], formatos=["csv"]
        )
        entrar(client, gestor)

        parcial = client.get(
            reverse("exports:detalhe", args=[job.job_id]), HTTP_HX_REQUEST="true"
        ).content.decode()
        assert 'hx-trigger="every 2s"' in parcial
        assert "Na fila" in parcial and "Cancelar exportação" in parcial

        ExportJob.objects.filter(pk=job.pk).update(
            status=ExportStatus.PROCESSANDO,
            stage="Lendo Lotes (1 de 1)",
            work_total=200,
            work_done=50,
        )
        parcial = client.get(
            reverse("exports:detalhe", args=[job.job_id]), HTTP_HX_REQUEST="true"
        ).content.decode()
        assert "Lendo Lotes (1 de 1)" in parcial and 'aria-valuenow="25"' in parcial
        assert "width: 25%" in parcial

    def test_pronta_para_de_perguntar_e_oferece_o_download(
        self, client, gestor, pronta
    ):
        entrar(client, gestor)
        parcial = client.get(
            reverse("exports:detalhe", args=[pronta.job_id]), HTTP_HX_REQUEST="true"
        ).content.decode()
        assert "hx-trigger" not in parcial
        assert "Exportação pronta" in parcial
        assert reverse("exports:baixar", args=[pronta.job_id]) in parcial
        assert "<html" not in parcial  # só o fragmento

    def test_pagina_completa_traz_o_pedido_e_o_hash(self, client, gestor, pronta):
        pagina = (
            entrar(client, gestor)
            .get(reverse("exports:detalhe", args=[pronta.job_id]))
            .content.decode()
        )
        assert (
            pronta.file_hash in pagina and "Todas as fazendas do seu acesso" in pagina
        )

    def test_erro_mostra_o_motivo_sem_traceback(self, client, gestor, pronta):
        ExportJob.objects.filter(pk=pronta.pk).update(
            status=ExportStatus.ERRO, error="Não foi possível exportar Lotes."
        )
        pagina = (
            entrar(client, gestor)
            .get(reverse("exports:detalhe", args=[pronta.job_id]))
            .content.decode()
        )
        assert (
            "Não foi possível exportar Lotes." in pagina and "Traceback" not in pagina
        )

    def test_lista_mostra_as_minhas_e_so_as_minhas(
        self, client, gestor, admin, pronta, pedir
    ):
        pedir(admin, conjuntos=["usuarios"], formatos=["csv"])
        pagina = entrar(client, gestor).get(reverse("exports:lista")).content.decode()
        assert (
            str(pronta.job_id) in pagina
            or reverse("exports:detalhe", args=[pronta.job_id]) in pagina
        )
        assert ExportJob.objects.count() == 2 and pagina.count('class="is-link"') == 1


class TestDownload:
    def test_baixa_o_arquivo_como_anexo_sem_cache(
        self, client, gestor, pronta, conteudo
    ):
        resposta = entrar(client, gestor).get(
            reverse("exports:baixar", args=[pronta.job_id])
        )
        assert resposta.status_code == 200
        assert resposta["Content-Type"] == "application/zip"
        assert resposta["Content-Disposition"].startswith("attachment;")
        assert pronta.file_name in resposta["Content-Disposition"]
        assert "no-store" in resposta["Cache-Control"]
        corpo = b"".join(resposta.streaming_content)
        assert corpo[:2] == b"PK"

    def test_de_outro_usuario_e_404_nao_403_nem_para_o_admin(
        self, client, admin, pronta
    ):
        entrar(client, admin)
        for nome in ("detalhe", "baixar"):
            assert (
                client.get(reverse(f"exports:{nome}", args=[pronta.job_id])).status_code
                == 404
            )
        for nome in ("cancelar", "repetir", "apagar"):
            assert (
                client.post(
                    reverse(f"exports:{nome}", args=[pronta.job_id])
                ).status_code
                == 404
            )

    def test_enquanto_nao_esta_pronta_nao_ha_download(self, client, gestor, pronta):
        ExportJob.objects.filter(pk=pronta.pk).update(status=ExportStatus.PROCESSANDO)
        resposta = entrar(client, gestor).get(
            reverse("exports:baixar", args=[pronta.job_id])
        )
        assert resposta.status_code == 302 and resposta.url == reverse(
            "exports:detalhe", args=[pronta.job_id]
        )

    def test_depois_de_apagado_nao_ha_download(self, client, gestor, pronta):
        entrar(client, gestor)
        client.post(reverse("exports:apagar", args=[pronta.job_id]))
        assert (
            client.get(reverse("exports:baixar", args=[pronta.job_id])).status_code
            == 302
        )
        pronta.refresh_from_db()
        assert pronta.status == ExportStatus.EXPIRADO

    @pytest.mark.parametrize("nome", ["cancelar", "repetir", "apagar"])
    def test_acao_que_escreve_nao_aceita_get(self, client, gestor, pronta, nome):
        resposta = entrar(client, gestor).get(
            reverse(f"exports:{nome}", args=[pronta.job_id])
        )
        assert resposta.status_code == 405

    def test_repetir_cria_outro_pedido(self, client, gestor, pronta, monkeypatch):
        from apps.exports import tasks

        monkeypatch.setattr(tasks.executar, "delay", lambda pk: None)
        resposta = entrar(client, gestor).post(
            reverse("exports:repetir", args=[pronta.job_id])
        )
        novo = ExportJob.objects.exclude(pk=pronta.pk).get()
        assert resposta.url == reverse("exports:detalhe", args=[novo.job_id])
        assert novo.params == pronta.params
