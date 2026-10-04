"""Leitura. Consultas e agregações."""

from django.db.models import Q, Sum

from apps.core.reversible import Status
from apps.herd.models import (
    TWO_LINE_TYPES,
    HerdLedgerEntry,
    HerdMovement,
    MovementType,
)
from apps.livestock.models import AnimalCategory, Lot


def posicao_do_rebanho(*, user, farm=None, season=None, until=None):
    """Substitui o quadro-resumo das abas de fazenda — e o consolidado
    que a aba `GERAL` tentava ser. Nunca mostra número negativo, porque
    o saldo é sempre `SUM` do razão (ADR 0002), já protegido pela
    invariante de saldo não negativo (F1-09)."""
    qs = HerdLedgerEntry.objects.for_user(user)
    if farm is not None:
        qs = qs.filter(farm=farm)
    if season is not None:
        qs = qs.filter(season=season)
    if until is not None:
        qs = qs.filter(date__lte=until)

    # Uma consulta para todas as categorias (eram duas por categoria).
    somas = {
        linha["category_id"]: linha
        for linha in qs.values("category_id")
        .annotate(
            entradas=Sum("quantity", filter=Q(quantity__gt=0)),
            saidas=Sum("quantity", filter=Q(quantity__lt=0)),
        )
        .order_by()
    }
    linhas = []
    for categoria in AnimalCategory.objects.filter(is_active=True):
        soma = somas.get(categoria.pk, {})
        entradas = soma.get("entradas") or 0
        saidas = soma.get("saidas") or 0
        linhas.append(
            {
                "categoria": categoria,
                "entradas": entradas,
                "saidas": -saidas,
                "posicao": entradas + saidas,
            }
        )

    total = {
        "entradas": sum(linha["entradas"] for linha in linhas),
        "saidas": sum(linha["saidas"] for linha in linhas),
        "posicao": sum(linha["posicao"] for linha in linhas),
    }
    return linhas, total


def lotes_da_fazenda(user, farm_id):
    if not farm_id:
        return Lot.objects.none()
    return Lot.objects.for_user(user).filter(farm_id=farm_id, status="ABERTO")


def conciliar_transferencias(user=None):
    """F1-15 — o relatório que a planilha nunca teve: toda saída de
    deslocamento sem entrada correspondente. O trigger de banco
    (F1-06) já torna isso impossível pelos caminhos normais; este
    relatório é a segunda camada — útil sobretudo depois que a Fase 2
    importar histórico (pendência #2). Numa operação saudável, vem
    vazio: é isso que prova que o modelo está fechando."""
    base = listar_movimentos_para(user) if user is not None else HerdMovement.objects
    return (
        base.filter(type__in=TWO_LINE_TYPES)
        .annotate(soma=Sum("entries__quantity"))
        .exclude(soma=0)
        .exclude(soma__isnull=True)
        .order_by("date")
    )


def listar_movimentos_para(user):
    from apps.herd.models import HerdMovement

    if user.has_broad_access:
        return HerdMovement.objects.all()
    fazendas = user.accessible_farms()
    # Sem `distinct()`: o filtro não junta tabela de muitos, então não há linha
    # repetida — e o `DISTINCT` obrigava o banco a ordenar a tabela inteira.
    return HerdMovement.objects.filter(
        Q(origin_farm__in=fazendas) | Q(destination_farm__in=fazendas)
    )


#: Colunas do quadro de movimentação, na ordem da planilha "Movimentação
#: Fazenda": saldo anterior, entradas, saídas e posição final.
COLUNAS_DE_ENTRADA = ("compra", "evolucao", "nascimento", "transf_e", "outras_e")
COLUNAS_DE_SAIDA = ("abate", "morte", "venda", "transf_s", "outras_s")


