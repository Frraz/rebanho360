"""Escrita. Toda operação que altera estado passa por aqui.

`confirmar_compra()` é onde o "registrar uma vez, reaproveitar" acontece:
em uma transação, sob `select_for_update`, cria (ou usa) o lote, dá entrada
no rebanho e gera um custo para cada valor preenchido. Na planilha isso é
digitado duas vezes. Ver docs/regras-negocio/03-compra-de-gado.md.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.commercial.payment import aplicar_condicao
from apps.core import reversible
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.money import kg_to_arroba, safe_div
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.serialization import diff_fields, snapshot
from apps.costs.models import CostEntry
from apps.costs.services import (
    centro_de_custo_por_nome,
    classe_de_custo_por_nome,
    registrar_custo,
)
from apps.finance import services as finance
from apps.herd.models import HerdMovement, MovementType, Weighing
from apps.herd.permissions import (
    pode_lancar_em_safra_encerrada,
    tem_acesso_de_escrita_a_fazenda,
)
from apps.herd.services import registrar_movimento, season_para_data
from apps.livestock.models import Lot, LotStatus
from apps.livestock.services import criar_lote
from apps.organizations.models import Season, SeasonStatus
from apps.partners.models import PartnerRoleChoice
from apps.purchases.models import Purchase
from apps.purchases.permissions import pode_confirmar_compra, pode_lancar_compra

#: Valor acessório da compra → centro de custo onde ele é lançado
#: (docs/regras-negocio/03#custos-gerados). A ordem é a ordem dos lançamentos.
CUSTOS_GERADOS = (
    ("animal_value", "DESPESA GADO", "animais"),
    ("freight_value", "FRETE", "frete"),
    ("commission_value", "COMISSÃO", "comissão"),
    ("tax_value", "IMPOSTO E TAXAS", "impostos"),
)

PAPEIS_DE_VENDEDOR = (PartnerRoleChoice.FORNECEDOR, PartnerRoleChoice.PRODUTOR)


# --------------------------------------------------------------------------
# PurchaseCostService — derivados, nunca gravados (regra 6)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CustoDaCompra:
    """Tudo `None` quando falta o dado: a tela mostra "—", nunca `0,00`."""

    custo_aquisicao: Decimal
    media_por_cabeca: (
        Decimal | None
    )  # só os animais ÷ cabeças (a `MÉDIA/CAB` da planilha)
    custo_por_cabeca: Decimal | None  # custo de aquisição ÷ cabeças
    peso_medio_kg: Decimal | None
    custo_por_arroba: Decimal | None
    custo_por_kg: Decimal | None


def calcular_custo_da_compra(
    *,
    head_count,
    animal_value,
    freight_value=0,
    commission_value=0,
    tax_value=0,
    total_weight_kg=None,
) -> CustoDaCompra:
    """`animais + frete + comissão + impostos`; custo/@ e custo/kg
    devolvem `None` sem peso. Sem arredondar no meio da conta (ADR 0005)."""
    animais = Decimal(animal_value or 0)
    custo = (
        animais
        + Decimal(freight_value or 0)
        + Decimal(commission_value or 0)
        + Decimal(tax_value or 0)
    )
    cabecas = head_count or 0
    peso = Decimal(total_weight_kg) if total_weight_kg else None
    return CustoDaCompra(
        custo_aquisicao=custo,
        media_por_cabeca=safe_div(animais, cabecas),
        custo_por_cabeca=safe_div(custo, cabecas),
        peso_medio_kg=safe_div(peso, cabecas),
        custo_por_arroba=safe_div(custo, kg_to_arroba(peso)) if peso else None,
        custo_por_kg=safe_div(custo, peso),
    )


def custo_da_compra(compra: Purchase) -> CustoDaCompra:
    return calcular_custo_da_compra(
        head_count=compra.head_count,
        animal_value=compra.animal_value,
        freight_value=compra.freight_value,
        commission_value=compra.commission_value,
        tax_value=compra.tax_value,
        total_weight_kg=compra.total_weight_kg,
    )


# --------------------------------------------------------------------------
# Código e validação
# --------------------------------------------------------------------------


def gerar_codigo_compra(season: Season) -> str:
    """`CP-2025/26-0001` — sequência por safra. A safra é travada pelo
    chamador, senão duas compras simultâneas calculariam a mesma sequência."""
    inicio, _, fim = season.name.partition("/")
    rotulo = f"{inicio}/{fim[-2:]}" if fim else season.name
    prefixo = f"CP-{rotulo}-"
    existentes = Purchase.objects.filter(code__startswith=prefixo).count()
    return f"{prefixo}{existentes + 1:04d}"


def _validar_dados(dados: dict, *, usuario) -> Season:
    """Validações de docs/regras-negocio/03#validações. Devolve a safra."""
    if (dados["head_count"] or 0) <= 0:
        raise BusinessError("Informe quantas cabeças foram compradas (mais de zero).")
    if Decimal(dados["animal_value"] or 0) <= 0:
        raise BusinessError("O valor dos animais deve ser maior que zero.")
    for campo, rotulo in (
        ("freight_value", "frete"),
        ("commission_value", "comissão"),
        ("tax_value", "impostos"),
    ):
        if Decimal(dados.get(campo) or 0) < 0:
            raise BusinessError(f"O valor de {rotulo} não pode ser negativo.")
    peso = dados.get("total_weight_kg")
    if peso is not None and Decimal(peso) <= 0:
        raise BusinessError("O peso total, quando informado, deve ser maior que zero.")
    rendimento = dados.get("entry_yield_percent")
    if rendimento is not None and not Decimal("1") <= Decimal(rendimento) <= Decimal(
        "100"
    ):
        raise BusinessError("O rendimento estimado de entrada fica entre 1% e 100%.")
    if dados["date"] > timezone.localdate():
        raise BusinessError("Compra com data futura não é permitida.")

    farm = dados["destination_farm"]
    if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")
    if not dados["category"].is_active:
        raise BusinessError(f"A categoria {dados['category']} está inativa.")

    seller = dados.get("seller")
    if (
        seller is not None
        and not seller.roles.filter(role__in=PAPEIS_DE_VENDEDOR).exists()
    ):
        raise BusinessError(
            f"{seller} não tem o papel de Fornecedor nem de Produtor. "
            "Acrescente o papel no cadastro do parceiro."
        )

    lot = dados.get("lot")
    if lot is not None:
        if lot.farm_id != farm.pk:
            raise BusinessError(
                f"O lote {lot.code} é da fazenda {lot.farm}, não de {farm}."
            )
        if lot.status == LotStatus.EXCLUIDO:
            raise BusinessError(f"O lote {lot.code} foi excluído.")

    season = season_para_data(dados["date"])
    if season is None:
        raise BusinessError(
            "Não há safra cadastrada que cubra esta data. Cadastre a safra antes."
        )
    if season.status == SeasonStatus.ENCERRADA and not pode_lancar_em_safra_encerrada(
        usuario
    ):
        raise BusinessError(
            f"A safra {season.name} está encerrada. Só o administrador pode "
            "lançar nela — reabra a safra antes, ou lance na safra corrente."
        )
    return season


