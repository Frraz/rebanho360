"""`seed_operacao_grande` e `desfazer_seed_operacao_grande`.

Rodam em escala reduzida (0,05) para a suíte não demorar. O que se prova:
o seed obedece às regras do sistema (razão fecha, nada negativo), não mexe em
usuário, e o desfazer devolve o banco ao estado anterior sem tocar no que não
é do seed e sem apagar a auditoria.
"""

from decimal import Decimal

import pytest
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum

from apps.accounts.models import Role, User, UserFarmAccess
from apps.audit.models import AuditEvent
from apps.costs.services import registrar_custo
from apps.herd.models import HerdLedgerEntry, HerdMovement
from apps.herd.selectors import conciliar_transferencias
from apps.livestock.models import AnimalCategory
from apps.organizations.models import Season
from apps.organizations.seed_operacao import catalogo as cat
from apps.partners.models import Partner
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db

ESCALA = Decimal("0.05")


def _semear():
    call_command("seed_operacao_grande", escala=ESCALA, force=True, verbosity=0)


def _desfazer(**kwargs):
    call_command(
        "desfazer_seed_operacao_grande", sim=True, force=True, verbosity=0, **kwargs
    )


def _contagens():
    """Linhas por tabela, menos a auditoria (que só cresce, por desenho)."""
    return {
        m._meta.label: m._base_manager.count()
        for m in apps.get_models()
        if m is not AuditEvent
    }


def _usuarios():
    return (
        list(
            User.objects.order_by("pk").values_list(
                "pk", "username", "role", "is_active", "password", "last_login"
            )
        ),
        sorted(UserFarmAccess.objects.values_list("user_id", "farm_id", "can_write")),
    )


@pytest.fixture
def base():
    call_command("seed_demo", verbosity=0)


class TestSeedEDesfazer:
    def test_ciclo_completo(self, base):
        usuarios_antes = _usuarios()
        # Dado "real" que não é do seed: tem de sobreviver a tudo.
        real = Farm.objects.create(name="Fazenda do Cliente", code="REAL1")
        parceiro_real = Partner.objects.create(name="Parceiro Real", notes="meu")
        antes = _contagens()
        auditoria_antes = AuditEvent.objects.count()

        _semear()

        # ---- o seed obedece às regras do sistema ----------------------------
        farms = Farm.objects.filter(code__startswith=cat.PREFIXO)
        assert farms.count() == 12
        assert (
            HerdLedgerEntry.objects.filter(farm__in=farms)
            .values("lot", "category")
            .annotate(s=Sum("quantity"))
            .filter(s__lt=0)
            .count()
            == 0
        ), "posição de rebanho negativa"
        assert list(conciliar_transferencias()) == []
        transferencias = HerdMovement.objects.filter(type="TRANSFERENCIA")
        assert transferencias.exists()
        for movimento in transferencias:
            soma = movimento.entries.aggregate(s=Sum("quantity"))["s"]
            assert soma == 0, f"{movimento.code} não fecha em zero"
        assert Season.objects.filter(name="2024/2025").exists()
        assert _usuarios() == usuarios_antes, "o seed alterou usuário ou acesso"

        # ---- rodar de novo é recusado ---------------------------------------
        with pytest.raises(CommandError, match="desfazer_seed_operacao_grande"):
            _semear()

        # ---- simular não apaga nada -----------------------------------------
        call_command(
            "desfazer_seed_operacao_grande", simular=True, force=True, verbosity=0
        )
        assert Farm.objects.filter(code__startswith=cat.PREFIXO).count() == 12

        # ---- desfazer devolve o banco ao que era ----------------------------
        _desfazer()
        assert _contagens() == antes
        assert _usuarios() == usuarios_antes
        assert Farm.objects.filter(pk=real.pk).exists()
        assert Partner.objects.filter(pk=parceiro_real.pk).exists()
        # a auditoria cresceu (criações do seed + o evento de desfazer) e nada sumiu
        assert AuditEvent.objects.count() > auditoria_antes
        assert AuditEvent.objects.filter(
            entity_type="SeedOperacaoGrande", action="DELETE"
        ).exists()

        # e dá para semear de novo
        _semear()
        assert Farm.objects.filter(code__startswith=cat.PREFIXO).count() == 12

    def test_desfazer_para_se_dado_real_depende_do_seed(self, base):
        _semear()
        admin = User.objects.get(username="admin@teste")
        real = Farm.objects.create(name="Fazenda do Cliente", code="REAL1")
        from apps.costs.models import CostCenter, CostClass

        safra = Season.objects.get(name="2025/2026")
        registrar_custo(
            date=safra.start_date,
            farm=real,
            cost_center=CostCenter.objects.first(),
            cost_class=CostClass.objects.first(),
            amount=Decimal("100.00"),
            description="Custo real pago a parceiro do seed",
            usuario=admin,
            payer=Partner.objects.filter(notes__startswith=cat.MARCADOR).first(),
        )
        antes = _contagens()

        with pytest.raises(CommandError, match="Nada foi apagado"):
            _desfazer()

        assert _contagens() == antes, "o desfazer apagou mesmo assim"

    def test_recusa_sem_debug_e_sem_force(self, base, settings):
        settings.DEBUG = False
        with pytest.raises(CommandError, match="DEBUG"):
            call_command("seed_operacao_grande", escala=ESCALA, verbosity=0)
        with pytest.raises(CommandError, match="DEBUG"):
            call_command("desfazer_seed_operacao_grande", sim=True, verbosity=0)

    def test_sem_administrador_nao_cria_usuario(self, base):
        User.objects.filter(role=Role.ADMIN).update(is_active=False)
        antes = User.objects.count()
        with pytest.raises(CommandError, match="ADMIN"):
            _semear()
        assert User.objects.count() == antes
        assert not Farm.objects.filter(code__startswith=cat.PREFIXO).exists()

    def test_nada_a_desfazer(self, base, capsys):
        call_command("desfazer_seed_operacao_grande", sim=True, force=True)
        assert "nada do seed" in capsys.readouterr().out.lower()
        assert AnimalCategory.objects.count() == 11
