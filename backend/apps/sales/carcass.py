"""`CarcassService` — os derivados de uma venda, calculados, nunca gravados.

Fonte única: tela da venda, relatório, dashboard e a conferência da
importação chamam este módulo. Se dois lugares mostrassem rendimento
diferente para a mesma venda, o usuário pararia de confiar nos dois
(regra 6 do CLAUDE.md).

Os seis números do abate de ago/2025 — 84 cabeças, 43.540 kg vivo,
22.350,40 kg de carcaça, R$ 401.502,68 — são o teste que trava o serviço:
518,33 · 266,08 · 51,33% · 1.490,03@ · 4.779,79 · 269,46
(docs/regras-negocio/04#derivados--carcassservice).

Tudo `Decimal`, sem arredondar no meio da conta (ADR 0005): quem apresenta
arredonda. Divisor zero ou dado ausente devolve `None`, que a tela mostra
como "—" (regra 3) — nunca `0`.
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.core.money import kg_to_arroba, safe_div

#: Rendimento de carcaça esperado, em %. Fora dela é **alerta**, não bloqueio:
#: valor atípico deve ser conferido por gente, não recusado pela máquina
#: (docs/regras-negocio/04#validações, item 4).
FAIXA_DE_RENDIMENTO = (Decimal("40"), Decimal("65"))

CEM = Decimal("100")


@dataclass(frozen=True)
class IndicadoresDaVenda:
    """Todo campo pode ser `None`: falta de dado é estado normal."""

    peso_medio_vivo: Decimal | None  # kg por cabeça
    carcaca_media: Decimal | None  # kg por cabeça
    rendimento: Decimal | None  # % (51,33 — não 0,5133)
    arrobas_carcaca: Decimal | None  # @ de carcaça: é a que vale no preço
    valor_por_cabeca: Decimal | None
    valor_por_arroba: Decimal | None  # R$ por @ de carcaça
    # Venda de animal vivo, sem carcaça: o preço é por cabeça ou por kg vivo.
    valor_por_kg_vivo: Decimal | None
    arrobas_vivas: Decimal | None  # só para conferência (05#conversões)


def calcular_carcaca(
    *, head_count, total_weight_kg, total_value, carcass_weight_kg=None
) -> IndicadoresDaVenda:
    cabecas = head_count or 0
    vivo = Decimal(total_weight_kg) if total_weight_kg else None
    carcaca = Decimal(carcass_weight_kg) if carcass_weight_kg else None
    valor = Decimal(total_value) if total_value else None

    arrobas_carcaca = kg_to_arroba(carcaca) if carcaca else None
    rendimento = safe_div(carcaca, vivo)
    return IndicadoresDaVenda(
        peso_medio_vivo=safe_div(vivo, cabecas),
        carcaca_media=safe_div(carcaca, cabecas),
        rendimento=rendimento * CEM if rendimento is not None else None,
        arrobas_carcaca=arrobas_carcaca,
        valor_por_cabeca=safe_div(valor, cabecas),
        valor_por_arroba=safe_div(valor, arrobas_carcaca),
        valor_por_kg_vivo=safe_div(valor, vivo),
        arrobas_vivas=kg_to_arroba(vivo) if vivo else None,
    )


def indicadores_da_venda(venda) -> IndicadoresDaVenda:
    return calcular_carcaca(
        head_count=venda.head_count,
        total_weight_kg=venda.total_weight_kg,
        total_value=venda.total_value,
        carcass_weight_kg=venda.carcass_weight_kg,
    )


def rendimento_fora_da_faixa(rendimento: Decimal | None) -> bool:
    """`None` não é "fora da faixa": sem carcaça não há o que alertar —
    isso é outra pendência (abate sem romaneio)."""
    if rendimento is None:
        return False
    minimo, maximo = FAIXA_DE_RENDIMENTO
    return not (minimo <= rendimento <= maximo)


def alertas_de_rendimento(rendimento: Decimal | None) -> list[str]:
    if not rendimento_fora_da_faixa(rendimento):
        return []
    minimo, maximo = FAIXA_DE_RENDIMENTO
    return [
        f"Rendimento de {rendimento:.2f}% fora da faixa usual "
        f"({minimo:.0f}% a {maximo:.0f}%). Confira o peso vivo e o peso de "
        "carcaça — pode ser digitação, ou pode ser real."
    ]


@dataclass(frozen=True)
class AgregadoDeVendas:
    """Várias vendas somadas. Os indicadores de carcaça só consideram as
    vendas **que têm carcaça** — somar o peso vivo de todas e dividir pela
    carcaça de algumas mentiria no rendimento. `sem_carcaca` diz quantas
    ficaram de fora."""

    vendas: int
    cabecas: int
    peso_vivo_kg: Decimal
    valor_total: Decimal
    com_carcaca: int
    sem_carcaca: int
    indicadores: IndicadoresDaVenda


def agregar(vendas) -> AgregadoDeVendas:
    vendas = list(vendas)
    cabecas = sum(v.head_count for v in vendas)
    peso_vivo = sum((v.total_weight_kg for v in vendas), Decimal("0"))
    valor = sum((v.total_value for v in vendas), Decimal("0"))
    com = [v for v in vendas if v.carcass_weight_kg]

    base = calcular_carcaca(
        head_count=cabecas, total_weight_kg=peso_vivo, total_value=valor
    )
    if com:
        sobre_carcaca = calcular_carcaca(
            head_count=sum(v.head_count for v in com),
            total_weight_kg=sum((v.total_weight_kg for v in com), Decimal("0")),
            total_value=sum((v.total_value for v in com), Decimal("0")),
            carcass_weight_kg=sum((v.carcass_weight_kg for v in com), Decimal("0")),
        )
        indicadores = IndicadoresDaVenda(
            peso_medio_vivo=base.peso_medio_vivo,
            carcaca_media=sobre_carcaca.carcaca_media,
            rendimento=sobre_carcaca.rendimento,
            arrobas_carcaca=sobre_carcaca.arrobas_carcaca,
            valor_por_cabeca=base.valor_por_cabeca,
            valor_por_arroba=sobre_carcaca.valor_por_arroba,
            valor_por_kg_vivo=base.valor_por_kg_vivo,
            arrobas_vivas=base.arrobas_vivas,
        )
    else:
        indicadores = base
    return AgregadoDeVendas(
        vendas=len(vendas),
        cabecas=cabecas,
        peso_vivo_kg=peso_vivo,
        valor_total=valor,
        com_carcaca=len(com),
        sem_carcaca=len(vendas) - len(com),
        indicadores=indicadores,
    )