CAMPOS_EDITAVEIS = (
    "date",
    "seller",
    "destination_farm",
    "category",
    "head_count",
    "total_weight_kg",
    "animal_value",
    "freight_value",
    "commission_value",
    "tax_value",
    "lot",
    "payment_days",
    "payment_condition",
    "entry_yield_percent",
    "partnership",
    "notes",
)


def _completar(compra: Purchase, dados: dict) -> dict:
    """Dados novos sobre os atuais: o que não veio, fica."""
    return aplicar_condicao(
        {campo: dados.get(campo, getattr(compra, campo)) for campo in CAMPOS_EDITAVEIS},
        atual=compra.payment_condition,
    )


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


@transaction.atomic
def criar_compra(*, usuario, **dados) -> Purchase:
    """Cria o rascunho. Rascunho não afeta nada: nem rebanho, nem custo."""
    if not pode_lancar_compra(usuario):
        raise BusinessError("Você não tem permissão para lançar compras.")
    # `codigo` só vem do ciclo de compra (número único da operação, #32).
    codigo = dados.get("codigo")
    dados = {campo: dados.get(campo) for campo in CAMPOS_EDITAVEIS} | {
        "freight_value": dados.get("freight_value") or 0,
        "commission_value": dados.get("commission_value") or 0,
        "tax_value": dados.get("tax_value") or 0,
        "partnership": dados.get("partnership") or "",
        "notes": dados.get("notes") or "",
    }
    dados = aplicar_condicao(dados)
    season = _validar_dados(dados, usuario=usuario)
    season = Season.objects.select_for_update().get(pk=season.pk)

    compra = Purchase(**dados, season=season, created_by=usuario)
    compra.code = codigo or gerar_codigo_compra(season)
    compra.save()
    registrar_auditoria(
        action=AuditAction.CREATE, entity=compra, after=snapshot(compra), actor=usuario
    )
    return compra


