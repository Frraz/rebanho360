"""F2-01 e F2-02 — classe, centro de custo e lançamento. Ver
docs/regras-negocio/02-custos-centro-de-custo.md."""

import datetime
import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.reversible import Status
from apps.costs import selectors, services
from apps.costs.models import CostCenter, CostClass, CostEntry
from apps.organizations.models import SeasonStatus

pytestmark = pytest.mark.django_db

DATA = datetime.date(2025, 9, 18)


def lancar(usuario, farm, centro, classe, **kwargs):
    dados = {
        "date": DATA,
        "farm": farm,
        "cost_center": centro,
        "cost_class": classe,
        "amount": Decimal("2967.00"),
        "description": "SALÁRIO ALDEMAR",
        "usuario": usuario,
    }
    dados.update(kwargs)
    return services.registrar_custo(**dados)


class TestSemente:
    def test_a_migracao_semeia_as_2_classes_e_os_11_centros_reais(self):
        migracao = importlib.import_module(
            "apps.costs.migrations.0004_seed_classes_e_centros"
        )
        CostCenter.objects.all().delete()
        CostClass.objects.all().delete()

        migracao.semear(django_apps, None)
        migracao.semear(django_apps, None)  # idempotente

        assert set(CostClass.objects.values_list("name", flat=True)) == {
            "CUSTEIO",
            "INVESTIMENTO",
        }
        assert CostCenter.objects.count() == 11
        assert CostCenter.objects.filter(name="FUNCIONARIO").exists()

    def test_da_para_criar_subcentro_sob_parque_de_maquinas(self, centro_maquinas):
        sub = CostCenter.objects.create(name="Combustível", parent=centro_maquinas)

        assert list(centro_maquinas.children.all()) == [sub]


