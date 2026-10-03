"""Escrita. Toda operação que altera estado passa por aqui.

`confirmar_venda()` é a mesma disciplina da compra: transacional, travada,
com a saída no rebanho gerada automaticamente. A verificação de saldo
acontece **dentro** da transação, com a posição travada — fora dela, duas
vendas simultâneas passariam as duas pela validação e derrubariam o saldo
abaixo de zero. Ver docs/regras-negocio/04-venda-e-abate.md.
"""

import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import reversible
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.formatting import numero_br
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.serialization import diff_fields, snapshot
from apps.finance import services as finance
from apps.herd.models import MovementType
from apps.herd.permissions import (
    pode_lancar_em_safra_encerrada,
    tem_acesso_de_escrita_a_fazenda,
)
from apps.herd.services import (
    registrar_movimento,
    saldo,
    saldo_travado,
    season_para_data,
)
from apps.livestock.models import Lot, LotStatus
from apps.organizations.models import Season, SeasonStatus
from apps.partners.models import PartnerRoleChoice
from apps.sales.carcass import alertas_de_rendimento, indicadores_da_venda
from apps.sales.models import Sale, SaleType
from apps.sales.permissions import pode_confirmar_venda, pode_lancar_venda

PAPEIS_DE_COMPRADOR = (PartnerRoleChoice.FRIGORIFICO, PartnerRoleChoice.COMPRADOR)

TIPO_DE_MOVIMENTO = {
    SaleType.ABATE: MovementType.ABATE,
    SaleType.VENDA: MovementType.VENDA,
}


# --------------------------------------------------------------------------
# Código e validação
# --------------------------------------------------------------------------


def gerar_codigo_venda(season: Season) -> str:
    """`VD-2025/26-0003` — sequência por safra. A safra é travada pelo
    chamador, senão duas vendas simultâneas calculariam a mesma sequência.
    Conta também as excluídas: um número nunca é reaproveitado."""
    inicio, _, fim = season.name.partition("/")
    rotulo = f"{inicio}/{fim[-2:]}" if fim else season.name
    prefixo = f"VD-{rotulo}-"
    existentes = Sale.objects.filter(code__startswith=prefixo).count()
    return f"{prefixo}{existentes + 1:04d}"


def _validar_dados(dados: dict, *, usuario) -> Season:
    """Validações de docs/regras-negocio/04#validações. Devolve a safra.

    A de saldo (item 2) não está aqui: ela só vale sob a trava da posição,
    dentro de `confirmar_venda`."""
    if dados["type"] not in SaleType.values:
        raise BusinessError("Informe se é abate ou venda de animal vivo.")
    if (dados["head_count"] or 0) <= 0:
        raise BusinessError("Informe quantas cabeças foram vendidas (mais de zero).")
    peso = Decimal(dados["total_weight_kg"] or 0)
    if peso <= 0:
        raise BusinessError("O peso vivo de saída deve ser maior que zero.")
    if Decimal(dados["total_value"] or 0) <= 0:
        raise BusinessError("O valor total deve ser maior que zero.")

    carcaca = dados.get("carcass_weight_kg")
    if carcaca is not None:
        if dados["type"] == SaleType.VENDA:
            raise BusinessError(
                "Venda de animal vivo não tem peso de carcaça. Se os animais "
                "foram abatidos, registre como abate."
            )
        if Decimal(carcaca) <= 0:
            raise BusinessError(
                "O peso de carcaça, quando informado, deve ser maior que zero."
            )
        if Decimal(carcaca) >= peso:
            raise BusinessError(
                f"A carcaça ({carcaca} kg) não pode pesar tanto quanto o animal "
                f"vivo ({peso} kg): o rendimento passaria de 100%. Confira os dois pesos."
            )

    if dados["date"] > timezone.localdate():
        raise BusinessError("Venda com data futura não é permitida.")

    farm = dados["farm"]
    if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")
    if not dados["category"].is_active:
        raise BusinessError(f"A categoria {dados['category']} está inativa.")

    buyer = dados.get("buyer")
    if buyer is None:
        raise BusinessError("Informe o comprador ou o frigorífico.")
    if not buyer.roles.filter(role__in=PAPEIS_DE_COMPRADOR).exists():
        raise BusinessError(
            f"{buyer} não tem o papel de Comprador nem de Frigorífico. "
            "Acrescente o papel no cadastro do parceiro."
        )

    lot = dados["lot"]
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
    "type",
    "buyer",
    "farm",
    "lot",
    "category",
    "head_count",
    "total_weight_kg",
    "carcass_weight_kg",
    "total_value",
    "sale_form",
    "payment_days",
    "partnership",
    "notes",
)


