"""Reprodução resumida: o ciclo da fazenda na safra e os índices que saem dele
(cliente, 2026-10-03)."""

import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import AuditAction, AuditEvent
from apps.core.exceptions import BusinessError
from apps.core.reversible import Status
from apps.herd import services as rebanho
from apps.herd.models import MovementType
from apps.reproduction import indicators, services
from apps.reproduction.models import BreedingCycle

pytestmark = pytest.mark.django_db
D = Decimal

DADOS = dict(
    breeding_months=5,
    females_total=400,
    females_over_18m=300,
    heifers_exposed=40,
    heifers_pregnant=30,
    challenge_heifers_exposed=10,
    challenge_heifers_pregnant=6,
    primiparous_exposed=50,
    primiparous_pregnant=40,
    cows_exposed=100,
    cows_pregnant=84,
    inseminated=120,
    pregnant_by_ai=80,
    pregnant_by_bull=80,
    weaned_calves=150,
)


@pytest.fixture
def ciclo(gestor, sao_francisco, season):
    return services.registrar_ciclo(
        usuario=gestor, farm=sao_francisco, season=season, **DADOS
    )


class TestIndicadores:
    def test_os_indices_saem_dos_numeros_informados(self, ciclo):
        ind = indicators.indicadores_do_ciclo(ciclo)
        assert (ind.expostas, ind.prenhes, ind.vazias) == (200, 160, 40)
        assert ind.fertilidade_geral_pct == D("80")
        assert ind.fertilidade_por_grupo["Novilhas"] == D("75")
        assert ind.em_reproducao_pct == D("50")  # 200 ÷ 400
        assert ind.aproveitamento_pct == D("200") / D("300") * 100
        assert ind.inseminadas_pct == D("60")  # 120 ÷ 200
        assert ind.fertilidade_ia_pct == D("80") / D("120") * 100
        assert ind.fertilidade_touro_pct == D("100")  # 80 prenhes ÷ 80 sem inseminar

    def test_divisor_zero_devolve_none_nunca_zero(self, gestor, sao_francisco, season):
        c = services.registrar_ciclo(usuario=gestor, farm=sao_francisco, season=season)
        ind = indicators.indicadores_do_ciclo(c)
        assert ind.fertilidade_geral_pct is None
        assert ind.em_reproducao_pct is None and ind.desmama_pct is None
        assert ind.fertilidade_touro_pct is None

    def test_nascimentos_vem_do_razao_do_rebanho_e_alimentam_a_desmama(
        self, ciclo, gestor, sao_francisco, categoria_desmamados, lote_sao_francisco
    ):
        # sem nascimento lançado, a desmama não inventa percentual
        assert indicators.indicadores_do_ciclo(ciclo).desmama_pct is None
        rebanho.registrar_movimento(
            type=MovementType.NASCIMENTO,
            date=datetime.date(2025, 10, 10),
            quantity=200,
            usuario=gestor,
            destination_farm=sao_francisco,
            destination_lot=lote_sao_francisco,
            destination_category=categoria_desmamados,
        )
        ind = indicators.indicadores_do_ciclo(ciclo)
        assert ind.nascidos == 200 and ind.nascidos_machos == 200
        assert ind.desmama_pct == D("75")  # 150 ÷ 200


