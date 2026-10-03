"""F5-06 — contrato em PDF, com versão de template e hash; dado bancário só para
quem já o vê (cliente, 2026-10-03)."""

import hashlib

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User, UserFarmAccess
from apps.audit.models import AuditAction, AuditEvent, OperationEvent
from apps.core.exceptions import BusinessError
from apps.documents.models import DocumentStatus, DocumentType, GeneratedDocument
from apps.partners.models import BankAccount
from apps.procurement import commitments, contract
from apps.procurement.tests.conftest import D

pytestmark = pytest.mark.django_db


class TestGerar:
    def test_gera_pdf_com_hash_e_versao_do_template(self, compromisso, escritorio):
        documento = contract.gerar_contrato(compromisso, usuario=escritorio)

        assert documento.status == DocumentStatus.PRONTO
        assert documento.doc_type == DocumentType.CONTRATO
        assert documento.template_version == contract.TEMPLATE_VERSION == "contrato-v2"
        assert documento.entity_type == "Commitment"
        assert documento.entity_id == str(compromisso.pk)
        conteudo = documento.file.read()
        assert conteudo.startswith(b"%PDF")
        assert documento.file_hash == hashlib.sha256(conteudo).hexdigest()
        assert documento.size_bytes == len(conteudo)

    def test_guarda_a_versao_do_compromisso_que_foi_impressa(
        self, compromisso, escritorio
    ):
        documento = contract.gerar_contrato(compromisso, usuario=escritorio)
        assert documento.params == {
            "commitment_id": compromisso.pk,
            "commitment_version": compromisso.version,
        }

    def test_duas_geracoes_sao_dois_documentos_com_hash(self, compromisso, escritorio):
        a = contract.gerar_contrato(compromisso, usuario=escritorio)
        b = contract.gerar_contrato(compromisso, usuario=escritorio)
        assert a.document_id != b.document_id
        assert contract.contratos_do_compromisso(compromisso).count() == 2
        assert a.file_hash and b.file_hash

    def test_so_depois_de_aprovar(self, rascunho, escritorio):
        with pytest.raises(BusinessError, match="depois da aprovação"):
            contract.gerar_contrato(rascunho, usuario=escritorio)
        assert not GeneratedDocument.objects.exists()

    def test_campo_nao_gera(self, compromisso, campo_baixao):
        with pytest.raises(BusinessError, match="permissão"):
            contract.gerar_contrato(compromisso, usuario=campo_baixao)

    def test_audita_a_geracao_e_marca_a_linha_do_tempo(self, compromisso, escritorio):
        documento = contract.gerar_contrato(compromisso, usuario=escritorio)
        evento = AuditEvent.objects.get(
            entity_type="Documento", entity_id=str(documento.document_id)
        )
        assert evento.action == AuditAction.EXPORT and evento.actor == escritorio
        assert OperationEvent.objects.filter(
            entity_type="Commitment", title="Contrato gerado"
        ).exists()

    def test_falha_vira_documento_com_motivo_nunca_traceback(
        self, compromisso, escritorio, monkeypatch
    ):
        def quebra(*a, **k):
            raise RuntimeError("segredo interno do renderizador")

        monkeypatch.setattr(contract, "renderizar_html", quebra)
        documento = contract.gerar_contrato(compromisso, usuario=escritorio)

        assert documento.status == DocumentStatus.ERRO
        assert "segredo interno" not in documento.error
        assert str(documento.document_id) in documento.error