def _completar(venda: Sale, dados: dict) -> dict:
    """Dados novos sobre os atuais: o que não veio, fica."""
    return {
        campo: dados.get(campo, getattr(venda, campo)) for campo in CAMPOS_EDITAVEIS
    }


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


@transaction.atomic
def criar_venda(*, usuario, **dados) -> Sale:
    """Cria o rascunho. Rascunho não afeta nada: nem rebanho, nem lote."""
    if not pode_lancar_venda(usuario):
        raise BusinessError("Você não tem permissão para lançar vendas.")
    dados = {campo: dados.get(campo) for campo in CAMPOS_EDITAVEIS} | {
        "sale_form": dados.get("sale_form") or "PASTO",
        "partnership": dados.get("partnership") or "",
        "notes": dados.get("notes") or "",
    }
    season = _validar_dados(dados, usuario=usuario)
    season = Season.objects.select_for_update().get(pk=season.pk)

    venda = Sale(**dados, season=season, created_by=usuario)
    venda.code = gerar_codigo_venda(season)
    venda.save()
    registrar_auditoria(
        action=AuditAction.CREATE, entity=venda, after=snapshot(venda), actor=usuario
    )
    return venda


@transaction.atomic
def editar_rascunho(venda: Sale, dados: dict, *, usuario) -> Sale:
    """Rascunho se edita sem motivo (06#permissões): ainda não afeta nada."""
    venda = Sale.objects.select_for_update().get(pk=venda.pk)
    if venda.status != Status.RASCUNHO:
        raise BusinessError(
            "Esta venda já foi confirmada. Use a correção, que exige motivo."
        )
    if not pode_lancar_venda(usuario):
        raise BusinessError("Você não tem permissão para editar vendas.")

    novos = _completar(venda, dados)
    venda.season = _validar_dados(novos, usuario=usuario)
    antes = snapshot(venda)
    for campo, valor in novos.items():
        setattr(venda, campo, valor)
    venda.updated_by = usuario
    venda.version += 1
    venda.save()
    depois = snapshot(venda)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=venda,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        actor=usuario,
    )
    return venda


def _verificar_saldo(venda: Sale) -> None:
    """Saldo suficiente? Verificado **dentro** da transação, com a posição
    travada (`select_for_update` em todas as linhas dela). O razão repete a
    checagem ao gravar a linha negativa, mas esta dá a mensagem da venda
    antes de qualquer movimento ser criado."""
    disponivel = saldo_travado(farm=venda.farm, lot=venda.lot, category=venda.category)
    if disponivel < venda.head_count:
        raise BusinessError(
            f"Saldo insuficiente: há {disponivel} cabeças de {venda.category} "
            f"no lote {venda.lot.code} em {venda.farm}, foram informadas "
            f"{venda.head_count}."
        )


@transaction.atomic
def confirmar_venda(venda: Sale, *, usuario, gerar_titulos: bool = True) -> Sale:
    """RASCUNHO → CONFIRMADA, tudo ou nada.

    Confirmar também gera o título a receber (F4-02), idempotente por
    `(venda, componente)`. A importação do histórico passa
    `gerar_titulos=False` — o que a planilha traz já foi recebido fora.

    O `select_for_update` na própria venda impede duplicidade por clique
    duplo; o da posição do rebanho impede que duas vendas distintas da mesma
    posição passem juntas. Uma é confirmada, a outra recebe o saldo real."""
    venda = Sale.objects.select_for_update().get(pk=venda.pk)
    if venda.status != Status.RASCUNHO:
        raise BusinessError("Esta venda já foi confirmada.")
    if not pode_confirmar_venda(usuario):
        raise BusinessError("Você não tem permissão para confirmar vendas.")

    # Revalida: o rascunho pode ter envelhecido (safra encerrada depois,
    # fazenda sem acesso, categoria desativada).
    venda.season = _validar_dados(_completar(venda, {}), usuario=usuario)
    if not venda.movements.filter(status=Status.CONFIRMADA).exists():
        _verificar_saldo(venda)
    venda = reversible.confirmar(venda, usuario=usuario)
    if gerar_titulos:
        finance.gerar_titulos_da_venda(venda, usuario=usuario)
    return venda