@transaction.atomic
def editar_rascunho(compra: Purchase, dados: dict, *, usuario) -> Purchase:
    """Rascunho se edita sem motivo (06#permissões): ainda não afeta nada."""
    compra = Purchase.objects.select_for_update().get(pk=compra.pk)
    if compra.status != Status.RASCUNHO:
        raise BusinessError(
            "Esta compra já foi confirmada. Use a correção, que exige motivo."
        )
    if not pode_lancar_compra(usuario):
        raise BusinessError("Você não tem permissão para editar compras.")

    novos = _completar(compra, dados)
    compra.season = _validar_dados(novos, usuario=usuario)
    antes = snapshot(compra)
    for campo, valor in novos.items():
        setattr(compra, campo, valor)
    compra.updated_by = usuario
    compra.version += 1
    compra.save()
    depois = snapshot(compra)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=compra,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        actor=usuario,
    )
    return compra


@transaction.atomic
def confirmar_compra(
    compra: Purchase, *, usuario, gerar_titulos: bool = True
) -> Purchase:
    """RASCUNHO → CONFIRMADA, tudo ou nada.

    Confirmar também gera os títulos a pagar (F4-02), idempotente por
    `(compra, componente)`. A importação do histórico passa
    `gerar_titulos=False`: o que a planilha traz já foi pago fora do sistema,
    e títulos de 2025 apareceriam todos como vencidos.

    O `select_for_update` é o que impede duplicidade por clique duplo ou
    por duas abas do navegador — cenário real quando a conexão da fazenda
    está lenta: o segundo clique espera o primeiro terminar e então vê a
    compra já confirmada.
    """
    compra = Purchase.objects.select_for_update().get(pk=compra.pk)
    if compra.status != Status.RASCUNHO:
        raise BusinessError("Esta compra já foi confirmada.")
    if not pode_confirmar_compra(usuario):
        raise BusinessError("Você não tem permissão para confirmar compras.")

    # Revalida: o rascunho pode ter envelhecido (safra encerrada depois,
    # fazenda sem acesso, categoria desativada).
    compra.season = _validar_dados(_completar(compra, {}), usuario=usuario)
    compra = reversible.confirmar(compra, usuario=usuario)
    if gerar_titulos:
        finance.gerar_titulos_da_compra(compra, usuario=usuario)
    return compra


