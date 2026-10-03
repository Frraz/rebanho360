"""F5-02, F5-03: cadastros parametrizáveis, permissão e auditoria."""

import datetime
import pathlib
import re

import pytest
from django.urls import reverse

from apps.audit.models import AuditAction, AuditEvent
from apps.commercial.models import CarcassClass, CommissionRule, TaxType
from apps.commercial.seed import CLASSES, TIPOS, garantir_cadastros_comerciais

pytestmark = pytest.mark.django_db


class TestSeed:
    def test_seis_classes_do_legado(self):
        assert set(CarcassClass.objects.values_list("code", flat=True)) >= {
            "MAGRO",
            "AUSENTE",
            "ESCASSA",
            "MEDIANA",
            "UNIFORME",
            "LESAO",
        }
        assert len(CLASSES) == 6

    def test_os_nove_tributos_e_taxas_do_legado(self):
        nomes = set(TaxType.objects.values_list("name", flat=True))
        for nome in (
            "Funrural",
            "Fundepec",
            "GTA",
            "ICMS",
            "Taxa de abate",
            "Indenização",
            "Incentivo Precoce",
            "Idaterra",
            "Crédito GR-3",
        ):
            assert nome in nomes
        assert len(TIPOS) == 11

    def test_semear_de_novo_nao_sobrescreve_o_que_o_usuario_mudou(self):
        classe = CarcassClass.objects.get(code="MAGRO")
        classe.name = "Magro (nome do frigorífico)"
        classe.is_active = False
        classe.save()

        garantir_cadastros_comerciais()

        classe.refresh_from_db()
        assert classe.name == "Magro (nome do frigorífico)" and not classe.is_active
        assert CarcassClass.objects.filter(code="MAGRO").count() == 1


class TestTributoNaoTemFormula:
    """Pendência #21: nada tributário se implementa por dedução."""

    def test_tipo_de_tributo_nao_tem_aliquota_nem_base(self):
        campos = {f.name for f in TaxType._meta.get_fields()}
        assert not campos & {
            "rate",
            "percent",
            "percentage",
            "aliquota",
            "base",
            "value",
        }

    def test_nenhuma_classe_de_carcaca_escrita_no_codigo_fora_do_seed(self):
        """Classificação é cadastro, nunca fixa no código."""
        raiz = pathlib.Path(__file__).resolve().parents[2]
        permitidos = {"seed.py"}
        achados = []
        for arquivo in raiz.glob("**/*.py"):
            partes = arquivo.relative_to(raiz).parts
            if (
                arquivo.name in permitidos
                or "migrations" in partes
                or "tests" in partes
                or "commercial" == partes[0]
                and arquivo.name == "models.py"
            ):
                continue
            texto = arquivo.read_text(encoding="utf-8")
            if re.search(r"Gordura (escassa|mediana|uniforme|ausente)", texto):
                achados.append(str(arquivo.relative_to(raiz)))
        assert achados == []


class TestPermissao:
    def test_gestor_cadastra_classe_e_fica_auditado(self, client, gestor):
        client.force_login(gestor)

        resposta = client.post(
            reverse("commercial:classe_nova"),
            {"code": "g4", "name": "Gordura excessiva", "display_order": 7},
        )

        assert resposta.status_code == 302
        classe = CarcassClass.objects.get(code="G4")
        assert classe.name == "Gordura excessiva"
        evento = AuditEvent.objects.filter(
            entity_type="CarcassClass", entity_id=str(classe.pk)
        ).get()
        assert evento.action == AuditAction.CREATE and evento.actor == gestor

    def test_escritorio_nao_cadastra(self, client, escritorio):
        client.force_login(escritorio)

        assert client.get(reverse("commercial:classe_nova")).status_code == 403
        assert (
            client.post(
                reverse("commercial:tributo_novo"), {"name": "X", "nature": "TAXA"}
            ).status_code
            == 403
        )
        assert not TaxType.objects.filter(name="X").exists()

    def test_escritorio_ve_as_listas(self, client, escritorio):
        client.force_login(escritorio)
        for nome in ("classe_lista", "tributo_lista", "comissao_lista"):
            assert client.get(reverse(f"commercial:{nome}")).status_code == 200

    def test_anonimo_vai_para_o_login(self, client):
        resposta = client.get(reverse("commercial:classe_lista"))
        assert resposta.status_code == 302 and "/entrar/" in resposta["Location"]

    def test_post_sem_csrf_e_recusado(self, gestor):
        from django.test import Client

        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(gestor)
        resposta = cliente.post(
            reverse("commercial:tributo_novo"), {"name": "Y", "nature": "TAXA"}
        )
        assert resposta.status_code == 403
        assert not TaxType.objects.filter(name="Y").exists()

    def test_classe_com_faixa_sugerida_fora_de_1_a_5_e_recusada(self, client, gestor):
        client.force_login(gestor)
        resposta = client.post(
            reverse("commercial:classe_nova"),
            {"code": "X1", "name": "X", "display_order": 1, "default_band": 9},
        )
        assert resposta.status_code == 200
        assert not CarcassClass.objects.filter(code="X1").exists()


class TestRegraDeComissaoNaTela:
    def _dados(self, **extra):
        return {
            "type": "PERCENTUAL",
            "base": "BRUTO",
            "value": "1.5",
            "valid_from": "2025-01-01",
            "is_active": "on",
        } | extra

    def test_cadastra_regra_e_audita_a_edicao(self, client, gestor, comissionado):
        client.force_login(gestor)
        client.post(
            reverse("commercial:comissao_nova"),
            self._dados(commissioned=comissionado.pk),
        )
        regra = CommissionRule.objects.get()
        assert regra.commissioned == comissionado

        client.post(
            reverse("commercial:comissao_editar", args=[regra.pk]),
            self._dados(commissioned=comissionado.pk, value="2"),
        )
        evento = AuditEvent.objects.filter(
            entity_type="CommissionRule", action=AuditAction.UPDATE
        ).get()
        assert "value" in evento.changed_fields

    def test_vigencia_invertida_e_recusada(self, client, gestor):
        client.force_login(gestor)
        resposta = client.post(
            reverse("commercial:comissao_nova"),
            self._dados(valid_from="2025-06-01", valid_to="2025-01-01"),
        )
        assert resposta.status_code == 200
        assert not CommissionRule.objects.exists()

    def test_percentual_acima_de_100_e_recusado(self, client, gestor):
        client.force_login(gestor)
        resposta = client.post(
            reverse("commercial:comissao_nova"), self._dados(value="150")
        )
        assert resposta.status_code == 200
        assert not CommissionRule.objects.exists()

    def test_so_comissionado_aparece_na_escolha(
        self, client, gestor, vendedor, comissionado
    ):
        client.force_login(gestor)
        html = client.get(reverse("commercial:comissao_nova")).content.decode()
        assert comissionado.name in html and vendedor.name not in html

    def test_constraint_de_valor_positivo_existe_no_banco(self, db):
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            CommissionRule.objects.create(
                value=0, valid_from=datetime.date(2025, 1, 1), type="PERCENTUAL"
            )
