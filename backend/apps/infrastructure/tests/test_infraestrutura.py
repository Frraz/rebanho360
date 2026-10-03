"""Infraestrutura e parque de máquinas, resumidos (cliente, 2026-10-03)."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User, UserFarmAccess
from apps.core.exceptions import BusinessError
from apps.core.reversible import Status
from apps.infrastructure import indicators, services
from apps.infrastructure.models import FarmStructure, Machine, StructureKind

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def trator(gestor, sao_francisco):
    m = Machine(
        farm=sao_francisco, name="Trator 7230", kind="TRATOR", new_value=D("350000")
    )
    return services.salvar_cadastro(m, usuario=gestor, criando=True)


def uso(machine, usuario, **extra):
    dados = {
        "date": datetime.date(2025, 9, 1),
        "hours": D("100"),
        "fuel_liters": D("800"),
        "fuel_cost": D("4800"),
        "maintenance_cost": D("1500"),
        **extra,
    }
    return services.registrar_uso(usuario=usuario, machine=machine, **dados)


class TestCustoHora:
    def test_custo_hora_sai_do_que_foi_lancado(self, trator, gestor):
        uso(trator, gestor)
        uso(
            trator,
            gestor,
            hours=D("100"),
            fuel_liters=D("700"),
            fuel_cost=D("4200"),
            maintenance_cost=D("500"),
        )
        c = indicators.custo_hora_da_maquina(trator)
        assert c.horas == D("200")
        assert c.consumo_l_h == D("7.5")  # 1.500 L ÷ 200 h
        assert c.custo_hora_combustivel == D("45")  # 9.000 ÷ 200
        assert c.custo_hora_manutencao == D("10")  # 2.000 ÷ 200
        assert c.custo_hora == D("55")

    def test_sem_uso_devolve_none_nunca_zero(self, trator):
        c = indicators.custo_hora_da_maquina(trator)
        assert c.custo_hora is None and c.consumo_l_h is None

    def test_uso_excluido_sai_da_conta(self, trator, gestor):
        a = uso(trator, gestor)
        uso(trator, gestor, hours=D("100"), fuel_cost=D("0"), maintenance_cost=D("0"))
        services.excluir_uso(a, usuario=gestor, motivo="Lançado duas vezes")
        assert indicators.custo_hora_da_maquina(trator).horas == D("100")


class TestUso:
    def test_horas_obrigatorias_e_positivas(self, trator, gestor):
        with pytest.raises(BusinessError, match="horas"):
            uso(trator, gestor, hours=D("0"))

    def test_campo_lanca_mas_nao_cadastra(self, trator, sao_francisco):
        campo = User.objects.create_user(username="cp", password="x", role=Role.CAMPO)
        UserFarmAccess.objects.create(user=campo, farm=sao_francisco, can_write=True)
        assert uso(trator, campo).status == Status.CONFIRMADA
        with pytest.raises(BusinessError, match="permissão"):
            services.salvar_cadastro(
                Machine(farm=sao_francisco, name="Outro", kind="TRATOR"),
                usuario=campo,
                criando=True,
            )

    def test_corrigir_pede_motivo(self, trator, gestor):
        u = uso(trator, gestor)
        with pytest.raises(BusinessError, match="(?i)motivo"):
            services.editar_uso(u, {"hours": D("90")}, usuario=gestor, motivo="")
        services.editar_uso(
            u, {"hours": D("90")}, usuario=gestor, motivo="Horímetro conferido"
        )
        u.refresh_from_db()
        assert u.hours == D("90") and u.version == 2

    def test_maquina_inativa_nao_recebe_uso(self, trator, gestor):
        trator.is_active = False
        trator.save()
        with pytest.raises(BusinessError, match="inativa"):
            uso(trator, gestor)


class TestEstrutura:
    def test_razoes_sao_calculadas_e_none_sem_dado(self, gestor, sao_francisco):
        e = services.salvar_cadastro(
            FarmStructure(
                farm=sao_francisco,
                kind=StructureKind.CURRAL,
                name="Curral 1",
                area_m2=D("1408"),
                trough_m=D("60"),
                waterers=1,
                animals=150,
            ),
            usuario=gestor,
            criando=True,
        )
        assert round(e.area_por_animal, 2) == D("9.39")
        assert e.cocho_cm_por_cabeca == D("40")
        assert e.animais_por_bebedouro == D("150")
        vazio = FarmStructure(farm=sao_francisco, kind=StructureKind.CERCA, name="C")
        assert vazio.area_por_animal is None and vazio.cocho_cm_por_cabeca is None

    def test_fazenda_sem_acesso_e_recusada(self, sao_francisco, baixao):
        so_baixao = User.objects.create_user(
            username="sb", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=so_baixao, farm=baixao, can_write=True)
        with pytest.raises(BusinessError, match="permissão de lançamento"):
            services.salvar_cadastro(
                FarmStructure(farm=sao_francisco, kind="CURRAL", name="X"),
                usuario=so_baixao,
                criando=True,
            )


class TestTelas:
    def test_listas_e_detalhe_abrem(self, client, gestor, trator):
        client.force_login(gestor)
        assert client.get(reverse("infrastructure:estrutura_lista")).status_code == 200
        assert client.get(reverse("infrastructure:maquina_lista")).status_code == 200
        html = client.get(
            reverse("infrastructure:maquina_detalhe", args=[trator.pk])
        ).content.decode()
        assert "Trator 7230" in html

    def test_lancar_uso_pela_tela(self, client, gestor, trator):
        client.force_login(gestor)
        resposta = client.post(
            reverse("infrastructure:uso_novo", args=[trator.pk]),
            {"date": "2025-09-01", "hours": "8", "fuel_liters": "60"},
        )
        assert resposta.status_code == 302
        assert trator.logs.count() == 1

    def test_fora_do_escopo_da_fazenda_da_404(self, client, trator, baixao):
        so_baixao = User.objects.create_user(
            username="sb", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=so_baixao, farm=baixao, can_write=True)
        client.force_login(so_baixao)
        assert (
            client.get(
                reverse("infrastructure:maquina_detalhe", args=[trator.pk])
            ).status_code
            == 404
        )
