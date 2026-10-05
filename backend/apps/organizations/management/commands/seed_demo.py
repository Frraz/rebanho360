import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User, UserFarmAccess
from apps.commercial.seed import garantir_cadastros_comerciais
from apps.core.management.mixins import InvalidaCacheDeResultados
from apps.costs.seed import garantir_classes_e_centros
from apps.livestock.models import AnimalCategory, Breed, Sex
from apps.organizations.models import BusinessUnit, Company, Season, SeasonStatus
from apps.properties.models import Farm

DEMO_PASSWORD = "demo12345"  # apenas dev/demo — nunca usado em produção

FARMS = [
    ("São Francisco", "SFR"),
    ("São Francisco II", "SF2"),
    ("Goiano", "GOI"),
    ("Baixão", "BXO"),
    ("Morada do Boi", "MDB"),
    ("São José do Grotão", "SJG"),
]

CATEGORIES = [
    ("Bezerros Mamando", Sex.MACHO, 1),
    ("Bezerras Mamando", Sex.FEMEA, 1),
    ("Machos Desm. até 12m", Sex.MACHO, 2),
    ("Fêmeas Desm. até 12m", Sex.FEMEA, 2),
    ("Machos 13 a 24 meses", Sex.MACHO, 3),
    ("Fêmeas 13 a 24 meses", Sex.FEMEA, 3),
    ("Machos 25 a 36 meses", Sex.MACHO, 4),
    ("Fêmeas 25 a 36 meses", Sex.FEMEA, 4),
    ("Touros", Sex.MACHO, 5),
    ("Fêmeas + 36 meses", Sex.FEMEA, 5),
    ("Tropa", Sex.INDEFINIDO, None),
]

# username, role, fazendas com acesso (vazio = ADMIN/GESTOR, que veem tudo por papel)
USERS = [
    ("admin@teste", Role.ADMIN, []),
    ("gestor@teste", Role.GESTOR, []),
    ("escritorio@teste", Role.ESCRITORIO, ["SFR", "SF2", "GOI", "BXO", "MDB", "SJG"]),
    ("campo@teste", Role.CAMPO, ["BXO"]),
    ("financeiro@teste", Role.FINANCEIRO, ["SFR", "SF2", "GOI", "BXO", "MDB", "SJG"]),
    ("consulta@teste", Role.CONSULTA, ["SFR", "GOI"]),
]


class Command(InvalidaCacheDeResultados, BaseCommand):
    help = (
        "Povoa um banco limpo com dados de desenvolvimento: empresa, safra "
        "2025/2026, as fazendas, um usuário por papel, categorias e centros "
        "de custo. Idempotente — pode rodar mais de uma vez."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        company = self._seed_company()
        unit = self._seed_business_unit(company)
        self._seed_season(company)
        farms = self._seed_farms(unit)
        self._seed_categories()
        self._seed_breeds()
        garantir_classes_e_centros()
        garantir_cadastros_comerciais()
        self._seed_users(farms)

        self.stdout.write(self.style.SUCCESS("seed_demo concluído."))
        self.stdout.write(f"Senha de todos os usuários de demo: {DEMO_PASSWORD}")

    def _seed_company(self) -> Company:
        company, _ = Company.objects.get_or_create(
            name="Fazendas Reunidas (demo)",
            defaults={"city": "Alvorada", "state": "TO"},
        )
        return company

    def _seed_business_unit(self, company: Company) -> BusinessUnit:
        unit, _ = BusinessUnit.objects.get_or_create(
            company=company, code="UN01", defaults={"name": "Unidade única"}
        )
        return unit

    def _seed_season(self, company: Company) -> Season:
        season, _ = Season.objects.get_or_create(
            company=company,
            name="2025/2026",
            defaults={
                "start_date": datetime.date(2025, 7, 1),
                "end_date": datetime.date(2026, 6, 30),
                "status": SeasonStatus.ABERTA,
                "is_current": True,
            },
        )
        return season

    def _seed_farms(self, unit: BusinessUnit) -> dict[str, Farm]:
        farms = {}
        for name, code in FARMS:
            farm, _ = Farm.objects.get_or_create(
                code=code, defaults={"name": name, "business_unit": unit}
            )
            farms[code] = farm
        return farms

    def _seed_categories(self) -> None:
        for order, (name, sex, age_order) in enumerate(CATEGORIES, start=1):
            AnimalCategory.objects.get_or_create(
                name=name,
                defaults={"sex": sex, "age_order": age_order, "display_order": order},
            )

    def _seed_breeds(self) -> None:
        Breed.objects.get_or_create(name="Nelore")

    def _seed_users(self, farms: dict[str, Farm]) -> None:
        for username, role, farm_codes in USERS:
            user, created = User.objects.get_or_create(
                username=username, defaults={"role": role, "email": username}
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.role = role
                user.save()

            for code in farm_codes:
                UserFarmAccess.objects.get_or_create(user=user, farm=farms[code])