class TestRegras:
    def test_prenhes_nao_passam_das_expostas(self, gestor, sao_francisco, season):
        with pytest.raises(BusinessError, match="passam das fêmeas em monta"):
            services.registrar_ciclo(
                usuario=gestor,
                farm=sao_francisco,
                season=season,
                cows_exposed=10,
                cows_pregnant=11,
            )

    def test_prenhes_de_ia_nao_passam_das_inseminadas(
        self, gestor, sao_francisco, season
    ):
        with pytest.raises(BusinessError, match="inseminadas"):
            services.registrar_ciclo(
                usuario=gestor,
                farm=sao_francisco,
                season=season,
                cows_exposed=10,
                cows_pregnant=10,
                inseminated=2,
                pregnant_by_ai=5,
            )

    def test_um_ciclo_por_fazenda_e_safra(self, ciclo, gestor, sao_francisco, season):
        with pytest.raises(BusinessError, match="já tem o ciclo"):
            services.registrar_ciclo(
                usuario=gestor, farm=sao_francisco, season=season, **DADOS
            )

    def test_banco_tambem_recusa_prenhe_acima_de_exposta(self, ciclo):
        with pytest.raises(IntegrityError):
            BreedingCycle.objects.filter(pk=ciclo.pk).update(cows_pregnant=999)

    def test_consulta_nao_lanca(self, sao_francisco, season):
        consulta = User.objects.create_user(
            username="c", password="x", role=Role.CONSULTA
        )
        with pytest.raises(BusinessError, match="permissão"):
            services.registrar_ciclo(
                usuario=consulta, farm=sao_francisco, season=season
            )


class TestCorrigirEExcluir:
    def test_corrigir_pede_motivo_e_audita(self, ciclo, gestor):
        with pytest.raises(BusinessError, match="(?i)motivo"):
            services.editar_ciclo(
                ciclo, {"weaned_calves": 140}, usuario=gestor, motivo=""
            )
        services.editar_ciclo(
            ciclo, {"weaned_calves": 140}, usuario=gestor, motivo="Recontagem"
        )
        ciclo.refresh_from_db()
        assert ciclo.weaned_calves == 140 and ciclo.version == 2
        assert AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity_id=str(ciclo.pk), reason="Recontagem"
        ).exists()

    def test_exclusao_e_logica_e_restaura(self, ciclo, gestor):
        services.excluir_ciclo(ciclo, usuario=gestor, motivo="Lançado errado")
        ciclo.refresh_from_db()
        assert ciclo.status == Status.EXCLUIDA
        assert BreedingCycle.objects.filter(pk=ciclo.pk).exists()  # nunca sai do banco
        services.restaurar_ciclo(ciclo, usuario=gestor)
        ciclo.refresh_from_db()
        assert ciclo.status == Status.CONFIRMADA

    def test_pode_lancar_outro_depois_de_excluir(
        self, ciclo, gestor, sao_francisco, season
    ):
        services.excluir_ciclo(ciclo, usuario=gestor, motivo="Duplicado")
        novo = services.registrar_ciclo(
            usuario=gestor, farm=sao_francisco, season=season, **DADOS
        )
        assert novo.code != ciclo.code


class TestTelas:
    def test_lista_detalhe_e_formulario_abrem(self, client, ciclo, gestor):
        client.force_login(gestor)
        assert client.get(reverse("reproduction:lista")).status_code == 200
        html = client.get(
            reverse("reproduction:detalhe", args=[ciclo.pk])
        ).content.decode()
        assert ciclo.code in html and "80,0%" in html
        assert client.get(reverse("reproduction:novo")).status_code == 200
        assert (
            client.get(reverse("reproduction:editar", args=[ciclo.pk])).status_code
            == 200
        )

    def test_lancar_pela_tela(self, client, gestor, sao_francisco, season):
        client.force_login(gestor)
        resposta = client.post(
            reverse("reproduction:novo"),
            {
                "farm": sao_francisco.pk,
                "season": season.pk,
                **{k: str(v) for k, v in DADOS.items()},
            },
        )
        assert resposta.status_code == 302
        assert BreedingCycle.objects.count() == 1

    def test_fora_do_escopo_da_fazenda_da_404(self, client, ciclo, baixao):
        from apps.accounts.models import UserFarmAccess

        so_baixao = User.objects.create_user(
            username="b", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=so_baixao, farm=baixao, can_write=True)
        client.force_login(so_baixao)
        assert (
            client.get(reverse("reproduction:detalhe", args=[ciclo.pk])).status_code
            == 404
        )
