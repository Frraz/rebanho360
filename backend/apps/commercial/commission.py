"""`CommissionService` — escolher e calcular a comissão. **Isolado de propósito.**

A pendência #4 (a comissão incide sobre o valor bruto ou o líquido?) está
aberta. Tudo que depende da resposta mora neste arquivo, para ajustá-la sem
tocar em nada mais (docs/regras-negocio/99-pendencias.md#4).

Não grava nada: devolve o valor, e quem chama decide onde ele vai. O que
fica gravado na operação é o **snapshot da regra** (`procurement.Commission`),
nunca o resultado deste cálculo — o valor é derivado (regra 6).
"""

import datetime
from decimal import Decimal

from django.db.models import Q

from apps.commercial.models import CommissionBase, CommissionRule, CommissionType
from apps.core.money import quantize_money


def escolher_regra(
    *, comissionado, categoria, data: datetime.date
) -> CommissionRule | None:
    """A regra **mais específica** vigente na data.

    Específica = tem comissionado (peso 2) e/ou categoria (peso 1). Entre
    regras igualmente específicas, vence a de vigência mais recente. Regra
    inativa nunca é escolhida.
    """
    regras = CommissionRule.objects.filter(is_active=True, valid_from__lte=data).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=data)
    )
    regras = regras.filter(Q(commissioned__isnull=True) | Q(commissioned=comissionado))
    regras = regras.filter(Q(category__isnull=True) | Q(category=categoria))
    if comissionado is None:
        # Sem comissionado na operação, só vale regra "para qualquer comprador".
        regras = regras.filter(commissioned__isnull=True)

    def especificidade(regra: CommissionRule) -> int:
        return (2 if regra.commissioned_id else 0) + (1 if regra.category_id else 0)

    return max(
        regras,
        key=lambda r: (especificidade(r), r.valid_from, r.pk),
        default=None,
    )


def calcular_comissao(
    *,
    tipo: str,
    base: str,
    valor: Decimal,
    valor_bruto: Decimal | None,
    deducoes: Decimal | None,
    cabecas: int | None,
) -> Decimal | None:
    """Valor da comissão em reais, ou `None` quando falta dado.

    - `PERCENTUAL` sobre o **bruto** (valor dos animais) ou sobre o **líquido**
      (bruto menos frete e tributos, `deducoes`; nunca negativo).
    - `POR_CABECA`: cabeças × valor.

    Arredonda **uma vez, no fim** (ADR 0005). Sem a base, devolve `None` — a
    tela mostra "—" e não "R$ 0,00".
    """
    valor = Decimal(valor)
    if tipo == CommissionType.POR_CABECA:
        if not cabecas:
            return None
        return quantize_money(Decimal(cabecas) * valor)

    if tipo != CommissionType.PERCENTUAL or valor_bruto is None:
        return None
    base_de_calculo = Decimal(valor_bruto)
    if base == CommissionBase.LIQUIDO:
        base_de_calculo = max(base_de_calculo - Decimal(deducoes or 0), Decimal("0"))
    return quantize_money(base_de_calculo * valor / Decimal("100"))
