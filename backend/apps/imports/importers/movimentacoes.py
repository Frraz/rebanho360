"""F2-12 — importador de movimentações com conciliação.

A tarefa mais difícil do projeto: é onde os −140 da aba `GERAL` aparecem.

`TRANSF. S` e `TRANSF. E` estão em linhas separadas (às vezes em abas
diferentes) e precisam virar **um** movimento de 2 linhas. O importador
pareia por data, categoria e quantidade. **O que não parear vira pendência
na tela, para o usuário decidir — nunca contrapartida inventada.**

Decisões que a spec não cobria (registradas em docs/migracao/01 e na
pendência #10):

- `SALDO ANTERIOR` do quadro-resumo é dado de entrada, não derivado: vira
  `SALDO_INICIAL`. Sem ele, mortes e abates deixariam o saldo negativo.
- Linhas `COMPRA` das abas **não** são importadas aqui: a compra entra uma
  vez só, pela aba `COMPRA DE GADO` — senão o rebanho dobra.
- A planilha não diz de qual lote saiu cada animal. Saídas e transferências
  são debitadas do lote "saldo anterior" da fazenda (um por fazenda).
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from apps.core.exceptions import BusinessError
from apps.core.reversible import Status
from apps.herd.models import HerdLedgerEntry, HerdMovement, MovementType
from apps.herd.permissions import pode_lancar_em_safra_encerrada
from apps.herd.services import registrar_movimento
from apps.imports import readers
from apps.imports.importers.base import (
    Campo,
    ImportacaoFalhou,
    Importador,
    aviso,
    erro,
    linhas_abertas,
    pendencia,
    salvar_validacao,
    status_pelas_mensagens,
)
from apps.imports.models import ImportKind, ImportRow, RowStatus
from apps.livestock.models import AnimalCategory, Lot
from apps.livestock.services import criar_lote
from apps.organizations.models import Season, SeasonStatus
from apps.partners.models import Partner
from apps.properties.models import Farm

MARCA_LOTE_LEGADO = "Saldo anterior da planilha"

# Tipos da coluna TIPO (normalizados) → tipo interno.
TIPOS = {
    "saldo anterior": "SALDO",
    "compra": "COMPRA",
    "morte": "MORTE",
    "abate": "ABATE",
    "venda": "VENDA",
    "nasc.": "NASC",
    "nasc": "NASC",
    "evoluc": "EVOL",
    "transf. s": "TS",
    "transf. e": "TE",
}

TIPO_DO_MOVIMENTO = {
    "SALDO": MovementType.SALDO_INICIAL,
    "NASC": MovementType.NASCIMENTO,
    "EVOL": MovementType.EVOLUCAO,
    "MORTE": MovementType.MORTE,
    "ABATE": MovementType.ABATE,
    "VENDA": MovementType.VENDA,
    "TRANSF": MovementType.TRANSFERENCIA,
}

# Na mesma data, entradas antes das saídas: o saldo nunca é consultado
# antes de a entrada do mesmo dia existir.
PRIORIDADE = {
    "SALDO": 0,
    "NASC": 1,
    "TRANSF": 2,
    "EVOL": 2,
    "MORTE": 3,
    "ABATE": 3,
    "VENDA": 3,
}

#: Palavras da coluna DESTINO que repetem o tipo — não são destino de verdade.
DESTINOS_QUE_SAO_O_TIPO = {"morte", "compra", "abate", "venda", "entrega compra"}


@dataclass
class Mov:
    row: ImportRow
    kind: str
    date: datetime.date | None = None
    farm: Farm | None = None
    category: AnimalCategory | None = None
    quantity: int | None = None
    weight: Decimal | None = None
    destino: str = ""
    mensagens: list = field(default_factory=list)

    @property
    def completa(self) -> bool:
        return all((self.date, self.farm, self.category, self.quantity))


@dataclass
class Op:
    """Uma operação a registrar — 1 ou 2 linhas da planilha."""

    kind: str
    date: datetime.date
    category: AnimalCategory
    quantity: int
    rows: list
    origem: Farm | None = None
    destino: Farm | None = None
    categoria_destino: AnimalCategory | None = None
    weight: Decimal | None = None
    texto_destino: str = ""
    ordem: int = 0


class ImportadorDeMovimentacoes(Importador):
    kind = ImportKind.MOVIMENTACOES

    def ler(self, workbook):
        return readers.ler_movimentacoes(workbook)

    # ---- apoio ----------------------------------------------------------

    def _fazendas(self):
        return {
            readers.normalizar(f.name): f for f in Farm.objects.filter(is_active=True)
        }

    def _categorias(self):
        return {
            readers.normalizar(c.name): c
            for c in AnimalCategory.objects.filter(is_active=True)
        }

    def _safra_do_saldo(self, batch) -> Season | None:
        try:
            return Season.objects.filter(pk=int(batch.options.get("season_id"))).first()
        except (TypeError, ValueError):
            return None

    def _fazenda_da_aba(self, row, batch, fazendas) -> Farm | None:
        if "farm" in row.resolution:
            return Farm.objects.filter(pk=row.resolution["farm"]).first()
        mapeada = (batch.options.get("farm_map") or {}).get(
            readers.normalizar(row.sheet)
        )
        if mapeada:
            return Farm.objects.filter(pk=mapeada).first()
        return fazendas.get(readers.normalizar(row.sheet))

    def abas(self, batch) -> list[str]:
        return sorted({r.sheet for r in batch.rows.all()})

    def textos_de_destino(self, batch) -> list[tuple[str, int]]:
        fazendas = self._fazendas()
        contagem: dict[str, int] = {}
        for row in batch.rows.exclude(raw__tipo="SALDO ANTERIOR"):
            texto = readers.texto_da_celula(row.raw.get("destino"))
            norma = readers.normalizar(texto)
            if not texto or norma in DESTINOS_QUE_SAO_O_TIPO or norma in fazendas:
                continue
            if TIPOS.get(readers.normalizar(row.raw.get("tipo"))) in ("COMPRA", None):
                continue
            contagem[texto] = contagem.get(texto, 0) + 1
        return sorted(contagem.items())

    def descrever(self, row):
        raw = row.raw
        data = readers.data_da_celula(raw.get("data"))
        return " · ".join(
            [
                row.sheet,
                (
                    f"{data:%d/%m/%Y}"
                    if data
                    else (
                        "saldo anterior"
                        if raw.get("tipo") == "SALDO ANTERIOR"
                        else "sem data"
                    )
                ),
                readers.texto_da_celula(raw.get("tipo")) or "?",
                f"{readers.texto_da_celula(raw.get('quantidade')) or '?'} cb",
                readers.texto_da_celula(raw.get("categoria")) or "sem categoria",
            ]
        )

    # ---- leitura de cada linha -----------------------------------------

    def _interpretar_linha(self, row, batch, fazendas, categorias, safra_saldo) -> Mov:
        raw = row.raw
        tipo_texto = readers.texto_da_celula(raw.get("tipo"))
        kind = TIPOS.get(readers.normalizar(tipo_texto))
        mov = Mov(row=row, kind=kind or "?")

        if kind is None:
            mov.mensagens.append(
                erro(f'Tipo "{tipo_texto or "(vazio)"}" não reconhecido.', "tipo")
            )
            return mov

        mov.farm = self._fazenda_da_aba(row, batch, fazendas)
        if mov.farm is None:
            mov.mensagens.append(
                pendencia(f'Aba "{row.sheet}" sem fazenda correspondente.', "farm")
            )

        nome_categoria = readers.texto_da_celula(raw.get("categoria"))
        if "category" in row.resolution:
            mov.category = AnimalCategory.objects.filter(
                pk=row.resolution["category"]
            ).first()
        else:
            mov.category = categorias.get(readers.normalizar(nome_categoria))
        if mov.category is None:
            mov.mensagens.append(
                pendencia(
                    f'Categoria "{nome_categoria or "(vazio)"}" não encontrada.',
                    "category",
                )
            )

        mov.quantity = readers.inteiro_da_celula(
            row.resolution.get("quantity", raw.get("quantidade"))
        )
        if mov.quantity is None or mov.quantity <= 0:
            mov.quantity = None
            mov.mensagens.append(
                pendencia("Quantidade ausente ou inválida.", "quantity")
            )

        if kind == "SALDO":
            mov.date = (
                safra_saldo.start_date if safra_saldo else datetime.date(1900, 1, 1)
            )
            if safra_saldo is None:
                mov.mensagens.append(
                    pendencia("Escolha a safra do saldo anterior nas opções.", None)
                )
        else:
            mov.date = (
                readers.data_da_celula(row.resolution["date"])
                if "date" in row.resolution
                else readers.data_da_celula(raw.get("data"))
            )
            if mov.date is None:
                mov.mensagens.append(pendencia("Data inválida ou vazia.", "date"))
            elif mov.date > datetime.date.today():
                mov.mensagens.append(
                    pendencia(
                        f"Data no futuro ({mov.date:%d/%m/%Y}) — provável erro de digitação. Informe a data certa.",
                        "date",
                    )
                )
                mov.date = None
            else:
                season = self.safra_da_data(mov.date)
                if season is None:
                    mov.mensagens.append(
                        erro(
                            f"Não há safra cadastrada que cubra {mov.date:%d/%m/%Y}.",
                            "date",
                        )
                    )
                elif (
                    season.status == SeasonStatus.ENCERRADA
                    and not pode_lancar_em_safra_encerrada(batch.created_by)
                ):
                    mov.mensagens.append(
                        erro(
                            f"A safra {season.name} está encerrada: só o administrador importa nela.",
                            "date",
                        )
                    )

        mov.weight = readers.decimal_da_celula(raw.get("peso_total"))
        mov.destino = readers.texto_da_celula(raw.get("destino"))
        return mov

    # ---- validação ------------------------------------------------------

    def _lote_legado(self, farm) -> Lot | None:
        return Lot.objects.filter(
            farm=farm, notes__startswith=MARCA_LOTE_LEGADO
        ).first()

    def _saldo_do_banco(self, cache, farm, categoria, ate):
        chave = (farm.pk, categoria.pk)
        if chave not in cache:
            lote = self._lote_legado(farm)
            if lote is None:
                cache[chave] = 0
            else:
                linhas = HerdLedgerEntry.objects.filter(
                    lot=lote, farm=farm, category=categoria, date__lte=ate
                )
                cache[chave] = sum(q for q in linhas.values_list("quantity", flat=True))
        return cache[chave]

    def _planejar(self, batch):
        """Lê as linhas, pareia as transferências e devolve
        `(ops, movs, ignoradas)`. Escreve só nas mensagens em memória."""
        fazendas, categorias = self._fazendas(), self._categorias()
        safra_saldo = self._safra_do_saldo(batch)
        movs = [
            self._interpretar_linha(row, batch, fazendas, categorias, safra_saldo)
            for row in linhas_abertas(batch)
        ]

        ignoradas, ativos = {}, []
        for mov in movs:
            if mov.kind == "COMPRA":
                ignoradas[mov.row.pk] = (
                    "Compra: entra uma vez só, pela aba COMPRA DE GADO — importar "
                    "aqui também dobraria o rebanho."
                )
            elif mov.row.resolution.get("acao") == "IGNORAR":
                ignoradas[mov.row.pk] = "Ignorada por decisão do usuário."
            else:
                ativos.append(mov)

        ops: list[Op] = []
        transferencias = [m for m in ativos if m.kind in ("TS", "TE")]
        outros = [m for m in ativos if m.kind not in ("TS", "TE")]

        for mov in outros:
            if not mov.completa:
                continue
            if mov.kind == "EVOL":
                origem = AnimalCategory.objects.filter(
                    pk=mov.row.resolution.get("origin_category") or 0
                ).first()
                if origem is None:
                    anterior = self._categoria_anterior(mov.category)
                    mov.mensagens.append(
                        pendencia(
                            "Evolução precisa da categoria de ORIGEM (a planilha só traz a de destino).",
                            "origin_category",
                            (
                                {
                                    "valor": anterior.pk,
                                    "rotulo": anterior.name,
                                    "motivo": "categoria imediatamente anterior",
                                }
                                if anterior
                                else None
                            ),
                        )
                    )
                    continue
                ops.append(
                    Op(
                        "EVOL",
                        mov.date,
                        origem,
                        mov.quantity,
                        [mov.row],
                        origem=mov.farm,
                        destino=mov.farm,
                        categoria_destino=mov.category,
                        weight=mov.weight,
                    )
                )
            elif mov.kind in ("MORTE", "ABATE", "VENDA"):
                ops.append(
                    Op(
                        mov.kind,
                        mov.date,
                        mov.category,
                        mov.quantity,
                        [mov.row],
                        origem=mov.farm,
                        weight=mov.weight,
                        texto_destino=mov.destino,
                    )
                )
            else:  # SALDO, NASC
                ops.append(
                    Op(
                        mov.kind,
                        mov.date,
                        mov.category,
                        mov.quantity,
                        [mov.row],
                        destino=mov.farm,
                        weight=mov.weight,
                    )
                )

        # ---- pareamento das transferências ----
        livres_e: dict[tuple, list[Mov]] = {}
        for mov in transferencias:
            if mov.kind == "TE" and mov.completa and "acao" not in mov.row.resolution:
                livres_e.setdefault(
                    (mov.date, mov.category.pk, mov.quantity), []
                ).append(mov)

        pareadas = set()
        for mov in transferencias:
            if mov.kind != "TS" or not mov.completa or "acao" in mov.row.resolution:
                continue
            candidatos = livres_e.get((mov.date, mov.category.pk, mov.quantity), [])
            par = next(
                (
                    c
                    for c in candidatos
                    if c.farm.pk != mov.farm.pk and id(c) not in pareadas
                ),
                None,
            )
            if par is None:
                continue
            pareadas.update({id(mov), id(par)})
            mov.row.meta = {"par": par.row.pk}
            par.row.meta = {"par": mov.row.pk}
            ops.append(
                Op(
                    "TRANSF",
                    mov.date,
                    mov.category,
                    mov.quantity,
                    [mov.row, par.row],
                    origem=mov.farm,
                    destino=par.farm,
                    weight=mov.weight or par.weight,
                )
            )

        for mov in transferencias:
            if id(mov) in pareadas:
                continue
            mov.row.meta = {}
            if not mov.completa:
                continue
            acao = mov.row.resolution.get("acao")
            origem = Farm.objects.filter(
                pk=mov.row.resolution.get("origem") or 0
            ).first()
            destino = Farm.objects.filter(
                pk=mov.row.resolution.get("destino") or 0
            ).first()
            if acao == "DEFINIR" and origem and destino and origem.pk != destino.pk:
                ops.append(
                    Op(
                        "TRANSF",
                        mov.date,
                        mov.category,
                        mov.quantity,
                        [mov.row],
                        origem=origem,
                        destino=destino,
                        weight=mov.weight,
                    )
                )
                continue
            sentido = "saída" if mov.kind == "TS" else "entrada"
            lado = "entrada" if mov.kind == "TS" else "saída"
            mov.mensagens.append(
                pendencia(
                    f"Transferência de {sentido} de {mov.quantity} cabeças de {mov.category} em "
                    f"{mov.date:%d/%m/%Y} ({mov.row.sheet}) sem {lado} correspondente em nenhuma aba. "
                    "Decida: ignorar a linha ou definir origem e destino. "
                    "O sistema não inventa a contrapartida.",
                    "contrapartida",
                )
            )

        for i, op in enumerate(
            sorted(
                ops,
                key=lambda o: (
                    o.date,
                    PRIORIDADE[o.kind],
                    min(r.row_number for r in o.rows),
                ),
            )
        ):
            op.ordem = i
        ops.sort(key=lambda o: o.ordem)
        return ops, movs, ignoradas

    def _categoria_anterior(self, categoria):
        return (
            AnimalCategory.objects.filter(
                sex=categoria.sex, age_order__lt=categoria.age_order, is_active=True
            )
            .order_by("-age_order")
            .first()
            if categoria.age_order is not None
            else None
        )

    def _simular(self, ops, mensagens_por_linha):
        """Saldo corrente por (fazenda, categoria) no lote "saldo anterior":
        o que a prévia mostra é o que a importação vai encontrar."""
        if not ops:
            return
        ate = min(op.date for op in ops) - datetime.timedelta(days=1)
        cache, saldo = {}, {}

        def atual(farm, categoria):
            chave = (farm.pk, categoria.pk)
            if chave not in saldo:
                saldo[chave] = self._saldo_do_banco(cache, farm, categoria, ate)
            return saldo[chave]

        for op in ops:
            debitos = []
            if op.kind in ("MORTE", "ABATE", "VENDA"):
                debitos.append((op.origem, op.category))
            elif op.kind == "TRANSF":
                debitos.append((op.origem, op.category))
            elif op.kind == "EVOL":
                debitos.append((op.origem, op.category))

            for farm, categoria in debitos:
                disponivel = atual(farm, categoria)
                if disponivel < op.quantity:
                    texto = (
                        f"Saldo insuficiente: há {disponivel} cabeças de {categoria} "
                        f"em {farm} em {op.date:%d/%m/%Y}, foram informadas {op.quantity}. "
                        "(A planilha não diz de qual lote saíram: o saldo considerado é o do "
                        "lote 'saldo anterior' da fazenda.)"
                    )
                    for row in op.rows:
                        mensagens_por_linha.setdefault(row.pk, []).append(erro(texto))
                    break
            else:
                for farm, categoria in debitos:
                    saldo[(farm.pk, categoria.pk)] = (
                        atual(farm, categoria) - op.quantity
                    )
                if op.kind in ("SALDO", "NASC"):
                    saldo[(op.destino.pk, op.category.pk)] = (
                        atual(op.destino, op.category) + op.quantity
                    )
                elif op.kind == "TRANSF":
                    saldo[(op.destino.pk, op.category.pk)] = (
                        atual(op.destino, op.category) + op.quantity
                    )
                elif op.kind == "EVOL":
                    saldo[(op.destino.pk, op.categoria_destino.pk)] = (
                        atual(op.destino, op.categoria_destino) + op.quantity
                    )

    def validar(self, batch):
        ops, movs, ignoradas = self._planejar(batch)
        extras: dict[int, list] = {}
        self._simular(ops, extras)

        linhas = []
        for mov in movs:
            row = mov.row
            if row.pk in ignoradas:
                row.messages = [aviso(ignoradas[row.pk])]
                row.status = RowStatus.IGNORADA
                row.meta = {}
            else:
                row.messages = mov.mensagens + extras.get(row.pk, [])
                row.status = status_pelas_mensagens(row.messages)
            linhas.append(row)
        salvar_validacao(linhas)

    def problemas_de_configuracao(self, batch):
        problemas = []
        tem_saldo = batch.rows.filter(raw__tipo="SALDO ANTERIOR").exists()
        if tem_saldo and self._safra_do_saldo(batch) is None:
            problemas.append(
                "Escolha a safra do saldo anterior: é a data de abertura do rebanho."
            )
        return problemas

    def avisos_do_lote(self, batch):
        avisos = []
        compras_nas_abas: dict[str, int] = {}
        for row in batch.rows.filter(raw__tipo="COMPRA"):
            quantidade = readers.inteiro_da_celula(row.raw.get("quantidade")) or 0
            compras_nas_abas[row.sheet] = (
                compras_nas_abas.get(row.sheet, 0) + quantidade
            )
        fazendas = self._fazendas()
        from apps.purchases.models import Purchase

        for aba, quantidade in compras_nas_abas.items():
            farm = fazendas.get(readers.normalizar(aba))
            if farm is None:
                continue
            importadas = sum(
                Purchase.objects.filter(
                    status=Status.CONFIRMADA, destination_farm=farm
                ).values_list("head_count", flat=True)
            )
            if importadas and importadas != quantidade:
                avisos.append(
                    f"{farm}: as linhas COMPRA da aba somam {quantidade} cabeças, mas as compras "
                    f"importadas da aba COMPRA DE GADO somam {importadas} (diferença de "
                    f"{importadas - quantidade}). Confira se alguma compra ficou sem lançar na aba da fazenda."
                )
            elif not importadas:
                avisos.append(
                    f"{farm}: {quantidade} cabeças de COMPRA nas linhas da aba não são importadas aqui — "
                    "entram pela aba COMPRA DE GADO. Importe as compras primeiro."
                )
        return avisos

    # ---- decisões do usuário -------------------------------------------

    def campos_da_linha(self, row, batch):
        campos = []
        fazendas = [(f.pk, f.name) for f in Farm.objects.filter(is_active=True)]
        categorias = [
            (c.pk, c.name) for c in AnimalCategory.objects.filter(is_active=True)
        ]
        valores = lambda campo: str(row.resolution.get(campo, ""))  # noqa: E731
        tipo_da_linha = TIPOS.get(readers.normalizar(row.raw.get("tipo")))
        for m in row.pendencias:
            campo = m["campo"]
            if campo == "farm":
                campos.append(
                    Campo("farm", "Fazenda", "select", fazendas, valores("farm"))
                )
            elif campo == "category":
                campos.append(
                    Campo(
                        "category",
                        "Categoria",
                        "select",
                        categorias,
                        valores("category"),
                    )
                )
            elif campo == "date":
                campos.append(Campo("date", "Data", "data", valor=valores("date")))
            elif campo == "quantity":
                campos.append(
                    Campo("quantity", "Quantidade", "numero", valor=valores("quantity"))
                )
            elif campo == "origin_category":
                campos.append(
                    Campo(
                        "origin_category",
                        "Categoria de origem",
                        "select",
                        categorias,
                        valores("origin_category"),
                        (m.get("sugestao") or {}).get("rotulo", ""),
                    )
                )
            elif campo == "contrapartida":
                campos.append(
                    Campo(
                        "acao",
                        "O que fazer",
                        "select",
                        [
                            ("IGNORAR", "Ignorar esta linha (não importar)"),
                            ("DEFINIR", "Definir origem e destino"),
                        ],
                        valores("acao"),
                    )
                )
                campos.append(
                    Campo(
                        "origem",
                        "Fazenda de origem",
                        "select",
                        fazendas,
                        valores("origem"),
                    )
                )
                campos.append(
                    Campo(
                        "destino",
                        "Fazenda de destino",
                        "select",
                        fazendas,
                        valores("destino"),
                    )
                )
        # Transferência já decidida continua editável (trocar a decisão).
        if (
            tipo_da_linha in ("TS", "TE")
            and "acao" in row.resolution
            and not any(c.nome == "acao" for c in campos)
        ):
            campos.extend(
                [
                    Campo(
                        "acao",
                        "O que fazer",
                        "select",
                        [
                            ("IGNORAR", "Ignorar esta linha (não importar)"),
                            ("DEFINIR", "Definir origem e destino"),
                        ],
                        valores("acao"),
                    ),
                    Campo(
                        "origem",
                        "Fazenda de origem",
                        "select",
                        fazendas,
                        valores("origem"),
                    ),
                    Campo(
                        "destino",
                        "Fazenda de destino",
                        "select",
                        fazendas,
                        valores("destino"),
                    ),
                ]
            )
        return campos

    # ---- importação -----------------------------------------------------

    def _lote_para(self, farm, cache, data_minima, safra_saldo):
        if farm.pk in cache:
            return cache[farm.pk]
        lote = self._lote_legado(farm)
        if lote is None:
            lote = Lot(
                farm=farm,
                season=self.safra_da_data(data_minima) or safra_saldo,
                entry_date=data_minima,
                notes=f"{MARCA_LOTE_LEGADO} (importação): reúne o rebanho que a planilha "
                "não separa por lote.",
            )
            criar_lote(lote, usuario=self._usuario)
        cache[farm.pk] = lote
        return lote

    def _parceiro(self, texto, batch, cache):
        if not texto:
            return None
        norma = readers.normalizar(texto)
        if norma in cache:
            return cache[norma]
        decisao = (batch.options.get("destinos") or {}).get(norma) or {}
        parceiro = None
        if decisao.get("acao") == "VINCULAR" and decisao.get("partner_id"):
            parceiro = Partner.objects.filter(pk=decisao["partner_id"]).first()
        elif decisao.get("acao") == "CRIAR":
            parceiro = Partner.objects.filter(
                name=texto
            ).first() or Partner.objects.create(name=texto)
        cache[norma] = parceiro
        return parceiro

    def importar(self, batch, usuario) -> dict:
        self._usuario = usuario
        ops, _, ignoradas = self._planejar(batch)
        if not ops:
            return {"movimentos": 0, "cabecas": 0}

        # Revalida o plano contra o saldo REAL, dentro da transação.
        extras: dict[int, list] = {}
        self._simular(ops, extras)
        if extras:
            primeira = next(iter(extras.values()))[0]["texto"]
            raise ImportacaoFalhou(primeira)

        safra_saldo = self._safra_do_saldo(batch)
        data_minima = min(op.date for op in ops)
        lotes, parceiros = {}, {}
        tipo = ContentType.objects.get_for_model(HerdMovement)
        movimentos, cabecas = 0, 0

        for op in ops:
            nota = " · ".join(f"aba {r.sheet}, linha {r.row_number}" for r in op.rows)
            partner = self._parceiro(op.texto_destino, batch, parceiros)
            observacao = f"Importado da planilha ({nota})."
            if op.texto_destino:
                observacao += f" Destino na planilha: {op.texto_destino}."
            argumentos = {
                "date": op.date,
                "quantity": op.quantity,
                "usuario": usuario,
                "total_weight_kg": op.weight,
                "partner": partner,
                "notes": observacao,
            }
            if op.kind == "MORTE":
                argumentos["reason"] = (
                    f"Importado da planilha, motivo não informado ({nota})."
                )
            if op.kind == "SALDO":
                argumentos["season"] = safra_saldo
            try:
                if op.kind in ("SALDO", "NASC"):
                    lote = self._lote_para(op.destino, lotes, data_minima, safra_saldo)
                    movimento = registrar_movimento(
                        type=TIPO_DO_MOVIMENTO[op.kind],
                        destination_farm=op.destino,
                        destination_lot=lote,
                        destination_category=op.category,
                        **argumentos,
                    )
                elif op.kind in ("MORTE", "ABATE", "VENDA"):
                    lote = self._lote_para(op.origem, lotes, data_minima, safra_saldo)
                    movimento = registrar_movimento(
                        type=TIPO_DO_MOVIMENTO[op.kind],
                        origin_farm=op.origem,
                        origin_lot=lote,
                        origin_category=op.category,
                        **argumentos,
                    )
                else:  # TRANSF, EVOL
                    categoria_destino = op.categoria_destino or op.category
                    movimento = registrar_movimento(
                        type=TIPO_DO_MOVIMENTO[op.kind],
                        origin_farm=op.origem,
                        origin_lot=self._lote_para(
                            op.origem, lotes, data_minima, safra_saldo
                        ),
                        origin_category=op.category,
                        destination_farm=op.destino,
                        destination_lot=self._lote_para(
                            op.destino, lotes, data_minima, safra_saldo
                        ),
                        destination_category=categoria_destino,
                        **argumentos,
                    )
            except BusinessError as exc:
                raise ImportacaoFalhou(f"{nota}: {exc}") from exc

            for row in op.rows:
                row.status = RowStatus.IMPORTADA
                row.target_type, row.target_id = tipo, movimento.pk
                row.save(update_fields=["status", "target_type", "target_id"])
            movimentos += 1
            cabecas += op.quantity
        return {"movimentos": movimentos, "cabecas": cabecas}
