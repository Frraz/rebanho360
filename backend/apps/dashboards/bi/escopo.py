"""O recorte de todo o dashboard: quem pergunta, qual safra, qual fazenda e até
que dia. Toda consulta nasce daqui, por `for_user()` (regra 4) — nenhum módulo
do BI chega ao banco sem passar pelo escopo.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from decimal import Decimal

from apps.accounts.models import Role
from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.finance.permissions import pode_ver_titulos
from apps.herd.models import HerdLedgerEntry, Weighing
from apps.livestock.models import Lot
from apps.organizations.models import Season
from apps.procurement.permissions import pode_ver_o_ciclo
from apps.purchases.models import Purchase
from apps.sales.models import Sale

#: Pessoal de campo vê o rebanho e o desempenho dos lotes, não o dinheiro:
#: preço, custo e resultado são dado comercial (pendência #48 — uma linha para
#: mudar).
PAPEIS_SEM_DINHEIRO = (Role.CAMPO,)


def pode_ver_dinheiro(user) -> bool:
    return user.is_authenticated and user.role not in PAPEIS_SEM_DINHEIRO


def primeiro_dia(data: datetime.date) -> datetime.date:
    return data.replace(day=1)


def somar_mes(mes: datetime.date) -> datetime.date:
    return (mes + datetime.timedelta(days=32)).replace(day=1)


def meses_entre(inicio: datetime.date, fim: datetime.date) -> list[datetime.date]:
    """Primeiro dia de cada mês de `inicio` a `fim`, inclusive."""
    meses, atual = [], primeiro_dia(inicio)
    while atual <= fim:
        meses.append(atual)
        atual = somar_mes(atual)
    return meses


@dataclass(frozen=True)
class Escopo:
    user: object
    season: Season | None
    farm: object | None
    hoje: datetime.date
    inicio: datetime.date
    fim: datetime.date
    ver_dinheiro: bool = True
    ver_titulos: bool = True
    ver_ciclo: bool = True
    # Escopo da safra anterior, no mesmo ponto — `None` na primeira safra.
    anterior: Escopo | None = None
    # Resultado de consultas caras, por requisição: a visão geral e a aba do
    # assunto pedem o mesmo número e ele é calculado uma vez só.
    _memo: dict = field(default_factory=dict, compare=False, repr=False)

    def memo(self, chave: str, calcular):
        if chave not in self._memo:
            self._memo[chave] = calcular()
        return self._memo[chave]

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    @staticmethod
    def fim_do_recorte(season, hoje) -> datetime.date:
        """O recorte vai até hoje, ou até o fim da safra se ela já acabou. Safra
        futura: o primeiro dia, vazio, em vez de um intervalo invertido."""
        return max(season.start_date, min(hoje, season.end_date))

    @classmethod
    def criar(cls, user, *, season, farm=None, hoje=None) -> Escopo | None:
        """`None` sem safra: não há recorte de tempo, e o painel diz isso."""
        if season is None:
            return None
        hoje = hoje or datetime.date.today()
        inicio = season.start_date
        fim = cls.fim_do_recorte(season, hoje)
        base = cls(
            user=user,
            season=season,
            farm=farm,
            hoje=hoje,
            inicio=inicio,
            fim=fim,
            ver_dinheiro=pode_ver_dinheiro(user),
            ver_titulos=pode_ver_titulos(user),
            ver_ciclo=pode_ver_o_ciclo(user),
        )
        previa = (
            Season.objects.filter(
                company_id=season.company_id, start_date__lt=season.start_date
            )
            .order_by("-start_date")
            .first()
        )
        if previa is None:
            return base
        # Mesmo ponto da safra anterior: se a atual vai no dia 90, a anterior
        # também vai até o dia 90 — comparar safra parcial com safra fechada
        # faria todo indicador de fluxo parecer em queda.
        passou = (fim - inicio).days
        fim_anterior = min(
            previa.end_date, previa.start_date + datetime.timedelta(passou)
        )
        return replace(
            base,
            anterior=replace(
                base,
                season=previa,
                inicio=previa.start_date,
                fim=fim_anterior,
                anterior=None,
                _memo={},  # nunca divide o cache com o escopo atual
            ),
        )

    # ------------------------------------------------------------------
    # Tempo
    # ------------------------------------------------------------------

    @property
    def meses(self) -> list[datetime.date]:
        return meses_entre(self.inicio, self.fim)

    @property
    def dias(self) -> int:
        return (self.fim - self.inicio).days + 1

    @property
    def rotulo_farm(self) -> str:
        return self.farm.name if self.farm else "Todas as fazendas"

    # ------------------------------------------------------------------
    # Consultas já escopadas (usuário, fazenda, safra e corte)
    # ------------------------------------------------------------------

    def _fazenda(self, qs, campo: str):
        return qs.filter(**{campo: self.farm}) if self.farm is not None else qs

    def compras(self):
        qs = Purchase.objects.for_user(self.user).filter(
            status=Status.CONFIRMADA, season=self.season, date__lte=self.fim
        )
        return self._fazenda(qs, "destination_farm")

    def vendas(self):
        qs = Sale.objects.for_user(self.user).filter(
            status=Status.CONFIRMADA, season=self.season, date__lte=self.fim
        )
        return self._fazenda(qs, "farm")

    def custos(self, *, com_os_da_compra: bool = False):
        """Sem os custos que a compra gera (frete, comissão...): já estão no
        "Comprado", e contá-los de novo dobraria a aquisição — o mesmo critério
        do painel inicial."""
        qs = CostEntry.objects.for_user(self.user).filter(
            status=Status.CONFIRMADA, season=self.season, date__lte=self.fim
        )
        if not com_os_da_compra:
            qs = qs.filter(source_purchase__isnull=True)
        return self._fazenda(qs, "farm")

    def razao(self, *, ate: datetime.date | None = None):
        """Linhas do razão da fazenda e dos lotes do escopo, até `ate` (padrão:
        a data de corte). Sem filtro de safra: saldo atravessa safras."""
        qs = HerdLedgerEntry.objects.for_user(self.user).filter(
            date__lte=ate or self.fim
        )
        return self._fazenda(qs, "farm")

    def movimentos(self):
        from apps.herd.selectors import listar_movimentos_para

        qs = listar_movimentos_para(self.user).filter(
            status=Status.CONFIRMADA, date__gte=self.inicio, date__lte=self.fim
        )
        if self.farm is not None:
            from django.db.models import Q

            qs = qs.filter(Q(origin_farm=self.farm) | Q(destination_farm=self.farm))
        return qs

    def pesagens(self):
        qs = Weighing.objects.for_user(self.user).filter(status=Status.CONFIRMADA)
        return self._fazenda(qs, "farm")

    def lotes(self):
        qs = Lot.objects.for_user(self.user)
        return self._fazenda(qs, "farm")

    def base_do_razao(self, farm):
        """O razão da fazenda até o corte, em memória e uma vez por requisição:
        cabeça-dia de qualquer janela sem voltar ao banco."""
        from apps.costs.allocation import BaseDeRateio

        return self.memo(
            f"base_do_razao:{farm.pk}", lambda: BaseDeRateio(farm, ate=self.fim)
        )

    def financeiro_dos_lotes(self, lotes) -> dict:
        """`{lot_id: financeiro}` dos lotes pedidos, calculado **uma vez por
        requisição** e só para o que ainda não se calculou: a aba de vendas e a
        de lotes pedem o mesmo custo (é a conta do `financeiro_do_lote`) e o
        rateio, que é a parte cara, não se repete."""
        from apps.livestock.selectors import (
            cabecas_que_entraram_por_lote,
            financeiro_dos_lotes,
        )

        guardado = self.memo("financeiro_dos_lotes", dict)
        faltam = [lt for lt in lotes if lt.pk not in guardado]
        if faltam:
            guardado.update(
                financeiro_dos_lotes(
                    faltam, entradas=cabecas_que_entraram_por_lote(faltam)
                )
            )
        return guardado

    def cor_da_fazenda(self, farm_id: int) -> int:
        """Posição fixa da fazenda na paleta categórica: a mesma fazenda tem a
        mesma cor em todo gráfico (a cor segue a entidade), e a oitava em diante
        divide a última cor — a paleta não tem mais de 8."""
        from apps.properties.models import Farm

        ids = self.memo(
            "ids_das_fazendas",
            lambda: list(
                Farm.objects.filter(is_active=True)
                .order_by("code")
                .values_list("pk", flat=True)
            ),
        )
        return min(ids.index(farm_id), 7) if farm_id in ids else 7

    def fazendas(self) -> list:
        """As fazendas que o recorte alcança: a escolhida, ou todas as do escopo
        do usuário (ADR 0003)."""
        from apps.core import context as ctx

        if self.farm is not None:
            return [self.farm]
        # Várias abas e gráficos pedem a lista: uma consulta por requisição.
        # `Farm` já ordena por nome; a lista é a mesma que a barra do topo usa
        # (`ctx.available_farms` é uma consulta só por requisição).
        return self.memo("fazendas", lambda: list(ctx.available_farms(self.user)))


ZERO = Decimal("0")

__all__ = [
    "Escopo",
    "ZERO",
    "meses_entre",
    "pode_ver_dinheiro",
    "primeiro_dia",
    "somar_mes",
]
