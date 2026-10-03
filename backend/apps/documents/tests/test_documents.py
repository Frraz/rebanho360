"""F3-12 — PDF com WeasyPrint: sai com os filtros no cabeçalho e fica
registrado para reprodução futura (`document_id`, `template_version`, quem
gerou, quando e hash)."""

import hashlib
import uuid

import pytest
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.documents import services, tasks
from apps.documents.models import DocumentStatus, GeneratedDocument

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def midia_temporaria(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def pedir(client, slug, **extra):
    return client.post(reverse("documents:gerar", args=[slug]), extra)


class TestGeracao:
    def test_relatorio_leve_gera_na_hora_e_registra_tudo(
        self, client, gestor, criar, confirmar, dados_abate, season
    ):
        confirmar(criar(**dados_abate))
        client.force_login(gestor)

        resposta = pedir(client, "vendas-e-abates", de="2025-08-01", ate="2025-08-31")

        doc = GeneratedDocument.objects.get()
        assert resposta.status_code == 302
        assert resposta.url == reverse("documents:detalhe", args=[doc.document_id])
        assert doc.status == DocumentStatus.PRONTO
        assert isinstance(doc.document_id, uuid.UUID)
        assert doc.template_version == services.TEMPLATE_VERSION
        assert doc.generated_by == gestor and doc.generated_at and doc.finished_at
        assert doc.entity_type == "Relatorio" and doc.entity_id == "vendas-e-abates"
        # Os filtros que o usuário viu na tela ficam gravados.
        assert "Safra 2025/2026" in doc.filters
        assert "Período: 01/08/2025 a 31/08/2025" in doc.filters
        assert (
            doc.params["start"] == "2025-08-01" and doc.params["season_id"] == season.pk
        )

    def test_o_arquivo_e_um_pdf_e_o_hash_confere(
        self, client, gestor, criar, confirmar, dados_abate, season
    ):
        confirmar(criar(**dados_abate))
        client.force_login(gestor)
        pedir(client, "vendas-e-abates")

        doc = GeneratedDocument.objects.get()
        with doc.file.open("rb") as f:
            conteudo = f.read()
        assert conteudo.startswith(b"%PDF")
        assert doc.file_hash == hashlib.sha256(conteudo).hexdigest()
        assert doc.size_bytes == len(conteudo) > 1000

    def test_cabecalho_imprime_sistema_relatorio_emissao_e_filtros(
        self, gestor, criar, confirmar, dados_abate, season
    ):
        import datetime

        from apps.reports import services as rel

        confirmar(criar(**dados_abate))
        relatorio = rel.vendas_e_abates(
            gestor,
            season=season,
            farm=None,
            start=datetime.date(2025, 8, 1),
            end=datetime.date(2025, 8, 31),
        )

        html = services.renderizar_html(
            relatorio,
            emitido_por="Warley",
            emitido_em=datetime.datetime(2026, 10, 1, 9, 30),
            versao="relatorio-v1",
        )

        assert "Rebanho360" in html and "Vendas e abates" in html
        assert "Emitido em 01/10/2026 09:30 por Warley" in html
        assert (
            "Filtros aplicados:</strong> Safra 2025/2026 · Todas as fazendas · "
            "Período: 01/08/2025 a 31/08/2025"
        ) in html
        assert "Emitido por Warley" in html  # rodapé
        # O cabeçalho e o rodapé se repetem em toda página; página x de y.
        assert (
            "running(cabecalho)" in html
            and "counter(page)" in html
            and "counter(pages)" in html
        )

    def test_relatorio_longo_pagina_e_repete_o_cabecalho(
        self, gestor, season, escritorio
    ):
        """O cabeçalho (com os filtros) está em toda página, não só na primeira."""
        import datetime

        import weasyprint

        from apps.reports.services import Coluna, Relatorio

        relatorio = Relatorio(
            titulo="Longo",
            descricao="",
            colunas=[Coluna("a", "A"), Coluna("b", "B")],
            linhas=[{"a": f"linha {i}", "b": i} for i in range(300)],
            filtros=["Safra 2025/2026"],
        )
        html = services.renderizar_html(
            relatorio,
            emitido_por="x",
            emitido_em=datetime.datetime(2026, 10, 1),
            versao="v",
        )
        paginas = weasyprint.HTML(string=html).render().pages
        assert len(paginas) > 3

    def test_pedido_e_auditado(self, client, gestor, season):
        client.force_login(gestor)
        pedir(client, "vendas-e-abates")

        doc = GeneratedDocument.objects.get()
        evento = AuditEvent.objects.get(
            entity_type="Documento", entity_id=str(doc.document_id)
        )
        assert evento.action == "EXPORT" and "pdf" in evento.reason

    def test_relatorio_desconhecido_da_404(self, client, gestor):
        client.force_login(gestor)
        assert pedir(client, "nao-existe").status_code == 404
        assert not GeneratedDocument.objects.exists()

    def test_gerar_exige_post(self, client, gestor):
        client.force_login(gestor)
        assert (
            client.get(reverse("documents:gerar", args=["pesagens"])).status_code == 405
        )

    def test_post_sem_csrf_e_recusado(self, gestor):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(gestor)
        assert (
            cliente.post(reverse("documents:gerar", args=["pesagens"])).status_code
            == 403
        )
        assert not GeneratedDocument.objects.exists()


class TestFila:
    def test_relatorio_pesado_vai_para_a_fila_e_nao_segura_o_navegador(
        self, client, gestor, season, monkeypatch, django_capture_on_commit_callbacks
    ):
        enviados = []
        monkeypatch.setattr(tasks.gerar_pdf, "delay", lambda pk: enviados.append(pk))
        client.force_login(gestor)

        with django_capture_on_commit_callbacks(execute=True):
            pedir(client, "resultado-do-lote")

        doc = GeneratedDocument.objects.get()
        assert doc.status == DocumentStatus.PENDENTE and not doc.file
        assert enviados == [doc.pk]

    def test_a_tarefa_gera_o_documento(self, gestor, season):
        doc = GeneratedDocument.objects.create(
            entity_type="Relatorio",
            entity_id="pesagens",
            title="Pesagens",
            template_version="relatorio-v1",
            generated_by=gestor,
            params={"season_id": season.pk, "farm_id": None},
            filters=["Safra 2025/2026"],
        )

        tasks.gerar_pdf(doc.pk)

        doc.refresh_from_db()
        assert doc.status == DocumentStatus.PRONTO and doc.file_hash

    def test_a_mesma_tarefa_duas_vezes_nao_gera_de_novo(self, gestor, season):
        doc = GeneratedDocument.objects.create(
            entity_type="Relatorio",
            entity_id="pesagens",
            title="Pesagens",
            template_version="relatorio-v1",
            generated_by=gestor,
            params={"season_id": season.pk, "farm_id": None},
        )
        tasks.gerar_pdf(doc.pk)
        doc.refresh_from_db()
        antes = (doc.file_hash, doc.finished_at, doc.file.name)

        tasks.gerar_pdf(doc.pk)  # a fila pode entregar duas vezes

        doc.refresh_from_db()
        assert (doc.file_hash, doc.finished_at, doc.file.name) == antes

    def test_o_documento_e_gerado_com_o_escopo_de_quem_pediu(
        self, campo_baixao, criar, confirmar, dados_abate, season
    ):
        """A venda é de São Francisco; o campo só tem o Baixão: o PDF dele
        não pode conter a venda."""
        confirmar(criar(**dados_abate))
        doc = GeneratedDocument.objects.create(
            entity_type="Relatorio",
            entity_id="vendas-e-abates",
            title="Vendas e abates",
            template_version="relatorio-v1",
            generated_by=campo_baixao,
            params={"season_id": season.pk, "farm_id": None},
        )
        capturado = {}
        original = services.renderizar_pdf

        def espiar(relatorio, **kw):
            capturado["linhas"] = relatorio.linhas
            return original(relatorio, **kw)

        services.renderizar_pdf = espiar
        try:
            services.gerar_documento(doc.pk)
        finally:
            services.renderizar_pdf = original

        assert capturado["linhas"] == []


class TestFalha:
    def test_falha_mostra_motivo_e_codigo_nunca_traceback(
        self, client, gestor, season, monkeypatch
    ):
        def quebrar(*a, **k):
            raise RuntimeError("pango explodiu em /usr/lib/segredo")

        monkeypatch.setattr(services, "renderizar_pdf", quebrar)
        client.force_login(gestor)
        resposta = pedir(
            client,
            "vendas-e-abates",
        )
        doc = GeneratedDocument.objects.get()

        assert doc.status == DocumentStatus.ERRO
        html = client.get(resposta.url).content.decode()
        assert "Não foi possível gerar o PDF" in html and str(doc.document_id) in html
        assert (
            "pango" not in html and "Traceback" not in html and "/usr/lib" not in html
        )


class TestAcesso:
    @pytest.fixture
    def doc_do_gestor(self, client, gestor, season):
        client.force_login(gestor)
        pedir(client, "vendas-e-abates")
        client.logout()
        return GeneratedDocument.objects.get()

    def test_o_dono_baixa_e_o_download_e_auditado(self, client, gestor, doc_do_gestor):
        client.force_login(gestor)
        resposta = client.get(
            reverse("documents:baixar", args=[doc_do_gestor.document_id])
        )

        assert resposta.status_code == 200
        assert resposta["Content-Type"] == "application/pdf"
        assert "attachment" in resposta["Content-Disposition"]
        assert b"".join(resposta.streaming_content).startswith(b"%PDF")
        assert AuditEvent.objects.filter(reason="download do PDF").exists()

    def test_outro_usuario_sem_acesso_amplo_recebe_404_nao_403(
        self, client, campo_baixao, doc_do_gestor
    ):
        client.force_login(campo_baixao)
        for nome in ("detalhe", "baixar"):
            resposta = client.get(
                reverse(f"documents:{nome}", args=[doc_do_gestor.document_id])
            )
            assert resposta.status_code == 404

    def test_admin_enxerga_tudo(self, client, admin, doc_do_gestor):
        client.force_login(admin)
        assert (
            client.get(
                reverse("documents:baixar", args=[doc_do_gestor.document_id])
            ).status_code
            == 200
        )

    def test_anonimo_vai_para_o_login(self, client, doc_do_gestor):
        resposta = client.get(
            reverse("documents:baixar", args=[doc_do_gestor.document_id])
        )
        assert resposta.status_code == 302 and resposta.url.startswith(
            reverse("accounts:login")
        )

    def test_o_arquivo_nao_e_servido_como_estatico(self, doc_do_gestor, settings):
        """Anexo só por view autenticada: a URL de media não está exposta."""
        from config import urls

        assert not any("media" in str(p.pattern) for p in urls.urlpatterns)

    def test_lista_mostra_so_os_meus(self, client, gestor, campo_baixao, doc_do_gestor):
        # O título "Vendas e abates" também está no menu: o que identifica o
        # documento na lista é o link com o código dele.
        codigo = str(doc_do_gestor.document_id)
        client.force_login(campo_baixao)
        assert codigo not in client.get(reverse("documents:lista")).content.decode()
        client.force_login(gestor)
        assert codigo in client.get(reverse("documents:lista")).content.decode()

    def test_o_fragmento_de_status_atualiza_pelo_htmx(
        self, client, gestor, doc_do_gestor
    ):
        client.force_login(gestor)
        html = client.get(
            reverse("documents:detalhe", args=[doc_do_gestor.document_id]),
            HTTP_HX_REQUEST="true",
        ).content.decode()
        assert "PDF pronto" in html and "<html" not in html

    def test_documento_pendente_se_atualiza_sozinho(self, client, gestor):
        doc = GeneratedDocument.objects.create(
            entity_type="Relatorio",
            entity_id="pesagens",
            title="Pesagens",
            template_version="v",
            generated_by=gestor,
        )
        client.force_login(gestor)
        html = client.get(
            reverse("documents:detalhe", args=[doc.document_id])
        ).content.decode()
        assert 'hx-trigger="every 2s"' in html and "Gerando o PDF" in html