@transaction.atomic
def editar_venda(venda: Sale, dados: dict, *, usuario, motivo: str) -> Sale:
    """Venda confirmada: desfaz os efeitos da versão anterior e aplica os
    da nova, na mesma transação, com motivo obrigatório."""
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar venda confirmada.")
    # Estado atual do banco, sob trava: a instância recebida pode estar velha
    # (safra encerrada ou venda excluída por outra pessoa desde que foi lida).
    venda = Sale.objects.select_for_update().select_related("season").get(pk=venda.pk)
    if venda.status == Status.RASCUNHO:
        return editar_rascunho(venda, dados, usuario=usuario)
    # O bloqueio vem antes da validação: é ele que explica o caminho ("peça a
    # um administrador para reabrir a safra"), em vez de recusar o lançamento.
    if venda.bloqueios():
        raise BlockingDependencyError(f"Não é possível editar: {venda.bloqueios()[0]}")

    novos = _completar(venda, dados)
    novos["season"] = _validar_dados(novos, usuario=usuario)
    return reversible.editar(venda, novos, usuario=usuario, motivo=motivo)


@transaction.atomic
def excluir_venda(venda: Sale, *, usuario, motivo: str, cascata: bool = False) -> Sale:
    if venda.status == Status.RASCUNHO:
        if not pode_lancar_venda(usuario):
            raise BusinessError("Você não tem permissão para excluir esta venda.")
    elif not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir venda confirmada.")
    return reversible.excluir(venda, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar_venda(venda: Sale, *, usuario) -> Sale:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar venda.")
    if venda.bloqueios():
        raise BlockingDependencyError(
            f"Não é possível restaurar: {venda.bloqueios()[0]}"
        )
    return reversible.restaurar(venda, usuario=usuario)


# --------------------------------------------------------------------------
# Efeitos: saída no rebanho e encerramento do lote
# --------------------------------------------------------------------------


def aplicar_efeitos_da_venda(venda: Sale, *, usuario) -> None:
    movimento = venda.movements.order_by("id").first()
    if movimento is None:
        registrar_movimento(
            type=TIPO_DE_MOVIMENTO[venda.type],
            date=venda.date,
            quantity=venda.head_count,
            total_weight_kg=venda.total_weight_kg,
            usuario=usuario,
            origin_farm=venda.farm,
            origin_lot=venda.lot,
            origin_category=venda.category,
            partner=venda.buyer,
            notes=f"Venda {venda.code}",
            season=venda.season,
            origin_sale=venda,
        )
    elif movimento.status == Status.EXCLUIDA:
        # Edição ou restauração: o documento do movimento acompanha a venda
        # e os efeitos dele são reaplicados — com o saldo checado sob trava.
        movimento.type = TIPO_DE_MOVIMENTO[venda.type]
        movimento.date = venda.date
        movimento.season = venda.season
        movimento.quantity = venda.head_count
        movimento.total_weight_kg = venda.total_weight_kg
        movimento.origin_farm = venda.farm
        movimento.origin_lot = venda.lot
        movimento.origin_category = venda.category
        movimento.partner = venda.buyer
        movimento.save()
        reversible.restaurar(movimento, usuario=usuario)
    # Movimento já confirmado e vinculado à venda (saída que veio da aba da
    # fazenda na importação): os efeitos já existem, nada a gerar.

    _encerrar_lote_se_zerou(venda, usuario=usuario)
    # Corrigir ou restaurar a venda: o título que ela já tinha acompanha.
    finance.sincronizar_da_venda(venda, usuario=usuario)


def desfazer_efeitos_da_venda(venda: Sale, *, usuario) -> None:
    """Devolve as cabeças ao lote — com linhas de compensação **na data
    original** — e reabre o lote, se a venda o tinha encerrado."""
    # Mesma raiz da exclusão que nos chamou: movimento e lote saem na
    # auditoria como parte do MESMO ato (06#auditoria, `cascade_root`).
    raiz = getattr(venda, "cascade_root", None) or uuid.uuid4()
    venda.cascade_root_usado = True
    motivo = f"Desfeito junto com a venda {venda.code}"

    finance.desfazer_titulos_da_origem(venda, usuario=usuario, raiz=raiz)
    for movimento in venda.movements.filter(status=Status.CONFIRMADA):
        reversible.excluir(
            movimento, usuario=usuario, motivo=motivo, cascata=True, raiz=raiz
        )
    _reabrir_lote_se_voltou(venda, usuario=usuario, motivo=motivo, raiz=raiz)


def _encerrar_lote_se_zerou(venda: Sale, *, usuario) -> None:
    """Com o lote a saldo zero, encerra (`ENCERRADO`, `exit_date`). O
    resultado dele deixa de mudar porque o período termina na `exit_date` —
    nada é gravado (regra 6)."""
    lote = Lot.objects.select_for_update().get(pk=venda.lot_id)
    if lote.status != LotStatus.ABERTO or saldo(lot=lote)["head_count"] != 0:
        return
    antes = snapshot(lote)
    lote.status = LotStatus.ENCERRADO
    lote.exit_date = venda.date
    lote.save(update_fields=["status", "exit_date"])
    depois = snapshot(lote)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=lote,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=f"Lote encerrado: a venda {venda.code} zerou o saldo.",
        actor=usuario,
    )


