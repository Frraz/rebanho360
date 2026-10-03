"""Romaneio valorizado: classificação × faixa → cabeças, peso, @, valor.

Média @, valor bruto, valor/kg e valor líquido **não são campos** (regra 6):
saem daqui, para a tela, o acerto e o relatório mostrarem o mesmo número.

    arrobas  = peso de carcaça ÷ 15
    bruto    = arrobas × preço da @
    líquido  = bruto × (1 − desconto%)

Arredonda uma vez, no fim, em cada linha — a linha é o que está no papel — e o
total é a soma das linhas (ADR 0005).
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from apps.commercial.models import CarcassClass
from apps.core.exceptions import BusinessError
from apps.core.money import kg_to_arroba, quantize_money, safe_div
from apps.core.reversible import Status
from apps.procurement.commitments import exigir_acerto_aberto
from apps.procurement.lines import sincronizar_linhas
from apps.procurement.models import (
    Commitment,
    CommitmentItem,
    GradingLine,
    PriceBasis,
)
from apps.procurement.permissions import pode_lancar_no_ciclo

CAMPOS_DA_LINHA = (
    "carcass_class",
    "band",
    "head_count",
    "carcass_weight_kg",
    "price_per_arroba",
    "discount_percent",
)


@dataclass(frozen=True)
class LinhaValorizada:
    linha: GradingLine
    arrobas: Decimal
    media_arrobas: Decimal | None
    valor_bruto: Decimal
    valor_por_kg: Decimal
    desconto: Decimal
    liquido: Decimal


@dataclass(frozen=True)
class Romaneio:
    linhas: list[LinhaValorizada]
    cabecas: int
    peso_kg: Decimal
    arrobas: Decimal
    media_arrobas: Decimal | None
    valor_bruto: Decimal
    desconto: Decimal
    liquido: Decimal
    #: R$ por @ efetivamente pago (líquido ÷ @); `None` sem carcaça.
    preco_medio_por_arroba: Decimal | None


def valorizar_linha(linha: GradingLine) -> LinhaValorizada:
    arrobas = kg_to_arroba(linha.carcass_weight_kg)
    bruto_exato = arrobas * linha.price_per_arroba
    liquido_exato = bruto_exato * (Decimal("100") - linha.discount_percent) / 100
    bruto = quantize_money(bruto_exato)
    liquido = quantize_money(liquido_exato)
    return LinhaValorizada(
        linha=linha,
        arrobas=arrobas,
        media_arrobas=safe_div(arrobas, linha.head_count),
        valor_bruto=bruto,
        valor_por_kg=linha.price_per_arroba / 15,
        desconto=bruto - liquido,
        liquido=liquido,
    )


def romaneio_do_item(item: CommitmentItem) -> Romaneio:
    linhas = [valorizar_linha(g) for g in item.gradings.select_related("carcass_class")]
    return romaneio_de(linhas)


def romaneio_de(linhas: list[LinhaValorizada]) -> Romaneio:
    cabecas = sum(v.linha.head_count for v in linhas)
    peso = sum((v.linha.carcass_weight_kg for v in linhas), Decimal("0"))
    arrobas = sum((v.arrobas for v in linhas), Decimal("0"))
    liquido = sum((v.liquido for v in linhas), Decimal("0"))
    return Romaneio(
        linhas=linhas,
        cabecas=cabecas,
        peso_kg=peso,
        arrobas=arrobas,
        media_arrobas=safe_div(arrobas, cabecas),
        valor_bruto=sum((v.valor_bruto for v in linhas), Decimal("0")),
        desconto=sum((v.desconto for v in linhas), Decimal("0")),
        liquido=liquido,
        preco_medio_por_arroba=safe_div(liquido, arrobas),
    )


def faixa_sugerida(classe: CarcassClass) -> int | None:
    """Só **sugere** (pendência #20): quem escolhe a faixa é o usuário."""
    return classe.default_band


# --------------------------------------------------------------------------
# Escrita
# --------------------------------------------------------------------------


def _preparar(entrada: dict, item: CommitmentItem, posicao: int) -> dict:
    entrada = dict(entrada)
    rotulo = f"Linha {posicao} do romaneio"
    classe = entrada.get("carcass_class")
    if classe is None:
        raise BusinessError(f"{rotulo}: escolha a classificação.")
    if not classe.is_active and entrada.get("id") is None:
        raise BusinessError(f"{rotulo}: a classificação {classe} está inativa.")
    faixa = entrada.get("band")
    if faixa is None or not 1 <= faixa <= 5:
        raise BusinessError(f"{rotulo}: a faixa vai de 1 a 5.")
    if not (entrada.get("head_count") or 0) > 0:
        raise BusinessError(f"{rotulo}: informe as cabeças (mais de zero).")
    peso = entrada.get("carcass_weight_kg")
    if peso is None or Decimal(peso) <= 0:
        raise BusinessError(f"{rotulo}: informe o peso de carcaça (maior que zero).")

    preco = entrada.get("price_per_arroba")
    if preco is None:
        # Copia do contrato — e fica editável (pendência #20).
        preco = item.preco_da_faixa(faixa)
        if preco is None:
            raise BusinessError(
                f"{rotulo}: o contrato não tem preço para a Faixa {faixa}. "
                "Informe o preço da @."
            )
        entrada["price_per_arroba"] = preco
    if Decimal(preco) <= 0:
        raise BusinessError(f"{rotulo}: o preço da @ deve ser maior que zero.")

    desconto = entrada.get("discount_percent")
    entrada["discount_percent"] = Decimal(desconto or 0)
    if not Decimal("0") <= entrada["discount_percent"] <= Decimal("100"):
        raise BusinessError(f"{rotulo}: o desconto vai de 0% a 100%.")
    return entrada


@transaction.atomic
def registrar_romaneio(
    item: CommitmentItem, linhas: list[dict], *, usuario, motivo: str = ""
):
    """Grava o romaneio do item **como um todo**: o que veio e não existia é
    criado, o que mudou é corrigido, o que sumiu é retirado. Corrigir ou
    retirar linha existente exige motivo."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para lançar o romaneio.")
    compromisso = Commitment.objects.select_for_update().get(pk=item.commitment_id)
    if compromisso.status != Status.CONFIRMADA:
        raise BusinessError("O romaneio se lança depois da aprovação do compromisso.")
    exigir_acerto_aberto(compromisso, "corrigir o romaneio")
    if item.price_basis != PriceBasis.ARROBA:
        raise BusinessError(
            f"O item {item.number} é precificado por cabeça: não tem romaneio por faixa."
        )

    entradas = [_preparar(e, item, i) for i, e in enumerate(linhas, start=1)]

    def _criar(entrada: dict) -> GradingLine:
        linha = GradingLine(item=item)
        for campo in CAMPOS_DA_LINHA:
            setattr(linha, campo, entrada[campo])
        linha.save()
        return linha

    return sincronizar_linhas(
        existentes=list(item.gradings.all()),
        entradas=entradas,
        campos=CAMPOS_DA_LINHA,
        criar=_criar,
        usuario=usuario,
        motivo=motivo,
    )