def _recusar_se_do_ciclo(compra: Purchase, acao: str) -> None:
    """A compra que nasceu de um acerto (Fase 5) se corrige pelo acerto — o
    valor dela é o que o acerto apurou. Como o movimento gerado por compra, que
    se corrige pelo documento de origem."""
    item = getattr(compra, "commitment_item", None)
    if item is not None:
        acerto = item.commitment.settlements.exclude(status=Status.EXCLUIDA).first()
        onde = (
            f"o acerto {acerto.code}"
            if acerto
            else f"o compromisso {item.commitment.code}"
        )
        raise BusinessError(
            f"A compra {compra.code} foi gerada por {onde} e não pode ser "
            f"{acao} direto. Corrija pelo acerto: reabra-o, ajuste e aprove de novo."
        )


@transaction.atomic
def editar_compra(compra: Purchase, dados: dict, *, usuario, motivo: str) -> Purchase:
    """Compra confirmada: desfaz os efeitos da versão anterior e aplica os
    da nova, na mesma transação, com motivo obrigatório."""
    _recusar_se_do_ciclo(compra, "editada")
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar compra confirmada.")
    if compra.status == Status.RASCUNHO:
        return editar_rascunho(compra, dados, usuario=usuario)

    novos = _completar(compra, dados)
    novos["season"] = _validar_dados(novos, usuario=usuario)
    return reversible.editar(compra, novos, usuario=usuario, motivo=motivo)


