"""Histórico de duas safras para ver o dashboard cheio (dev e demonstração).

    python manage.py seed_demo && python manage.py seed_demo_bi

Usa os **serviços** do sistema (compra, movimento, pesagem, venda, custo, título,
baixa, compromisso), então todo número nasce pelas mesmas regras de produção: o
razão fecha, o título é gerado, o custo é rateado. Determinístico (semente fixa):
rodar duas vezes no mesmo banco não duplica — o marcador `[demo-bi]` nas
observações das compras detecta a carga anterior.

Nunca roda em produção: inventa compras, vendas e pagamentos. Por isso recusa
`DEBUG=False`.
"""

import datetime
import random
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.commercial.models import CarcassClass
from apps.core.exceptions import BusinessError
from apps.costs.models import CostCenter, CostClass
from apps.costs.services import registrar_custo
from apps.finance import services as financeiro
from apps.finance.models import Invoice, PaymentMethod, PaymentStatus
from apps.herd import services as herd
from apps.herd.models import (
    DeathCause,
    HerdLedgerEntry,
    MovementType,
    WeighingReason,
)
from apps.livestock.models import AnimalCategory, Breed
from apps.organizations.models import Company, Season, SeasonStatus
from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
from apps.procurement import closing, commitments, grading, receivings, trips
from apps.properties.models import Farm
from apps.purchases import services as compras
from apps.sales import services as vendas

D = Decimal
MARCADOR = "[demo-bi]"

#: nome → (peso médio na compra em kg, R$ por kg vivo, peso de abate-alvo)
CATEGORIAS = {
    "Machos Desm. até 12m": (D("205"), D("15.2")),
    "Machos 13 a 24 meses": (D("305"), D("12.9")),
    "Machos 25 a 36 meses": (D("425"), D("12.1")),
    "Fêmeas 13 a 24 meses": (D("272"), D("11.4")),
    "Fêmeas 25 a 36 meses": (D("360"), D("10.9")),
}
VENDEDORES = [
    ("Waldemar Secchi", 30),
    ("Agropecuária Boa Vista", 18),
    ("Faz. Santa Luzia", 12),
    ("José Carlos Tavares", 9),
    ("Pecuária Três Irmãos", 8),
    ("Agro Cerrado", 7),
    ("Marcos Oliveira", 6),
    ("Fazenda Barra Grande", 5),
    ("Pedro Henrique Lima", 5),
]
COMPRADORES = [
    ("COPERFRIGU", PartnerRoleChoice.FRIGORIFICO),
    ("Frigorífico Vale do Tocantins", PartnerRoleChoice.FRIGORIFICO),
    ("Marfrig Araguaína", PartnerRoleChoice.FRIGORIFICO),
    ("Açougue Real", PartnerRoleChoice.COMPRADOR),
]
TRANSPORTADORES = ["Transportes Tocantins", "Frota Araguaia", "Boiadeiro Express"]
# centro → (R$/mês de base por 1.000 cabeças, classe)
CENTROS = {
    "FUNCIONARIO": (D("11000"), "CUSTEIO"),
    "PARQUE DE MÁQUINAS": (D("6800"), "CUSTEIO"),
    "NUTRIÇÃO": (D("9700"), "CUSTEIO"),
    "PASTAGEM": (D("8100"), "CUSTEIO"),
    "SANIDADE": (D("2100"), "CUSTEIO"),
    "INFRAESTRUTURA": (D("2900"), "INVESTIMENTO"),
    "IMPOSTO E TAXAS": (D("800"), "CUSTEIO"),
    "OUTROS": (D("850"), "CUSTEIO"),
    "DESPESA GADO": (D("1700"), "CUSTEIO"),
}