class TestConteudo:
    def _html(self, compromisso, usuario):
        import django.utils.timezone as tz

        return contract.renderizar_html(
            compromisso, emitido_por=str(usuario), emitido_em=tz.localtime()
        )

    def test_traz_produtor_itens_faixas_e_datas(self, compromisso, escritorio):
        html = self._html(compromisso, escritorio)
        assert compromisso.code in html
        assert "Waldemar Secchi" in html
        assert "216,00" in html and "270,00" in html  # faixas
        assert "01/09/2025" in html and "03/09/2025" in html
        assert "30 dias" in html

    def _conta(self, produtor):
        return BankAccount.objects.create(
            partner=produtor,
            bank_code="001",
            bank_name="Banco do Brasil",
            branch="1303-X",
            account="4249-8",
            pix_key="chave-pix-secreta",
            is_default=True,
        )

    def test_sem_permissao_para_dado_bancario_o_contrato_sai_sem_ele(
        self, compromisso, escritorio, produtor
    ):
        self._conta(produtor)
        html = self._html(compromisso, escritorio)
        for sensivel in ("4249-8", "1303-X", "chave-pix-secreta", "Banco do Brasil"):
            assert sensivel not in html

    def test_com_permissao_leva_banco_agencia_e_conta_mas_nunca_o_pix(
        self, compromisso, gestor, produtor
    ):
        """Cliente, 2026-10-03 (#27): o contrato de compra traz banco, agência e
        conta — só para quem já pode ver dado bancário."""
        self._conta(produtor)
        import django.utils.timezone as tz

        html = contract.renderizar_html(
            compromisso,
            emitido_por=str(gestor),
            emitido_em=tz.localtime(),
            com_dado_bancario=True,
        )
        assert "Banco do Brasil" in html and "1303-X" in html and "4249-8" in html
        assert "chave-pix-secreta" not in html

    def test_gerar_pelo_gestor_registra_o_dado_bancario_na_auditoria(
        self, compromisso, gestor, produtor
    ):
        self._conta(produtor)
        documento = contract.gerar_contrato(compromisso, usuario=gestor)
        evento = AuditEvent.objects.get(
            entity_type="Documento", entity_id=str(documento.document_id)
        )
        assert "com dados bancários" in evento.reason

    def test_varios_compradores_saem_no_contrato(
        self, criar_compromisso, gestor, comissionado, outro_comissionado
    ):
        c = commitments.aprovar_compromisso(
            criar_compromisso(
                compradores=[
                    {"partner": comissionado, "type": "PERCENTUAL", "value": D("1")},
                    {"partner": outro_comissionado, "type": "VALOR", "value": D("9")},
                ]
            ),
            usuario=gestor,
        )
        html = self._html(c, gestor)
        assert comissionado.name in html and outro_comissionado.name in html

    def test_item_por_cabeca_mostra_o_preco_por_cabeca(
        self, escritorio, gestor, criar_compromisso, categoria_desmamados
    ):
        from decimal import Decimal

        from apps.procurement import commitments
        from apps.procurement.tests.conftest import dados_item

        c = commitments.aprovar_compromisso(
            criar_compromisso(
                itens=[
                    dados_item(
                        categoria_desmamados,
                        price_basis="CABECA",
                        unit_price=Decimal("3000"),
                        expected_band=None,
                    )
                ]
            ),
            usuario=gestor,
        )
        assert "por cabeça" in self._html(c, escritorio)


class TestTela:
    def test_gerar_pela_tela_leva_ao_documento(self, client, escritorio, compromisso):
        client.force_login(escritorio)
        resposta = client.post(
            reverse("procurement:contrato_gerar", args=[compromisso.pk])
        )
        documento = GeneratedDocument.objects.get()
        assert resposta.status_code == 302
        assert str(documento.document_id) in resposta["Location"]

    def test_get_nao_gera(self, client, escritorio, compromisso):
        client.force_login(escritorio)
        resposta = client.get(
            reverse("procurement:contrato_gerar", args=[compromisso.pk])
        )
        assert resposta.status_code == 405
        assert not GeneratedDocument.objects.exists()

    def test_fora_do_escopo_devolve_404(self, client, baixao, compromisso):
        outro = User.objects.create_user(
            username="o", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=outro, farm=baixao, can_write=True)
        client.force_login(outro)
        resposta = client.post(
            reverse("procurement:contrato_gerar", args=[compromisso.pk])
        )
        assert resposta.status_code == 404

    def test_pdf_so_por_view_autenticada_e_a_quem_gerou(
        self, client, escritorio, gestor, compromisso, baixao
    ):
        documento = contract.gerar_contrato(compromisso, usuario=escritorio)
        url = reverse("documents:baixar", args=[documento.document_id])

        client.logout()
        assert client.get(url).status_code == 302  # login

        client.force_login(escritorio)
        resposta = client.get(url)
        assert resposta.status_code == 200
        assert resposta["Content-Type"] == "application/pdf"

        client.force_login(gestor)  # enxerga tudo
        assert client.get(url).status_code == 200

        outro = User.objects.create_user(
            username="o", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=outro, farm=baixao, can_write=True)
        client.force_login(outro)
        assert client.get(url).status_code == 404

    def test_detalhe_lista_os_contratos_gerados(self, client, escritorio, compromisso):
        contract.gerar_contrato(compromisso, usuario=escritorio)
        client.force_login(escritorio)
        html = client.get(
            reverse("procurement:compromisso_detalhe", args=[compromisso.pk])
        ).content.decode()
        assert "Contrato gerado em" in html and "contrato-v2" in html
