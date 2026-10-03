"""Cadastros do seed: safras, unidades, fazendas, pastos, parceiros, contas,
regras de comissão, estruturas, máquinas e (opcionalmente) acessos.

Tudo pelos serviços de cadastro, que gravam auditoria — a criação de cada
safra fica registrada com o `request_id` do seed, que é como o desfazer sabe
quais safras ele criou e quais já existiam.
"""

import datetime

from django.core.management.base import CommandError

from apps.accounts.models import Role, User, UserFarmAccess
from apps.commercial import services as comercial
from apps.commercial.models import (
    CarcassClass,
    CommissionRule,
    PaymentCondition,
    TaxType,
)
from apps.commercial.seed import garantir_cadastros_comerciais
from apps.costs.models import CostCenter, CostClass
from apps.costs.seed import garantir_classes_e_centros
from apps.infrastructure import services as infra_services
from apps.infrastructure.models import FarmStructure, Machine
from apps.livestock import services as livestock_services
from apps.livestock.models import AnimalCategory, Breed
from apps.organizations import services as org_services
from apps.organizations.models import BusinessUnit, Season, SeasonStatus
from apps.partners import services as partner_services
from apps.partners.models import BankAccount, Partner
from apps.properties import services as property_services
from apps.properties.models import Farm, Paddock

from . import catalogo as cat
from .util import D, decimal_entre, inteiro_proporcional

SAFRAS = [
    ("2024/2025", datetime.date(2024, 7, 1), datetime.date(2025, 6, 30)),
    ("2025/2026", datetime.date(2025, 7, 1), datetime.date(2026, 6, 30)),
    ("2026/2027", datetime.date(2026, 7, 1), datetime.date(2027, 6, 30)),
]


# --------------------------------------------------------------------------
# Referências compartilhadas (já existem; só se cria o que falta)
# --------------------------------------------------------------------------


def preparar_referencias(ctx):
    garantir_classes_e_centros()
    garantir_cadastros_comerciais()

    for nome, (sexo, ordem) in cat.CATEGORIAS_PADRAO.items():
        categoria = AnimalCategory.objects.filter(name=nome).first()
        if categoria is None:
            categoria = AnimalCategory(
                name=nome, sex=sexo, age_order=ordem, display_order=ordem or 99
            )
            livestock_services.salvar_cadastro(
                categoria, usuario=ctx.admin, criando=True
            )
        ctx.categorias[nome] = categoria

    for nome in cat.RACAS:
        raca = Breed.objects.filter(name=nome).first()
        if raca is None:
            raca = Breed(name=nome)
            livestock_services.salvar_cadastro(raca, usuario=ctx.admin, criando=True)
        ctx.racas.append(raca)

    ctx.centros = {c.name: c for c in CostCenter.objects.filter(name__in=cat.CENTROS)}
    faltam = [n for n in cat.CENTROS if n not in ctx.centros]
    if faltam:
        raise CommandError(f"Centros de custo ausentes: {', '.join(faltam)}.")
    ctx.classes = {c.name: c for c in CostClass.objects.all()}
    ctx.condicoes = {c.name: c for c in PaymentCondition.objects.filter(is_active=True)}
    ctx.tributos = {t.name: t for t in TaxType.objects.filter(is_active=True)}
    ctx.carcass = {c.code: c for c in CarcassClass.objects.filter(is_active=True)}


# --------------------------------------------------------------------------
# Safras
# --------------------------------------------------------------------------


def preparar_safras(ctx):
    """Reaproveita a safra de mesmo nome da empresa; cria a que falta, sem
    mexer em `is_current` de nenhuma. Recusa sobreposição (o banco também)."""
    for nome, inicio, fim in SAFRAS:
        safra = Season.objects.filter(company=ctx.company, name=nome).first()
        if safra is None:
            choque = Season.objects.filter(
                company=ctx.company, start_date__lte=fim, end_date__gte=inicio
            ).first()
            if choque is not None:
                raise CommandError(
                    f"A safra {nome} ({inicio:%d/%m/%Y} a {fim:%d/%m/%Y}) se sobrepõe "
                    f"à safra {choque.name} ({choque.start_date:%d/%m/%Y} a "
                    f"{choque.end_date:%d/%m/%Y}) da empresa. Ajuste ou remova uma delas."
                )
            safra = Season(
                company=ctx.company,
                name=nome,
                start_date=inicio,
                end_date=fim,
                status=SeasonStatus.ABERTA,
                is_current=False,
            )
            org_services.salvar_cadastro(safra, usuario=ctx.admin, criando=True)
            ctx.safras_criadas.add(safra.pk)
        elif safra.status == SeasonStatus.ENCERRADA:
            raise CommandError(
                f"A safra {nome} já existe e está encerrada. Reabra-a ou use outra "
                "empresa: o seed não lança em safra encerrada."
            )
        ctx.safras.append(safra)

    # O período simulado precisa estar inteiro coberto, sem buraco entre safras.
    ordenadas = sorted(ctx.safras, key=lambda s: s.start_date)
    for anterior, seguinte in zip(ordenadas, ordenadas[1:], strict=False):
        if seguinte.start_date != anterior.end_date + datetime.timedelta(days=1):
            raise CommandError(
                f"Há um buraco entre as safras {anterior.name} e {seguinte.name}: "
                "o seed precisa de safras contínuas."
            )