def mes_mais(data: datetime.date, n: int) -> datetime.date:
    total = data.year * 12 + data.month - 1 + n
    return datetime.date(total // 12, total % 12 + 1, 1)


def q2(x) -> Decimal:
    return Decimal(x).quantize(D("0.01"))


class Command(BaseCommand):
    help = "Cria o histórico de duas safras (compras, pesagens, mortes, vendas, custos, títulos, baixas e compromissos) para o dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--semente", type=int, default=360)

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError(
                "Recusado: este comando inventa dados e só roda com DEBUG=True."
            )
        if compras.Purchase.objects.filter(notes__startswith=MARCADOR).exists():
            self.stdout.write("A carga demo-bi já existe neste banco; nada a fazer.")
            return
        self.rnd = random.Random(opts["semente"])
        self.hoje = timezone.localdate()
        self.admin = User.objects.get(username="admin@teste")
        self.gestor = User.objects.get(username="gestor@teste")
        self.company = Company.objects.filter(is_active=True).order_by("id").first()
        self._cadastros()
        for inicio_ano in (2024, 2025, 2026):
            self._safra(inicio_ano)
        self._ciclo_de_compra()
        self._pagamentos()
        self.stdout.write(
            self.style.SUCCESS(
                f"Carga demo-bi pronta: {HerdLedgerEntry.objects.count()} linhas no razão, "
                f"{Invoice.objects.count()} títulos."
            )
        )

    # ------------------------------------------------------------------ base
    def _cadastros(self):
        for ano in (2024, 2025, 2026):
            Season.objects.get_or_create(
                company=self.company,
                name=f"{ano}/{ano + 1}",
                defaults={
                    "start_date": datetime.date(ano, 7, 1),
                    "end_date": datetime.date(ano + 1, 6, 30),
                    "status": SeasonStatus.ABERTA,
                    "is_current": False,
                },
            )
        self.fazendas = list(
            Farm.objects.filter(
                is_active=True, business_unit__company=self.company
            ).order_by("code")
        )
        # Áreas e tamanhos para a lotação (só aparece onde a área existe).
        areas = [820, 640, 910, 380, 520, 700, 0]
        for f, a in zip(self.fazendas, areas, strict=False):
            if a:
                f.pasture_area_ha = D(a)
                f.total_area_ha = D(round(a * 1.18))
                f.save(update_fields=["pasture_area_ha", "total_area_ha"])
        # Pesos relativos por fazenda (tamanho do rebanho).
        self.peso_fazenda = [1.35, 1.0, 1.5, 0.7, 0.9, 1.1, 0.4][: len(self.fazendas)]
        self.vendedores = [
            self._parceiro(n, PartnerRoleChoice.PRODUTOR) for n, _ in VENDEDORES
        ]
        self.pesos_vendedor = [p for _, p in VENDEDORES]
        self.compradores = [self._parceiro(n, r) for n, r in COMPRADORES]
        self.transportadores = [
            self._parceiro(n, PartnerRoleChoice.TRANSPORTADOR) for n in TRANSPORTADORES
        ]
        self.comissionado = self._parceiro(
            "Cláudia Ferreira", PartnerRoleChoice.COMISSIONADO
        )
        self.categorias = {
            c.name: c for c in AnimalCategory.objects.filter(name__in=CATEGORIAS)
        }
        self.raca = Breed.objects.filter(name="Nelore").first()
        self.centros = {c.name: c for c in CostCenter.objects.filter(name__in=CENTROS)}
        self.classes = {c.name: c for c in CostClass.objects.all()}

    def _parceiro(self, nome, papel):
        p, _ = Partner.objects.get_or_create(name=nome)
        PartnerRole.objects.get_or_create(partner=p, role=papel)
        return p

    # ----------------------------------------------------------------- safra
    def _safra(self, ano):
        """Compras de jul a mar, pesagens a cada ~50 dias, mortes, abates a partir
        de ~6 meses, custos mensais. Tudo até hoje."""
        inicio = datetime.date(ano, 7, 1)
        tendencia = 1.0 + 0.06 * (ano - 2024)  # preços sobem de uma safra para a outra
        lotes = []
        for m in range(9):
            mes = mes_mais(inicio, m)
            for _ in range(self.rnd.choice([3, 4, 4, 5])):
                data = mes + datetime.timedelta(days=self.rnd.randrange(0, 27))
                if data > self.hoje:
                    continue
                lote = self._compra(data, tendencia * (1 + 0.012 * m))
                if lote:
                    lotes.append(lote)
        for lote in lotes:
            self._vida_do_lote(lote, tendencia)
        self._custos(inicio)

    def _compra(self, data, preco):
        nome = self.rnd.choices(list(CATEGORIAS), weights=[18, 30, 27, 17, 8])[0]
        peso_medio, preco_kg = CATEGORIAS[nome]
        cabecas = self.rnd.randrange(28, 150)
        peso_medio = peso_medio * D(str(self.rnd.uniform(0.93, 1.07)))
        peso_total = q2(peso_medio * cabecas)
        valor = q2(
            peso_total * preco_kg * D(str(preco)) * D(str(self.rnd.uniform(0.95, 1.06)))
        )
        fazenda = self.rnd.choices(self.fazendas, weights=self.peso_fazenda)[0]
        vendedor = self.rnd.choices(self.vendedores, weights=self.pesos_vendedor)[0]
        try:
            compra = compras.criar_compra(
                usuario=self.admin,
                date=data,
                seller=vendedor,
                destination_farm=fazenda,
                category=self.categorias[nome],
                head_count=cabecas,
                total_weight_kg=peso_total,
                animal_value=valor,
                freight_value=q2(valor * D(str(self.rnd.uniform(0.008, 0.02)))),
                commission_value=(
                    q2(valor * D("0.01")) if self.rnd.random() < 0.45 else 0
                ),
                tax_value=q2(valor * D("0.0035")) if self.rnd.random() < 0.2 else 0,
                payment_days=self.rnd.choice([0, 15, 30, 30, 45]),
                notes=f"{MARCADOR} compra de teste",
            )
            compra = compras.confirmar_compra(compra, usuario=self.admin)
        except BusinessError as exc:
            self.stderr.write(f"compra ignorada ({data}): {exc}")
            return None
        lote = compra.lot
        if lote and self.raca and not lote.breed_id:
            lote.breed = self.raca
            lote.save(update_fields=["breed"])
        # Pesagem de entrada.
        self._pesar(lote, fazenda, data, WeighingReason.COMPRA, cabecas, peso_total)
        return lote

    def _pesar(self, lote, fazenda, data, motivo, cabecas, peso_total):
        if data > self.hoje or cabecas <= 0:
            return
        try:
            herd.registrar_pesagem(
                date=data,
                farm=fazenda,
                lot=lote,
                reason=motivo,
                head_count=cabecas,
                total_weight_kg=q2(peso_total),
                usuario=self.admin,
            )
        except BusinessError as exc:
            self.stderr.write(f"pesagem ignorada: {exc}")

    def _saldo(self, lote):
        return herd.saldo(lot=lote)["head_count"]

    def _vida_do_lote(self, lote, tendencia):
        compra = lote.origin_purchase
        fazenda, cat = lote.farm, compra.category
        gmd = D(str(self.rnd.uniform(0.28, 0.98)))
        peso_medio = compra.total_weight_kg / compra.head_count
        data = compra.date
        # Mortes pequenas, concentradas em algumas fazendas e lotes.
        if self.rnd.random() < (0.55 if fazenda.code in {"BXO", "GOI"} else 0.28):
            quando = data + datetime.timedelta(days=self.rnd.randrange(15, 120))
            if quando <= self.hoje:
                try:
                    cabecas_mortas = self.rnd.randrange(1, 4)
                    herd.registrar_movimento(
                        type=MovementType.MORTE,
                        date=quando,
                        quantity=cabecas_mortas,
                        # Parte das mortes sem causa e sem peso: é o que acontece no
                        # campo, e a aba Mortes tem de mostrar a falta de dado.
                        death_cause=(
                            self.rnd.choice(DeathCause.values)
                            if self.rnd.random() < 0.75
                            else ""
                        ),
                        total_weight_kg=(
                            (peso_medio * cabecas_mortas).quantize(D("0.001"))
                            if self.rnd.random() < 0.6
                            else None
                        ),
                        usuario=self.admin,
                        origin_farm=fazenda,
                        origin_lot=lote,
                        origin_category=cat,
                        reason=(
                            "Picada de cobra / timpanismo"
                            if self.rnd.random() < 0.5
                            else "Doença respiratória"
                        ),
                    )
                except BusinessError:
                    pass
        # Pesagens de acompanhamento.
        dias = 0
        while True:
            passo = self.rnd.randrange(42, 64)
            if data + datetime.timedelta(days=dias + passo) > self.hoje:
                break
            dias += passo
            saldo = self._saldo(lote)
            if saldo <= 0:
                break
            peso_dia = peso_medio + gmd * dias
            self._pesar(
                lote,
                fazenda,
                data + datetime.timedelta(days=dias),
                WeighingReason.CONFERENCIA,
                saldo,
                peso_dia * saldo,
            )
        # Abate: quem passa de ~210 dias e tem categoria de recria/engorda.
        dias_de_pasto = self.rnd.randrange(185, 285)
        quando = data + datetime.timedelta(days=dias_de_pasto)
        if quando > self.hoje or self.rnd.random() < 0.18:
            return
        saldo = self._saldo(lote)
        if saldo <= 0:
            return
        fatias = (
            [saldo] if self.rnd.random() < 0.6 else [saldo // 2, saldo - saldo // 2]
        )
        for i, cabecas in enumerate(fatias):
            if cabecas <= 0:
                continue
            quando_i = quando + datetime.timedelta(days=21 * i)
            if quando_i > self.hoje:
                break
            vivo = (peso_medio + gmd * (dias_de_pasto + 21 * i)) * cabecas
            rendimento = (
                D(str(self.rnd.uniform(0.505, 0.545)))
                if self.rnd.random() > 0.07
                else D("0.445")
            )
            carcaca = vivo * rendimento
            arroba = D(str(self.rnd.uniform(282, 312) * tendencia))
            tipo = "ABATE"
            try:
                venda = vendas.criar_venda(
                    usuario=self.admin,
                    date=quando_i,
                    type=tipo,
                    buyer=self.rnd.choice(self.compradores[:3]),
                    farm=fazenda,
                    lot=lote,
                    category=cat,
                    head_count=cabecas,
                    total_weight_kg=q2(vivo),
                    carcass_weight_kg=q2(carcaca) if self.rnd.random() > 0.04 else None,
                    total_value=q2(carcaca / 15 * arroba),
                    payment_days=self.rnd.choice([7, 15, 30]),
                    sale_form="PASTO",
                )
                vendas.confirmar_venda(venda, usuario=self.admin)
            except BusinessError as exc:
                self.stderr.write(f"venda ignorada: {exc}")

    # ---------------------------------------------------------------- custos
    def _custos(self, inicio):
        for m in range(12):
            mes = mes_mais(inicio, m)
            if mes > self.hoje:
                break
            for fazenda, peso in zip(self.fazendas, self.peso_fazenda, strict=False):
                base_cabecas = herd.saldo(farm=fazenda, until=mes)["head_count"]
                if base_cabecas <= 0:
                    continue
                for nome, (por_mil, classe) in CENTROS.items():
                    if self.rnd.random() < 0.12:
                        continue
                    valor = q2(
                        por_mil
                        * D(base_cabecas)
                        / 1000
                        * D(str(self.rnd.uniform(0.8, 1.25)))
                    )
                    if valor <= 0:
                        continue
                    data = mes + datetime.timedelta(days=self.rnd.randrange(2, 26))
                    if data > self.hoje:
                        continue
                    try:
                        registrar_custo(
                            date=data,
                            farm=fazenda,
                            cost_center=self.centros[nome],
                            cost_class=self.classes[classe],
                            amount=valor,
                            description=f"{nome.title()} — {data:%m/%Y}",
                            usuario=self.admin,
                        )
                    except BusinessError as exc:
                        self.stderr.write(f"custo ignorado: {exc}")

    # ---------------------------------------------------------------- ciclo
    def _ciclo_de_compra(self):
        """Compromissos em todas as etapas: aprovado, programado, em viagem,
        recebido sem acerto, em acerto e acerto aprovado."""
        farm = self.fazendas[0]
        categoria = self.categorias["Machos 25 a 36 meses"]
        classe = CarcassClass.objects.filter(code="MEDIANA").first()
        if classe is None:
            return
        etapas = [
            "APROVADO",
            "PROGRAMADO",
            "VIAGEM",
            "RECEBIDO",
            "ACERTO",
            "FECHADO",
            "FECHADO",
            "FECHADO",
        ]
        for i, etapa in enumerate(etapas):
            data = datetime.date(2025, 9, 1) + datetime.timedelta(days=24 * i)
            if data > self.hoje:
                continue
            produtor = self.vendedores[i % len(self.vendedores)]
            try:
                item = {
                    "category": categoria,
                    "head_count": 40 + 10 * i,
                    "avg_weight_kg": D("480"),
                    "price_basis": "ARROBA",
                    "price_band_1": D("216"),
                    "price_band_2": D("237.6"),
                    "price_band_3": D("248.4"),
                    "price_band_4": D("270"),
                    "price_band_5": D("270"),
                    "expected_arrobas": D("17"),
                    "expected_band": 4,
                }
                comp = commitments.criar_compromisso(
                    usuario=self.admin,
                    itens=[item],
                    date=data,
                    seller=produtor,
                    destination_farm=farm,
                    commissioned=self.comissionado,
                    payment_days=30,
                    pickup_date=(
                        data + datetime.timedelta(days=3)
                        if etapa != "APROVADO"
                        else None
                    ),
                    slaughter_date=data + datetime.timedelta(days=12),
                    trucks=2,
                    distance_km=140 + 20 * i,
                )
                comp = commitments.aprovar_compromisso(comp, usuario=self.gestor)
                if etapa in ("APROVADO", "PROGRAMADO"):
                    continue
                it = comp.items.get(number=1)
                cab = 40 + 10 * i
                viagem = trips.criar_viagem(
                    usuario=self.admin,
                    compromisso=comp,
                    pickup_date=data + datetime.timedelta(days=3),
                    carrier=self.transportadores[i % 3],
                    freight_criterion="POR_CABECA",
                    freight_rate=D("62"),
                    freight_actual=q2(D(cab) * D(str(self.rnd.uniform(58, 74)))),
                    cargas=[
                        {
                            "item": it,
                            "planned_qty": cab,
                            "shipped_qty": cab,
                            "origin_weight_kg": D(cab) * D("492"),
                        }
                    ],
                )
                if etapa == "VIAGEM":
                    continue
                quebra = D(str(self.rnd.uniform(0.012, 0.062)))
                receivings.criar_recebimento(
                    usuario=self.admin,
                    viagem=viagem,
                    date=data + datetime.timedelta(days=4),
                    linhas=[
                        {
                            "load": viagem.loads.get(),
                            "received_qty": cab,
                            "received_weight_kg": q2(D(cab) * D("492") * (1 - quebra)),
                        }
                    ],
                )
                if etapa == "RECEBIDO":
                    continue
                grading.registrar_romaneio(
                    it,
                    [
                        {
                            "carcass_class": classe,
                            "band": 4,
                            "head_count": cab,
                            "carcass_weight_kg": q2(D(cab) * D("255")),
                        }
                    ],
                    usuario=self.admin,
                )
                acerto = closing.criar_acerto(
                    usuario=self.admin,
                    compromisso=comp,
                    date=data + datetime.timedelta(days=15),
                )
                if etapa == "FECHADO" and acerto.date <= self.hoje:
                    closing.aprovar_acerto(acerto, usuario=self.gestor)
            except BusinessError as exc:
                self.stderr.write(f"compromisso {i} ({etapa}) parou: {exc}")

    # ------------------------------------------------------------ pagamentos
    def _pagamentos(self):
        """Quita o que venceu há mais de ~20 dias (alguns em parte) e deixa o
        resto em aberto, com atrasos reais."""
        metodos = [
            PaymentMethod.PIX,
            PaymentMethod.TED,
            PaymentMethod.PIX,
            PaymentMethod.BOLETO,
        ]
        for titulo in Invoice.objects.filter(status="CONFIRMADA").order_by(
            "due_date", "id"
        ):
            if titulo.payment_status != PaymentStatus.A_PAGAR:
                continue
            idade = (self.hoje - titulo.due_date).days
            if idade < 20 or self.rnd.random() < 0.1:
                continue
            valor = (
                titulo.amount
                if self.rnd.random() > 0.12
                else q2(titulo.amount * D("0.6"))
            )
            try:
                if titulo.direction == "PAGAR":
                    if titulo.payee_id is None:
                        # Frete e comissão nascem sem favorecido: em produção alguém informa.
                        favorecido = {
                            "FRETE": self.transportadores[titulo.pk % 3],
                            "COMISSAO": self.comissionado,
                        }.get(titulo.component, self.vendedores[0])
                        Invoice.objects.filter(pk=titulo.pk).update(payee=favorecido)
                        titulo.refresh_from_db()
                    financeiro.programar_titulo(
                        titulo, usuario=self.admin, data=self.hoje
                    )
                    financeiro.aprovar_titulo(titulo, usuario=self.gestor)
                data = min(
                    titulo.due_date + datetime.timedelta(days=self.rnd.randrange(0, 6)),
                    self.hoje,
                )
                financeiro.baixar_titulo(
                    titulo,
                    usuario=self.admin,
                    date=data,
                    amount=valor,
                    method=self.rnd.choice(metodos),
                    document=f"DOC-{titulo.pk:05d}",
                )
            except BusinessError as exc:
                self.stderr.write(f"baixa ignorada ({titulo.code}): {exc}")