def _coluna_do_movimento(tipo: str, fazenda_id, origem_id, destino_id):
    """Em qual coluna do quadro cai uma linha do razão, e com que sinal.

    `(coluna, sinal)`: o sinal é `+1` para somar a quantidade da linha como
    está (entradas) e `-1` para mostrá-la como número positivo (saídas). O papel
    da fazenda na transferência (`destino` ou `origem` do movimento) é o que
    separa "Transf. E" de "Transf. S" — e é o que faz o desfazer cancelar nas
    duas colunas, em vez de inflar as duas."""
    if tipo == MovementType.COMPRA:
        return "compra", 1
    if tipo == MovementType.NASCIMENTO:
        return "nascimento", 1
    if tipo == MovementType.EVOLUCAO:
        return "evolucao", 1  # líquido: sai de uma categoria, entra em outra
    if tipo == MovementType.ABATE:
        return "abate", -1
    if tipo == MovementType.MORTE:
        return "morte", -1
    if tipo == MovementType.VENDA:
        return "venda", -1
    if tipo == MovementType.CONSUMO_DOACAO:
        return "outras_s", -1
    if tipo in (MovementType.TRANSFERENCIA, MovementType.AJUSTE_INVENTARIO):
        interna = origem_id == destino_id
        recebe = destino_id == fazenda_id and not interna
        sai = origem_id == fazenda_id and not interna
        externa = tipo == MovementType.TRANSFERENCIA
        if recebe:
            return ("transf_e" if externa else "outras_e"), 1
        if sai:
            return ("transf_s" if externa else "outras_s"), -1
        # Entre lotes da mesma fazenda (ou fazenda não identificada): não é
        # entrada nem saída da fazenda; fica em "outras", pelo sinal da linha.
        return "outras", 1
    # Saldo inicial e reclassificação.
    return "outras_e", 1


def movimentacao_por_categoria(*, user, farm=None, start, end):
    """O quadro "Movimentação por fazenda" da planilha: por categoria, o saldo
    anterior ao período, as entradas, as saídas e a posição final.

    Tudo é `SUM` do razão (ADR 0002): nada é gravado. Como o desfazer escreve
    compensação **com a data do fato**, o quadro de um mês passado também se
    corrige. Devolve `(linhas, totais)`; cada linha é um dict com as colunas
    acima, `total_e`, `total_s` e `posicao` (= anterior + entradas − saídas, que
    é igual ao saldo do razão até `end`)."""
    base = HerdLedgerEntry.objects.for_user(user)
    if farm is not None:
        base = base.filter(farm=farm)

    anterior = {
        r["category_id"]: r["total"] or 0
        for r in base.filter(date__lt=start)
        .values("category_id")
        .annotate(total=Sum("quantity"))
        .order_by()
    }

    colunas = {}  # categoria -> coluna -> quantidade
    periodo = (
        base.filter(date__gte=start, date__lte=end)
        .values(
            "category_id",
            "movement__type",
            "farm_id",
            "movement__origin_farm_id",
            "movement__destination_farm_id",
        )
        .annotate(total=Sum("quantity"))
        .order_by()
    )
    for r in periodo:
        coluna, sinal = _coluna_do_movimento(
            r["movement__type"],
            r["farm_id"],
            r["movement__origin_farm_id"],
            r["movement__destination_farm_id"],
        )
        quantidade = r["total"] or 0
        if coluna == "outras":
            # Interna: a linha positiva é entrada de "outras", a negativa, saída.
            coluna, sinal = ("outras_e", 1) if quantidade >= 0 else ("outras_s", -1)
        celulas = colunas.setdefault(r["category_id"], {})
        celulas[coluna] = celulas.get(coluna, 0) + sinal * quantidade

    ids = set(anterior) | set(colunas)
    categorias = AnimalCategory.objects.filter(Q(is_active=True) | Q(pk__in=ids))
    linhas = []
    for categoria in categorias:
        celulas = colunas.get(categoria.pk, {})
        linha = {
            "categoria": categoria,
            "saldo_anterior": anterior.get(categoria.pk, 0),
        }
        for nome in (*COLUNAS_DE_ENTRADA, *COLUNAS_DE_SAIDA):
            linha[nome] = celulas.get(nome, 0)
        linha["total_e"] = sum(linha[n] for n in COLUNAS_DE_ENTRADA)
        linha["total_s"] = sum(linha[n] for n in COLUNAS_DE_SAIDA)
        linha["posicao"] = linha["saldo_anterior"] + linha["total_e"] - linha["total_s"]
        linhas.append(linha)

    chaves = (
        "saldo_anterior",
        *COLUNAS_DE_ENTRADA,
        "total_e",
        *COLUNAS_DE_SAIDA,
        "total_s",
        "posicao",
    )
    totais = {c: sum(linha[c] for linha in linhas) for c in chaves}
    return linhas, totais


def movimentos_da_fazenda(*, user, farm=None, start, end):
    """As movimentações confirmadas do período em que a fazenda é origem ou
    destino, em ordem de data — a lista "Movimentações de bovinos" da planilha."""
    qs = (
        listar_movimentos_para(user)
        .filter(status=Status.CONFIRMADA, date__gte=start, date__lte=end)
        .select_related(
            "origin_farm",
            "destination_farm",
            "origin_category",
            "destination_category",
            "partner",
            "origin_sale__buyer",
            "origin_purchase__seller",
        )
        .order_by("date", "id")
    )
    if farm is not None:
        qs = qs.filter(Q(origin_farm=farm) | Q(destination_farm=farm))
    return qs