# --------------------------------------------------------------------------
# Unidades, fazendas e pastos
# --------------------------------------------------------------------------


def criar_fazendas(ctx):
    unidades = {}
    for chave, (codigo, nome) in cat.UNIDADES.items():
        unidade = BusinessUnit(company=ctx.company, code=codigo, name=nome)
        org_services.salvar_cadastro(unidade, usuario=ctx.admin, criando=True)
        unidades[chave] = unidade

    for f in cat.FAZENDAS:
        fazenda = Farm(
            code=f.code,
            name=f.name,
            business_unit=unidades[f.unidade],
            city=f.city,
            state=f.state,
            total_area_ha=D(f.total_ha),
            pasture_area_ha=D(f.pasture_ha),
        )
        property_services.salvar_cadastro(fazenda, usuario=ctx.admin, criando=True)
        ctx.fazendas[f.code] = fazenda
        ctx.perfil[f.code] = f.perfil
        _criar_pastos(ctx, fazenda, f)


def _criar_pastos(ctx, fazenda, f):
    rnd = ctx.rnd
    n = max(4, min(14, f.pasture_ha // 300))
    # A área de pasto é toda repartida entre os piquetes, sem sobrar nem faltar.
    centesimos = inteiro_proporcional(
        f.pasture_ha * 100, [rnd.randint(7, 13) for _ in range(n)]
    )
    for i, c in enumerate(centesimos, start=1):
        area = D(c) / 100
        tipo = "SILAGEM" if i == 3 and f.perfil != cat.CONFINAMENTO else "PASTAGEM"
        pasto = Paddock(
            farm=fazenda,
            name=f"Piquete {i:02d}",
            type=tipo,
            area_ha=area,
            capacity_ua=(area * decimal_entre(rnd, "0.9", "1.4")).quantize(D("0.01")),
        )
        property_services.salvar_cadastro(pasto, usuario=ctx.admin, criando=True)
    extras = [
        ("Reserva legal e APP", "RESERVA_APP", D(f.total_ha - f.pasture_ha) * D("0.7")),
        ("Sede e benfeitorias", "BENFEITORIA", D(f.total_ha - f.pasture_ha) * D("0.3")),
    ]
    for nome, tipo, area in extras:
        if area <= 0:
            continue
        pasto = Paddock(
            farm=fazenda, name=nome, type=tipo, area_ha=area.quantize(D("0.01"))
        )
        property_services.salvar_cadastro(pasto, usuario=ctx.admin, criando=True)


# --------------------------------------------------------------------------
# Parceiros
# --------------------------------------------------------------------------


def _cpf(rnd) -> str:
    base = [rnd.randint(0, 9) for _ in range(9)]
    for tamanho in (9, 10):
        soma = sum(d * (tamanho + 1 - i) for i, d in enumerate(base[:tamanho]))
        base.append((soma * 10 % 11) % 10)
    s = "".join(map(str, base))
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


def _cnpj(rnd) -> str:
    n = "".join(str(rnd.randint(0, 9)) for _ in range(8))
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/0001-{rnd.randint(10, 99)}"


def _pessoa_juridica(nome: str) -> bool:
    return any(
        t in nome
        for t in (
            "Ltda",
            "S/A",
            "Cia.",
            "Frigor",
            "Marfrig",
            "Coperfrigu",
            "Transportes",
            "Boiadeiro",
            "Rodoboi",
            "Frota",
            "Receita",
            "Fundepec",
            "Agência",
            "Secretaria",
            "Grupo",
            "Agropecuária",
            "Pecuária",
            "Agro ",
            "Leilões",
            "Açougue",
            "Cavalcante",
            "Intermediação",
            "Compra de Gado",
        )
    )


def _criar_parceiro(ctx, nome, papeis, cidade, uf, *, com_conta=True):
    rnd = ctx.rnd
    juridica = _pessoa_juridica(nome)
    slug = "".join(c for c in nome.lower() if c.isalnum())[:18] or "parceiro"
    parceiro = Partner(
        name=nome,
        legal_name=nome if juridica else "",
        document=_cnpj(rnd) if juridica else _cpf(rnd),
        city=cidade,
        state=uf,
        phone=f"(63) 9{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}",
        email=f"contato@{slug}.exemplo.com.br",
        notes=cat.MARCADOR,
    )
    partner_services.salvar_parceiro(parceiro, papeis, usuario=ctx.admin, criando=True)
    if com_conta:
        codigo, banco = rnd.choice(cat.BANCOS)
        conta = BankAccount(
            partner=parceiro,
            bank_code=codigo,
            bank_name=banco,
            branch=f"{rnd.randint(1, 4999):04d}",
            account=f"{rnd.randint(10000, 99999)}-{rnd.randint(0, 9)}",
            account_type="CORRENTE",
            pix_key=parceiro.email if rnd.random() < 0.6 else "",
            is_default=True,
        )
        partner_services.salvar_conta_bancaria(conta, usuario=ctx.admin, criando=True)
    return parceiro


def criar_parceiros(ctx):
    for nome, papeis, cidade, uf, peso in cat.PRODUTORES:
        ctx.parceiros["produtor"].append(_criar_parceiro(ctx, nome, papeis, cidade, uf))
        ctx.pesos.setdefault("produtor", []).append(peso)
    for nome, papeis, cidade, uf, peso in cat.COMPRADORES:
        grupo = "frigorifico" if "FRIGORIFICO" in papeis else "comprador"
        ctx.parceiros[grupo].append(_criar_parceiro(ctx, nome, papeis, cidade, uf))
        ctx.pesos.setdefault(grupo, []).append(peso)
    for nome, papeis, cidade, uf in cat.TRANSPORTADORAS:
        ctx.parceiros["transportador"].append(
            _criar_parceiro(ctx, nome, papeis, cidade, uf)
        )
    for nome, papeis, cidade, uf in cat.COMISSIONADOS:
        ctx.parceiros["comissionado"].append(
            _criar_parceiro(ctx, nome, papeis, cidade, uf)
        )
    for nome, papeis, cidade, uf in cat.FAVORECIDOS_DE_TRIBUTO:
        ctx.parceiros["favorecido"].append(
            _criar_parceiro(ctx, nome, papeis, cidade, uf)
        )


def criar_regras_de_comissao(ctx):
    """Cada comissionado com uma regra vigente desde o início do período, em
    formatos diferentes (percentual, por cabeça). Os compromissos digitam o
    valor — a regra só pré-preenche quando o campo fica vazio."""
    inicio = ctx.inicio
    formatos = [
        ("PERCENTUAL", "BRUTO", D("1.5")),
        ("POR_CABECA", "BRUTO", D("22")),
        ("PERCENTUAL", "LIQUIDO", D("1.2")),
    ]
    for comissionado, (tipo, base, valor) in zip(
        ctx.parceiros["comissionado"], formatos, strict=False
    ):
        regra = CommissionRule(
            commissioned=comissionado,
            category=None,
            type=tipo,
            base=base,
            value=valor,
            valid_from=inicio,
            notes=cat.MARCADOR,
        )
        comercial.salvar_cadastro(regra, usuario=ctx.admin, criando=True)


# --------------------------------------------------------------------------
# Estruturas e máquinas
# --------------------------------------------------------------------------


def criar_estruturas_e_maquinas(ctx):
    rnd = ctx.rnd
    for f in cat.FAZENDAS:
        fazenda = ctx.fazendas[f.code]
        for tipo, nome, area, cocho, bebedouros, animais in cat.ESTRUTURAS_POR_PERFIL[
            f.perfil
        ]:
            estrutura = FarmStructure(
                farm=fazenda,
                kind=tipo,
                name=nome,
                area_m2=D(area) if area else None,
                trough_m=D(cocho) if cocho else None,
                waterers=bebedouros,
                animals=animais,
            )
            ctx.tentar(
                "estrutura",
                infra_services.salvar_cadastro,
                estrutura,
                usuario=ctx.admin,
                criando=True,
            )
        for nome, tipo, valor in cat.MAQUINAS_POR_PERFIL[f.perfil]:
            maquina = Machine(
                farm=fazenda,
                name=nome,
                kind=tipo,
                new_value=D(valor) * decimal_entre(rnd, "0.95", "1.1"),
            )
            if ctx.tentar(
                "maquina",
                infra_services.salvar_cadastro,
                maquina,
                usuario=ctx.admin,
                criando=True,
            ):
                ctx.maquinas.append(maquina)


# --------------------------------------------------------------------------
# Acessos (opcional)
# --------------------------------------------------------------------------


def vincular_acessos(ctx) -> int:
    """Dá acesso às fazendas do seed aos usuários de papel restrito que já
    existem. ADMIN e GESTOR já veem tudo; o sistema não grava linha para eles."""
    restritos = User.objects.filter(
        is_active=True,
        deleted_at__isnull=True,
        is_superuser=False,
        role__in=[Role.ESCRITORIO, Role.CAMPO, Role.FINANCEIRO, Role.CONSULTA],
    )
    criados = 0
    for usuario in restritos:
        for fazenda in ctx.fazendas.values():
            _, criou = UserFarmAccess.objects.get_or_create(
                user=usuario,
                farm=fazenda,
                defaults={"can_write": usuario.role != Role.CONSULTA},
            )
            criados += int(criou)
    return criados


def sortear(ctx, grupo: str):
    """Um parceiro do grupo, com os pesos do catálogo (concentração real:
    o vendedor principal responde por boa parte das compras)."""
    return ctx.rnd.choices(ctx.parceiros[grupo], weights=ctx.pesos[grupo])[0]
