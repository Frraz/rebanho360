"""`WeightGainService` — GMD e @ produzida de pesagens sucessivas do lote.

Regras (docs/regras-negocio/05#rebanho):

- GMD = (peso médio final − peso médio inicial) ÷ dias, de pesagens do mesmo
  lote. **Sem duas pesagens em datas diferentes, GMD é `None` — não se estima
  peso de entrada.** O motivo vai junto, para a tela dizer "—" *e por quê*.
- @ produzida = (carcaça de saída − carcaça de entrada) ÷ 15. A carcaça de
  entrada nunca é medida: é estimada por `peso vivo de entrada × rendimento`.
  Quando o rendimento de entrada é estimado, o resultado vem **marcado como
  estimativa** — e sem rendimento informado não há @ produzida (pendência
  #15: ninguém disse qual rendimento usar, então o sistema não escolhe).

Tudo `Decimal`, sem arredondar no meio da conta (ADR 0005).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.money import kg_to_arroba, safe_div
from apps.core.reversible import Status
from apps.herd.models import Weighing, WeighingReason

CEM = Decimal("100")


@dataclass(frozen=True)
class PontoDePeso:
    """Um peso médio datado: uma pesagem, ou o peso informado na compra."""

    date: object
    peso_medio_kg: Decimal
    cabecas: int
    origem: str
    e_entrada: bool  # peso de entrada do lote (pesagem de compra ou peso da compra)


@dataclass(frozen=True)
class Trecho:
    """GMD entre duas pesagens sucessivas."""

    de: PontoDePeso
    ate: PontoDePeso
    dias: int
    gmd: Decimal

    @property
    def ganho_por_cabeca_kg(self) -> Decimal:
        return self.ate.peso_medio_kg - self.de.peso_medio_kg


@dataclass(frozen=True)
class DesempenhoDoLote:
    pontos: tuple = ()
    trechos: tuple = ()
    primeiro: PontoDePeso | None = None
    ultimo: PontoDePeso | None = None
    dias: int | None = None
    ganho_por_cabeca_kg: Decimal | None = None
    gmd: Decimal | None = None
    # O GMD parte de um peso de entrada? Se não, cobre só o período pesado.
    gmd_desde_a_entrada: bool = False
    arrobas_produzidas: Decimal | None = None
    arrobas_estimadas: bool = False
    cabecas_abatidas: int | None = None
    rendimento_entrada: Decimal | None = None  # %, só quando informado
    # Por que cada "—" é "—". Nunca vazio quando algo é `None`.
    motivos: list[str] = field(default_factory=list)


def _pontos(pesagens, compras) -> list[PontoDePeso]:
    """Os pontos de peso a partir de pesagens e compras **já carregadas**
    (as pesagens em ordem de data). A regra é uma só, para um lote ou para
    trezentos."""
    pontos = [
        PontoDePeso(
            date=p.date,
            peso_medio_kg=p.average_weight_kg,
            cabecas=p.head_count,
            origem=f"Pesagem de {p.get_reason_display().lower()}",
            e_entrada=p.reason == WeighingReason.COMPRA,
        )
        for p in pesagens
    ]
    if not any(p.e_entrada for p in pontos):
        if compras and all(c.total_weight_kg for c in compras):
            cabecas = sum(c.head_count for c in compras)
            peso = sum((c.total_weight_kg for c in compras), Decimal("0"))
            pontos.append(
                PontoDePeso(
                    date=compras[0].date,
                    peso_medio_kg=peso / cabecas,
                    cabecas=cabecas,
                    origem="Peso informado na compra",
                    e_entrada=True,
                )
            )
            pontos.sort(key=lambda p: p.date)
    return pontos


def pontos_de_peso(lot) -> list[PontoDePeso]:
    """Pesagens confirmadas do lote em ordem de data. Sem pesagem de entrada,
    o peso informado na compra serve — mas só se **todas** as compras do lote
    têm peso: parte delas não representa a entrada."""
    return pontos_de_peso_dos_lotes([lot])[lot.pk]


def _carregar(lots, *, com_abates=True):
    """Pesagens, compras e abates confirmados de vários lotes: três consultas,
    qualquer que seja o número de lotes. `{lot_id: [...]}` para cada um."""
    from apps.purchases.models import Purchase
    from apps.sales.models import Sale, SaleType

    ids = [lt.pk for lt in lots]
    pesagens, compras, abates = defaultdict(list), defaultdict(list), defaultdict(list)
    for p in Weighing.objects.filter(lot_id__in=ids, status=Status.CONFIRMADA).order_by(
        "date", "id"
    ):
        pesagens[p.lot_id].append(p)
    for c in Purchase.objects.filter(lot_id__in=ids, status=Status.CONFIRMADA).order_by(
        "date", "id"
    ):
        compras[c.lot_id].append(c)
    if com_abates:
        for a in Sale.objects.filter(
            lot_id__in=ids, status=Status.CONFIRMADA, type=SaleType.ABATE
        ):
            abates[a.lot_id].append(a)
    return pesagens, compras, abates


def pontos_de_peso_dos_lotes(lots) -> dict:
    """`{lot_id: [PontoDePeso]}` de vários lotes, com duas consultas."""
    pesagens, compras, _ = _carregar(lots, com_abates=False)
    return {lt.pk: _pontos(pesagens[lt.pk], compras[lt.pk]) for lt in lots}


def _trechos(pontos) -> list[Trecho]:
    trechos = []
    for anterior, atual in zip(pontos, pontos[1:], strict=False):
        dias = (atual.date - anterior.date).days
        if dias > 0:
            trechos.append(
                Trecho(
                    de=anterior,
                    ate=atual,
                    dias=dias,
                    gmd=(atual.peso_medio_kg - anterior.peso_medio_kg) / dias,
                )
            )
    return trechos


def gmd_do_ultimo_trecho(lot) -> Decimal | None:
    trechos = _trechos(pontos_de_peso(lot))
    return trechos[-1].gmd if trechos else None


def _rendimento_das_compras(compras) -> Decimal | None:
    informadas = [c for c in compras if c.entry_yield_percent is not None]
    cabecas = sum(c.head_count for c in informadas)
    if not cabecas:
        return None
    return sum(
        (c.entry_yield_percent * c.head_count for c in informadas), Decimal("0")
    ) / (cabecas)


def rendimento_de_entrada_do_lote(lot) -> Decimal | None:
    """O rendimento estimado de entrada que o usuário **informou nas compras** do
    lote (cliente, 2026-10-03, #15a): média ponderada pelas cabeças. `None` se
    nenhuma compra o informou — o sistema não escolhe um valor."""
    from apps.purchases.models import Purchase

    return _rendimento_das_compras(
        Purchase.objects.filter(lot=lot, status=Status.CONFIRMADA)
    )


def _montar_desempenho(
    lot, pesagens, compras, abates, rendimento_entrada
) -> DesempenhoDoLote:
    pontos = _pontos(pesagens, compras)
    motivos: list[str] = []
    if rendimento_entrada is None:
        rendimento_entrada = _rendimento_das_compras(compras)

    gmd = dias = ganho = primeiro = ultimo = None
    desde_a_entrada = False
    if not pontos:
        motivos.append("GMD indisponível: sem pesagem registrada.")
    elif len(pontos) == 1:
        motivos.append(
            f"GMD indisponível: só há uma pesagem ({pontos[0].date:%d/%m/%Y}); "
            "são precisas duas, em datas diferentes."
        )
    else:
        primeiro, ultimo = pontos[0], pontos[-1]
        dias = (ultimo.date - primeiro.date).days
        if dias <= 0:
            motivos.append("GMD indisponível: as pesagens são do mesmo dia.")
            primeiro = ultimo = dias = None
        else:
            ganho = ultimo.peso_medio_kg - primeiro.peso_medio_kg
            gmd = safe_div(ganho, dias)
            desde_a_entrada = primeiro.e_entrada
            if not desde_a_entrada:
                motivos.append(
                    f"Sem pesagem de entrada: o GMD cobre só o período pesado "
                    f"({primeiro.date:%d/%m/%Y} a {ultimo.date:%d/%m/%Y}), não o "
                    "lote inteiro. O peso de entrada não é estimado."
                )

    arrobas, estimada, abatidas, rendimento = _arrobas_produzidas(
        abates, pontos, rendimento_entrada, motivos
    )
    return DesempenhoDoLote(
        pontos=tuple(pontos),
        trechos=tuple(_trechos(pontos)),
        primeiro=primeiro,
        ultimo=ultimo,
        dias=dias,
        ganho_por_cabeca_kg=ganho,
        gmd=gmd,
        gmd_desde_a_entrada=desde_a_entrada,
        arrobas_produzidas=arrobas,
        arrobas_estimadas=estimada,
        cabecas_abatidas=abatidas,
        rendimento_entrada=rendimento,
        motivos=motivos,
    )


def desempenho_dos_lotes(lots, *, rendimento_entrada=None) -> dict:
    """`{lot_id: DesempenhoDoLote}` de vários lotes com três consultas no total
    (pesagens, compras, abates), em vez de três ou quatro **por lote**."""
    lots = list(lots)
    pesagens, compras, abates = _carregar(lots)
    return {
        lt.pk: _montar_desempenho(
            lt, pesagens[lt.pk], compras[lt.pk], abates[lt.pk], rendimento_entrada
        )
        for lt in lots
    }


def desempenho_do_lote(lot, *, rendimento_entrada=None) -> DesempenhoDoLote:
    """GMD e @ produzida do lote. `rendimento_entrada` em % (48 = 48%): o que
    vem na chamada vale; sem ele, o informado nas compras do lote; sem nenhum,
    a @ produzida é `None`, com o motivo. Um lote é o caso de `desempenho_dos_lotes`
    com uma só posição — a conta é a mesma na tela do lote e no dashboard."""
    return desempenho_dos_lotes([lot], rendimento_entrada=rendimento_entrada)[lot.pk]


def _arrobas_produzidas(abates, pontos, rendimento_entrada, motivos):
    """`(carcaça de saída − carcaça de entrada) ÷ 15`, sobre os animais
    abatidos. Devolve `(@, estimada?, cabeças abatidas, rendimento usado)`."""
    sem_dado = (None, False, None, None)
    if not abates:
        motivos.append(
            "@ produzida indisponível: o lote não tem abate confirmado "
            "(falta o peso de carcaça de saída)."
        )
        return sem_dado
    sem_carcaca = [a for a in abates if a.carcass_weight_kg is None]
    if sem_carcaca:
        motivos.append(
            f"@ produzida indisponível: {len(sem_carcaca)} abate(s) sem peso de "
            "carcaça — informe o romaneio do frigorífico."
        )
        return sem_dado

    entrada = next((p for p in pontos if p.e_entrada), None)
    if entrada is None:
        motivos.append(
            "@ produzida indisponível: sem pesagem de entrada, não há de onde "
            "tirar a carcaça de entrada (o peso de entrada não é estimado)."
        )
        return sem_dado
    if rendimento_entrada is None:
        motivos.append(
            "@ produzida indisponível: não há carcaça medida na entrada. Informe "
            "um rendimento de entrada estimado para ver a conta — ela aparece "
            "marcada como estimativa."
        )
        return sem_dado

    rendimento = Decimal(rendimento_entrada)
    if not (0 < rendimento < CEM):
        motivos.append(
            "@ produzida indisponível: o rendimento de entrada deve estar "
            "entre 0% e 100%."
        )
        return sem_dado

    abatidas = sum(a.head_count for a in abates)
    carcaca_saida = sum((a.carcass_weight_kg for a in abates), Decimal("0"))
    carcaca_entrada = entrada.peso_medio_kg * abatidas * rendimento / CEM
    return (
        kg_to_arroba(carcaca_saida - carcaca_entrada),
        True,
        abatidas,
        rendimento,
    )