def _reabrir_lote_se_voltou(venda: Sale, *, usuario, motivo, raiz) -> None:
    lote = Lot.objects.select_for_update().get(pk=venda.lot_id)
    if lote.status != LotStatus.ENCERRADO or saldo(lot=lote)["head_count"] <= 0:
        return
    antes = snapshot(lote)
    lote.status = LotStatus.ABERTO
    lote.exit_date = None
    lote.save(update_fields=["status", "exit_date"])
    depois = snapshot(lote)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=lote,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=f"{motivo}: o lote {lote.code} voltou a ter saldo e foi reaberto.",
        cascade_root=raiz,
        actor=usuario,
    )


# --------------------------------------------------------------------------
# Vínculo com uma saída que já está no razão (importação)
# --------------------------------------------------------------------------


@transaction.atomic
def vincular_a_saida_existente(venda: Sale, movimento, *, usuario) -> None:
    """A aba da fazenda já registrou o abate como saída no rebanho; a aba
    `VENDAS` registra o mesmo abate como venda. Debitar de novo contaria as
    cabeças duas vezes. Em vez disso a venda **adota** a saída: ela passa a
    ser o documento de origem, sem mexer em data nem peso do movimento — a
    diferença entre os dois é aviso (pendência #12), não correção silenciosa.

    Só vale para venda em rascunho e movimento confirmado, de saída, que
    ninguém reivindicou, com a mesma posição e a mesma quantidade."""
    from apps.herd.models import HerdMovement

    movimento = HerdMovement.objects.select_for_update().get(pk=movimento.pk)
    if venda.status != Status.RASCUNHO:
        raise BusinessError("Só dá para vincular uma saída a uma venda em rascunho.")
    if movimento.status != Status.CONFIRMADA:
        raise BusinessError(f"A movimentação {movimento.code} não está confirmada.")
    if movimento.type != TIPO_DE_MOVIMENTO[venda.type]:
        raise BusinessError(
            f"A movimentação {movimento.code} é {movimento.get_type_display().lower()}, "
            f"e a venda é {venda.get_type_display().lower()}."
        )
    if movimento.origin_sale_id or movimento.origin_purchase_id:
        raise BusinessError(
            f"A movimentação {movimento.code} já pertence a outro documento."
        )
    if (
        movimento.quantity != venda.head_count
        or movimento.origin_category_id != venda.category_id
        or movimento.origin_farm_id != venda.farm_id
        or movimento.origin_lot_id != venda.lot_id
    ):
        raise BusinessError(
            f"A movimentação {movimento.code} não é a mesma saída desta venda: "
            "fazenda, lote, categoria e quantidade precisam coincidir."
        )

    antes = snapshot(movimento)
    movimento.origin_sale = venda
    movimento.save(update_fields=["origin_sale"])
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=movimento,
        before=antes,
        after=snapshot(movimento),
        changed_fields=["origin_sale"],
        reason=f"Vinculada à venda {venda.code}: é a mesma saída.",
        actor=usuario,
    )


# --------------------------------------------------------------------------
# Alertas — o que conferir, nunca o que recusar
# --------------------------------------------------------------------------


def alertas_da_venda(venda: Sale) -> list[str]:
    """Texto para a tela da venda. Nenhum deles bloqueia: valor atípico deve
    ser conferido por gente, não recusado pela máquina."""
    alertas = []
    if venda.sem_carcaca:
        alertas.append(
            "Abate sem peso de carcaça: o rendimento e o valor por @ aparecem "
            "como — até o romaneio do frigorífico ser informado."
        )
    alertas.extend(alertas_de_rendimento(indicadores_da_venda(venda).rendimento))

    movimento = venda.movements.filter(status=Status.CONFIRMADA).first()
    if (
        movimento is not None
        and movimento.total_weight_kg is not None
        and movimento.total_weight_kg != venda.total_weight_kg
    ):
        alertas.append(
            f"O peso vivo da venda ({numero_br(venda.total_weight_kg, 0)} kg) difere "
            f"do peso da saída no rebanho, {movimento.code} "
            f"({numero_br(movimento.total_weight_kg, 0)} kg). "
            "Confirme com o produtor qual vale — pendência #12."
        )
    return alertas