class TestLancamento:
    def test_lancamento_valido_fica_confirmado_e_auditado(
        self, escritorio, baixao, centro_funcionario, custeio
    ):
        custo = lancar(escritorio, baixao, centro_funcionario, custeio)

        assert custo.status == Status.CONFIRMADA
        assert custo.season.name == "2025/2026"  # derivada da data
        assert custo.is_direct is False

    def test_nao_da_para_salvar_sem_centro_de_custo_nem_no_banco(
        self, baixao, season, custeio, gestor
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            CostEntry.objects.create(
                date=DATA,
                season=season,
                farm=baixao,
                cost_class=custeio,
                amount=Decimal("10"),
                description="sem centro",
                created_by=gestor,
            )

    def test_valor_zero_ou_negativo_e_recusado(
        self, escritorio, baixao, centro_funcionario, custeio
    ):
        for valor in (Decimal("0"), Decimal("-5")):
            with pytest.raises(BusinessError, match="maior que zero"):
                lancar(escritorio, baixao, centro_funcionario, custeio, amount=valor)

    def test_descricao_e_obrigatoria(
        self, escritorio, baixao, centro_funcionario, custeio
    ):
        with pytest.raises(BusinessError, match="descrição"):
            lancar(escritorio, baixao, centro_funcionario, custeio, description="  ")

    def test_data_futura_e_recusada(
        self, escritorio, baixao, centro_funcionario, custeio
    ):
        amanha = datetime.date.today() + datetime.timedelta(days=1)
        with pytest.raises(BusinessError, match="futura"):
            lancar(escritorio, baixao, centro_funcionario, custeio, date=amanha)

    def test_custo_direto_so_aponta_para_lote_da_propria_fazenda(
        self, escritorio, baixao, lote_sao_francisco, centro_funcionario, custeio
    ):
        with pytest.raises(BusinessError, match="própria fazenda"):
            lancar(
                escritorio, baixao, centro_funcionario, custeio, lot=lote_sao_francisco
            )

    def test_usuario_sem_acesso_de_escrita_a_fazenda_e_recusado(
        self, campo_baixao, sao_francisco, centro_funcionario, custeio
    ):
        with pytest.raises(BusinessError, match="permissão de lançamento"):
            lancar(campo_baixao, sao_francisco, centro_funcionario, custeio)

    def test_safra_encerrada_so_aceita_lancamento_do_admin(
        self, escritorio, admin, baixao, season, centro_funcionario, custeio
    ):
        season.status = SeasonStatus.ENCERRADA
        season.save()

        with pytest.raises(BusinessError, match="encerrada"):
            lancar(escritorio, baixao, centro_funcionario, custeio)
        assert lancar(admin, baixao, centro_funcionario, custeio).pk

    def test_filtro_por_safra_e_centro(
        self,
        gestor,
        escritorio,
        baixao,
        season,
        centro_funcionario,
        centro_maquinas,
        custeio,
    ):
        lancar(escritorio, baixao, centro_funcionario, custeio)
        lancar(escritorio, baixao, centro_maquinas, custeio, description="POSTO")

        so_maquinas = selectors.listar_custos_para(
            gestor, season=season, cost_center=centro_maquinas
        )

        assert [c.description for c in so_maquinas] == ["POSTO"]


class TestEdicaoExclusao:
    def test_editar_exige_motivo_e_audita(
        self, escritorio, baixao, centro_funcionario, centro_maquinas, custeio
    ):
        custo = lancar(escritorio, baixao, centro_funcionario, custeio)

        with pytest.raises(BusinessError, match="Motivo"):
            services.editar_custo(
                custo, {"amount": Decimal("3000")}, usuario=escritorio, motivo=" "
            )

        editado = services.editar_custo(
            custo,
            {"amount": Decimal("3000"), "cost_center": centro_maquinas},
            usuario=escritorio,
            motivo="Digitei o valor errado",
        )
        assert editado.amount == Decimal("3000")
        assert editado.cost_center == centro_maquinas
        assert editado.version == 2

    def test_escritorio_edita_mas_nao_exclui(
        self, escritorio, baixao, centro_funcionario, custeio
    ):
        custo = lancar(escritorio, baixao, centro_funcionario, custeio)

        with pytest.raises(BusinessError, match="permissão"):
            services.excluir_custo(custo, usuario=escritorio, motivo="duplicado")

    def test_excluir_e_restaurar(self, gestor, baixao, centro_funcionario, custeio):
        custo = lancar(gestor, baixao, centro_funcionario, custeio)

        services.excluir_custo(custo, usuario=gestor, motivo="Duplicado")
        custo.refresh_from_db()
        assert custo.status == Status.EXCLUIDA
        assert CostEntry.objects.filter(pk=custo.pk).exists()  # lógica, nunca do banco
        assert selectors.listar_custos_para(gestor).count() == 0

        services.restaurar_custo(custo, usuario=gestor)
        custo.refresh_from_db()
        assert custo.status == Status.CONFIRMADA

    def test_safra_encerrada_bloqueia_edicao_e_diz_o_caminho(
        self, gestor, baixao, season, centro_funcionario, custeio
    ):
        custo = lancar(gestor, baixao, centro_funcionario, custeio)
        season.status = SeasonStatus.ENCERRADA
        season.save()

        with pytest.raises(BlockingDependencyError, match="reabrir a safra"):
            services.excluir_custo(custo, usuario=gestor, motivo="erro")

    def test_custo_gerado_por_compra_nao_se_edita_direto(
        self, gestor, baixao, season, centro_funcionario, custeio
    ):
        from apps.purchases.models import Purchase

        compra = Purchase.objects.create(
            code="CP-2025/26-0001",
            date=DATA,
            season=season,
            destination_farm=baixao,
            category=__import__(
                "apps.livestock.models", fromlist=["x"]
            ).AnimalCategory.objects.create(name="Cat teste"),
            head_count=1,
            animal_value=Decimal("1"),
            created_by=gestor,
        )
        custo = lancar(
            gestor, baixao, centro_funcionario, custeio, source_purchase=compra
        )

        with pytest.raises(BusinessError, match="gerado pela compra CP-2025/26-0001"):
            services.editar_custo(
                custo, {"amount": Decimal("5")}, usuario=gestor, motivo="x"
            )
        with pytest.raises(BusinessError, match="Corrija a compra"):
            services.excluir_custo(custo, usuario=gestor, motivo="x")


class TestTelas:
    def test_escritorio_lanca_pela_tela(
        self, client, escritorio, baixao, centro_funcionario, custeio
    ):
        client.force_login(escritorio)

        resposta = client.post(
            reverse("costs:novo"),
            {
                "date": "2025-09-18",
                "farm": baixao.pk,
                "cost_center": centro_funcionario.pk,
                "cost_class": custeio.pk,
                "amount": "2967.00",
                "description": "SALÁRIO ALDEMAR",
            },
        )

        assert resposta.status_code == 302
        assert CostEntry.objects.count() == 1

    def test_tela_recusa_lancamento_sem_centro(
        self, client, escritorio, baixao, custeio
    ):
        client.force_login(escritorio)

        resposta = client.post(
            reverse("costs:novo"),
            {
                "date": "2025-09-18",
                "farm": baixao.pk,
                "cost_class": custeio.pk,
                "amount": "10",
                "description": "x",
            },
        )

        assert resposta.status_code == 200
        assert CostEntry.objects.count() == 0
        assert "cost_center" in resposta.context["form"].errors

    def test_campo_nao_lanca_custo(self, client, campo_baixao):
        client.force_login(campo_baixao)

        assert client.get(reverse("costs:novo")).status_code == 403

    def test_custo_de_outra_fazenda_devolve_404_nao_403(
        self, client, campo_baixao, gestor, sao_francisco, centro_funcionario, custeio
    ):
        custo = lancar(gestor, sao_francisco, centro_funcionario, custeio)
        client.force_login(campo_baixao)

        assert client.get(reverse("costs:detalhe", args=[custo.pk])).status_code == 404
        assert client.get(reverse("costs:excluir", args=[custo.pk])).status_code == 404

    def test_lista_mostra_so_o_escopo_do_usuario(
        self,
        client,
        escritorio,
        gestor,
        baixao,
        sao_francisco,
        centro_funcionario,
        custeio,
    ):
        outro = User.objects.create_user(
            username="so_baixao", password="x", role=Role.ESCRITORIO
        )
        from apps.accounts.models import UserFarmAccess

        UserFarmAccess.objects.create(user=outro, farm=baixao, can_write=True)
        lancar(gestor, baixao, centro_funcionario, custeio, description="DO BAIXAO")
        lancar(gestor, sao_francisco, centro_funcionario, custeio, description="DO SFR")
        client.force_login(outro)

        resposta = client.get(reverse("costs:lista"))

        corpo = resposta.content.decode()
        assert "DO BAIXAO" in corpo
        assert "DO SFR" not in corpo

    def test_tela_de_exclusao_mostra_o_impacto_antes(
        self, client, gestor, baixao, centro_funcionario, custeio
    ):
        custo = lancar(gestor, baixao, centro_funcionario, custeio)
        client.force_login(gestor)

        resposta = client.get(reverse("costs:excluir", args=[custo.pk]))

        assert resposta.status_code == 200
        assert "Isto vai desfazer" in resposta.content.decode()
        assert "FUNCIONARIO" in resposta.content.decode()

    def test_post_sem_csrf_e_recusado(
        self, escritorio, baixao, custeio, centro_funcionario
    ):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(escritorio)

        resposta = client.post(reverse("costs:novo"), {"amount": "1"})

        assert resposta.status_code == 403