@transaction.atomic
def excluir_compra(
    compra: Purchase, *, usuario, motivo: str, cascata: bool = False
) -> Purchase:
    _recusar_se_do_ciclo(compra, "excluída")
    if compra.status == Status.RASCUNHO:
        if not pode_lancar_compra(usuario):
            raise BusinessError("Você não tem permissão para excluir esta compra.")
    elif not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir compra confirmada.")
    return reversible.excluir(compra, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar_compra(compra: Purchase, *, usuario) -> Purchase:
    _recusar_se_do_ciclo(compra, "restaurada")
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar compra.")
    if compra.bloqueios():
        raise BlockingDependencyError(
            f"Não é possível restaurar: {compra.bloqueios()[0]}"
        )
    return reversible.restaurar(compra, usuario=usuario)


# --------------------------------------------------------------------------
# Efeitos: lote, entrada no rebanho, custos
# --------------------------------------------------------------------------


def _lote_da_compra(compra: Purchase, *, usuario) -> Lot:
    """Lote escolhido pelo usuário, ou o criado por esta compra."""
    lote = compra.lot
    if lote is None:
        lote = Lot(
            farm=compra.destination_farm,
            season=compra.season,
            entry_date=compra.date,
            origin_partner=compra.seller,
            origin_purchase=compra,
            notes=f"Criado pela compra {compra.code}.",
        )
        criar_lote(lote, usuario=usuario)
        compra.lot = lote
        compra.save(update_fields=["lot"])
        return lote

    if lote.origin_purchase_id == compra.pk:
        # Lote criado por esta compra: acompanha as correções dela.
        lote.farm = compra.destination_farm
        lote.entry_date = compra.date
        lote.origin_partner = compra.seller
        lote.season = compra.season
        if lote.status == LotStatus.EXCLUIDO:
            lote.status = LotStatus.ABERTO
        lote.save()
    return lote


def aplicar_efeitos_da_compra(compra: Purchase, *, usuario) -> None:
    lote = _lote_da_compra(compra, usuario=usuario)

    movimento = compra.movements.order_by("id").first()
    if movimento is None:
        registrar_movimento(
            type=MovementType.COMPRA,
            date=compra.date,
            quantity=compra.head_count,
            total_weight_kg=compra.total_weight_kg,
            usuario=usuario,
            destination_farm=compra.destination_farm,
            destination_lot=lote,
            destination_category=compra.category,
            partner=compra.seller,
            notes=f"Compra {compra.code}",
            season=compra.season,
            origin_purchase=compra,
        )
    else:
        # Edição ou restauração: o documento do movimento acompanha a compra
        # e os efeitos dele são reaplicados.
        movimento.date = compra.date
        movimento.season = compra.season
        movimento.quantity = compra.head_count
        movimento.total_weight_kg = compra.total_weight_kg
        movimento.destination_farm = compra.destination_farm
        movimento.destination_lot = lote
        movimento.destination_category = compra.category
        movimento.partner = compra.seller
        movimento.save()
        reversible.restaurar(movimento, usuario=usuario)

    _gerar_custos(compra, lote, usuario=usuario)
    # Corrigir ou restaurar a compra: os títulos que ela já tinha acompanham.
    finance.sincronizar_da_compra(compra, usuario=usuario)


def _gerar_custos(compra: Purchase, lote: Lot, *, usuario) -> None:
    """Um lançamento por valor preenchido, todos com `lot` (custo direto) e
    `source_purchase` (só se corrigem pela compra)."""
    classe = classe_de_custo_por_nome("CUSTEIO")
    for campo, nome_do_centro, rotulo in CUSTOS_GERADOS:
        valor = getattr(compra, campo)
        if valor and valor > 0:
            registrar_custo(
                date=compra.date,
                farm=compra.destination_farm,
                cost_center=centro_de_custo_por_nome(nome_do_centro),
                cost_class=classe,
                amount=valor,
                description=f"Compra {compra.code} · {rotulo}",
                usuario=usuario,
                lot=lote,
                season=compra.season,
                source_purchase=compra,
            )


def _lote_sem_mais_nada(lote: Lot, compra: Purchase) -> bool:
    """O lote criado pela compra sai junto se nada mais depende dele."""
    confirmada = Status.CONFIRMADA
    return not (
        HerdMovement.objects.filter(status=confirmada).filter(origin_lot=lote).exists()
        or HerdMovement.objects.filter(status=confirmada, destination_lot=lote).exists()
        or Weighing.objects.filter(status=confirmada, lot=lote).exists()
        or CostEntry.objects.filter(status=confirmada, lot=lote).exists()
        or Purchase.objects.filter(status=confirmada, lot=lote)
        .exclude(pk=compra.pk)
        .exists()
    )


def desfazer_efeitos_da_compra(compra: Purchase, *, usuario) -> None:
    """Desfaz movimento, custos gerados e o lote (se criado por ela e vazio).
    Cada item gera o próprio evento de auditoria."""
    # Mesma raiz da exclusão que nos chamou: movimento, custos e lote saem
    # na auditoria como parte do MESMO ato (06#auditoria, `cascade_root`).
    raiz = getattr(compra, "cascade_root", None) or uuid.uuid4()
    compra.cascade_root_usado = True
    motivo = f"Desfeito junto com a compra {compra.code}"

    finance.desfazer_titulos_da_origem(compra, usuario=usuario, raiz=raiz)
    for movimento in compra.movements.filter(status=Status.CONFIRMADA):
        try:
            reversible.excluir(
                movimento, usuario=usuario, motivo=motivo, cascata=True, raiz=raiz
            )
        except BlockingDependencyError:
            raise
        except BusinessError as exc:
            raise BlockingDependencyError(
                f"não dá para desfazer a entrada de animais da compra {compra.code}: "
                f"{exc} Os animais desta compra já saíram do lote. Desfaça antes as "
                "saídas (mortes, vendas, transferências) ou confirme a exclusão em "
                "cascata."
            ) from exc

    for custo in compra.cost_entries.filter(status=Status.CONFIRMADA):
        reversible.excluir(
            custo, usuario=usuario, motivo=motivo, cascata=True, raiz=raiz
        )

    lote = compra.lot
    if (
        lote is not None
        and lote.origin_purchase_id == compra.pk
        and lote.status != LotStatus.EXCLUIDO
        and _lote_sem_mais_nada(lote, compra)
    ):
        antes = snapshot(lote)
        lote.status = LotStatus.EXCLUIDO
        lote.save(update_fields=["status"])
        registrar_auditoria(
            action=AuditAction.DELETE,
            entity=lote,
            before=antes,
            after=snapshot(lote),
            reason=motivo,
            cascade_root=raiz,
            actor=usuario,
        )
