"""Escrita. Toda operação que altera estado passa por aqui.

`registrar_movimento()` é o ponto de entrada único: tipo simples gera 1
linha, tipo de deslocamento gera 2 — sempre na mesma transação, sempre
com a posição travada antes de decidir se uma saída é possível. Ver
docs/regras-negocio/01-rebanho-movimentacoes.md.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core import reversible
from apps.core.exceptions import BusinessError
from apps.herd.models import (
    ENTRY_TYPES,
    EXIT_TYPES,
    TWO_LINE_TYPES,
    TYPES_COM_MOTIVO_OBRIGATORIO,
    HerdLedgerEntry,
    HerdMovement,
    MovementType,
    Weighing,
)
from apps.herd.permissions import (
    pode_lancar_ajuste_inventario,
    pode_lancar_em_safra_encerrada,
    tem_acesso_de_escrita_a_fazenda,
)
from apps.organizations.models import Season, SeasonStatus


def gerar_codigo_movimento(season: Season) -> str:
    prefixo = f"MV-{season.name}-"
    existentes = HerdMovement.objects.filter(code__startswith=prefixo).count()
    return f"{prefixo}{existentes + 1:06d}"


def season_para_data(data):
    return (
        Season.objects.filter(start_date__lte=data, end_date__gte=data)
        .order_by("-start_date")
        .first()
    )


def saldo(*, farm=None, lot=None, category=None, season=None, until=None) -> dict:
    """`HerdBalanceService` — saldo por fazenda, lote, categoria e data.
    `SUM` sobre o razão, nunca um campo gravado (ADR 0002)."""
    qs = HerdLedgerEntry.objects.all()
    if farm is not None:
        qs = qs.filter(farm=farm)
    if lot is not None:
        qs = qs.filter(lot=lot)
    if category is not None:
        qs = qs.filter(category=category)
    if season is not None:
        qs = qs.filter(season=season)
    if until is not None:
        qs = qs.filter(date__lte=until)

    head_count = 0
    weight_kg = Decimal("0")
    for quantity, weight in qs.values_list("quantity", "weight_kg"):
        head_count += quantity
        if weight is not None:
            weight_kg += weight
    return {"head_count": head_count, "weight_kg": weight_kg}


def saldo_travado(*, farm, lot, category) -> int:
    """Trava (`select_for_update`) todas as linhas da posição antes de
    somar — é o que impede duas saídas concorrentes de passarem juntas
    pela validação (F1-09). Só vale dentro de uma transação."""
    linhas = list(
        HerdLedgerEntry.objects.select_for_update().filter(
            farm=farm, lot=lot, category=category
        )
    )
    return sum(linha.quantity for linha in linhas)


_saldo_travado = saldo_travado


def _criar_linha(
    movimento, *, farm, lot, category, quantity, weight_kg, date, reverses=None
):
    if quantity < 0:
        saldo_atual = _saldo_travado(farm=farm, lot=lot, category=category)
        if saldo_atual + quantity < 0:
            raise BusinessError(
                f"Saldo insuficiente: há {saldo_atual} cabeças de {category} "
                f"no lote {lot.code} em {farm}, foram informadas {abs(quantity)}."
            )
    return HerdLedgerEntry.objects.create(
        movement=movimento,
        date=date,
        farm=farm,
        lot=lot,
        category=category,
        quantity=quantity,
        weight_kg=weight_kg,
        season=movimento.season,
        reverses_entry=reverses,
    )


def gerar_linhas_do_razao(movimento: HerdMovement) -> None:
    """Partidas dobradas: tipo de deslocamento gera as 2 linhas na mesma
    transação, negativa na origem e positiva no destino, soma zero."""
    peso = movimento.total_weight_kg

    if movimento.type in TWO_LINE_TYPES:
        _criar_linha(
            movimento,
            farm=movimento.origin_farm,
            lot=movimento.origin_lot,
            category=movimento.origin_category,
            quantity=-movimento.quantity,
            weight_kg=-peso if peso is not None else None,
            date=movimento.date,
        )
        _criar_linha(
            movimento,
            farm=movimento.destination_farm,
            lot=movimento.destination_lot,
            category=movimento.destination_category,
            quantity=movimento.quantity,
            weight_kg=peso,
            date=movimento.date,
        )
    elif movimento.type in ENTRY_TYPES:
        _criar_linha(
            movimento,
            farm=movimento.destination_farm,
            lot=movimento.destination_lot,
            category=movimento.destination_category,
            quantity=movimento.quantity,
            weight_kg=peso,
            date=movimento.date,
        )
    elif movimento.type in EXIT_TYPES:
        _criar_linha(
            movimento,
            farm=movimento.origin_farm,
            lot=movimento.origin_lot,
            category=movimento.origin_category,
            quantity=-movimento.quantity,
            weight_kg=-peso if peso is not None else None,
            date=movimento.date,
        )
    elif movimento.type == MovementType.AJUSTE_INVENTARIO:
        # Sinal decidido por onde o usuário preencheu: destino = entrada,
        # origem = saída. Permissão restrita verificada em registrar_movimento.
        if movimento.destination_farm_id:
            _criar_linha(
                movimento,
                farm=movimento.destination_farm,
                lot=movimento.destination_lot,
                category=movimento.destination_category,
                quantity=movimento.quantity,
                weight_kg=peso,
                date=movimento.date,
            )
        else:
            _criar_linha(
                movimento,
                farm=movimento.origin_farm,
                lot=movimento.origin_lot,
                category=movimento.origin_category,
                quantity=-movimento.quantity,
                weight_kg=-peso if peso is not None else None,
                date=movimento.date,
            )
    else:  # pragma: no cover - defensivo, todo tipo real cai em um dos ramos acima
        raise BusinessError(f"Tipo de movimento desconhecido: {movimento.type}")


def desfazer_linhas_do_razao(movimento: HerdMovement) -> None:
    """O razão é append-only: desfazer escreve linhas de compensação,
    nunca apaga — e a compensação leva a data do fato original, nunca a
    data da correção (docs/regras-negocio/01#correção-de-erro)."""
    linhas_ativas = movimento.entries.filter(reversed_by__isnull=True)
    for linha in linhas_ativas:
        _criar_linha(
            movimento,
            farm=linha.farm,
            lot=linha.lot,
            category=linha.category,
            quantity=-linha.quantity,
            weight_kg=-linha.weight_kg if linha.weight_kg is not None else None,
            date=linha.date,
            reverses=linha,
        )


@transaction.atomic
def registrar_movimento(
    *,
    type: str,
    date,
    quantity: int,
    usuario,
    total_weight_kg=None,
    origin_farm=None,
    origin_lot=None,
    origin_category=None,
    destination_farm=None,
    destination_lot=None,
    destination_category=None,
    partner=None,
    reason: str = "",
    notes: str = "",
    season=None,
    origin_purchase=None,
    origin_sale=None,
) -> HerdMovement:
    if date > timezone.localdate():
        raise BusinessError("Movimento com data futura não é permitido.")

    if type in TYPES_COM_MOTIVO_OBRIGATORIO and not reason.strip():
        raise BusinessError(f"Motivo é obrigatório para {MovementType(type).label}.")

    if type == MovementType.AJUSTE_INVENTARIO and not pode_lancar_ajuste_inventario(
        usuario
    ):
        raise BusinessError(
            "Ajuste de inventário é permissão restrita a gestor e administrador."
        )

    for farm in (origin_farm, destination_farm):
        if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
            raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")

    season = season or season_para_data(date)
    if season is None:
        raise BusinessError(
            "Não há safra cadastrada que cubra esta data. Cadastre a safra antes."
        )

    # Trava a safra para serializar a geração de código entre lançamentos
    # concorrentes — sem isso, duas inserções simultâneas podem calcular a
    # mesma sequência antes de qualquer uma comitar (visto em teste real).
    season = Season.objects.select_for_update().get(pk=season.pk)

    if season.status == SeasonStatus.ENCERRADA and not pode_lancar_em_safra_encerrada(
        usuario
    ):
        raise BusinessError(
            f"A safra {season.name} está encerrada. Só o administrador pode "
            "lançar nela — reabra a safra antes, ou lance na safra corrente."
        )

    movimento = HerdMovement(
        date=date,
        type=type,
        season=season,
        quantity=quantity,
        total_weight_kg=total_weight_kg,
        origin_farm=origin_farm,
        origin_lot=origin_lot,
        origin_category=origin_category,
        destination_farm=destination_farm,
        destination_lot=destination_lot,
        destination_category=destination_category,
        partner=partner,
        origin_purchase=origin_purchase,
        origin_sale=origin_sale,
        reason=reason,
        notes=notes,
        created_by=usuario,
    )
    movimento.code = gerar_codigo_movimento(season)
    movimento.save()

    return reversible.confirmar(movimento, usuario=usuario)


@transaction.atomic
def registrar_pesagem(
    *, date, farm, lot, reason, head_count, total_weight_kg, usuario
) -> Weighing:
    if date > timezone.localdate():
        raise BusinessError("Pesagem com data futura não é permitida.")
    if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")

    pesagem = Weighing(
        date=date,
        farm=farm,
        lot=lot,
        reason=reason,
        head_count=head_count,
        total_weight_kg=total_weight_kg,
        created_by=usuario,
    )
    pesagem.save()
    return reversible.confirmar(pesagem, usuario=usuario)


def calcular_gmd(lot) -> Decimal | None:
    """GMD do trecho mais recente do lote (entre as duas últimas pesagens).
    A conta é do `WeightGainService` (`apps.herd.weight_gain`): `None`
    quando faltam duas pesagens em datas diferentes — falta de dado é
    estado normal, não defeito."""
    from apps.herd.weight_gain import gmd_do_ultimo_trecho

    return gmd_do_ultimo_trecho(lot)
