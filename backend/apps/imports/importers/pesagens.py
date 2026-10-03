"""F3-07 — importador de PESAGENS E CONFERENCIA: o desempilhamento.

Nove blocos paralelos `(DATA, BRINCO, PESO, MOVIMENTAÇÃO)` viram uma tabela
só. Agrupa por `(data, motivo)`, cria uma `Weighing` por grupo e uma
`WeighingAnimal(ear_tag, weight_kg)` por linha — **sem entidade `Animal`**
(ADR 0004).

O que a planilha real mostrou (docs/migracao/01):

- `SB` na coluna de brinco é **sem brinco**, não um brinco repetido. 3
  blocos (591 animais) não têm brinco nenhum.
- Há brincos repetidos *com pesos diferentes no mesmo dia* (o 1759 aparece 3
  vezes em 16/12/2025): não é o mesmo animal pesado duas vezes. Nenhum é
  descartado — vira aviso. "Nenhum brinco se perdeu" é o critério de pronto.
- `VACINA COFERENCIA` (sic) é "vacina + conferência". Um bloco não tem
  motivo nenhum.
- A planilha **não diz de qual lote** foi cada pesagem. Lote e motivo de
  cada grupo são decisão do usuário, nas opções, com sugestão — que só vale
  depois de salva.
"""

from collections import Counter, defaultdict
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from apps.core.exceptions import BusinessError
from apps.core.formatting import numero_br
from apps.core.reversible import Status
from apps.herd.models import Weighing, WeighingAnimal, WeighingReason
from apps.herd.services import registrar_pesagem
from apps.imports import readers
from apps.imports.importers.base import (
    ACAO_IGNORAR,
    Campo,
    ImportacaoFalhou,
    Importador,
    aviso,
    ignorada_pelo_usuario,
    linhas_abertas,
    pendencia,
    salvar_validacao,
    status_pelas_mensagens,
)
from apps.imports.models import ImportKind, ImportRow, RowStatus
from apps.livestock.models import Lot, LotStatus

#: Texto da coluna MOVIMENTAÇÃO (normalizado) → motivo da pesagem. É só a
#: **sugestão** do formulário de opções; vale quando o usuário salva.
MOTIVOS_SUGERIDOS = {
    "conferencia": WeighingReason.CONFERENCIA,
    "abate": WeighingReason.ABATE,
    "compra": WeighingReason.COMPRA,
    "compra goiano": WeighingReason.COMPRA,
    "venda": WeighingReason.VENDA,
    "vacina": WeighingReason.VACINA,
    "vacina conferencia": WeighingReason.VACINA,
    "vacina coferencia": WeighingReason.VACINA,  # sic: é assim que a planilha grafa
}

#: Peso por animal fora disto é aviso (digitação), nunca bloqueio.
PESO_USUAL_KG = (Decimal("20"), Decimal("1200"))

MARCAS_DE_SEM_BRINCO = {"sb", "s/b", "sem brinco"}


def chave_do_grupo(data, motivo_texto) -> str:
    return f"{data.isoformat()}|{readers.normalizar(motivo_texto)}"


class ImportadorDePesagens(Importador):
    kind = ImportKind.PESAGENS

    def ler(self, workbook):
        return readers.ler_pesagens(workbook)

    # ---- leitura de uma linha --------------------------------------------

    @staticmethod
    def _brinco(bruto) -> str:
        if bruto is None or readers.eh_erro_de_celula(bruto):
            return ""
        if isinstance(bruto, float) and bruto == int(bruto):
            bruto = int(bruto)
        texto = str(bruto).strip()
        return "" if readers.normalizar(texto) in MARCAS_DE_SEM_BRINCO else texto

    def _interpretar(self, row: ImportRow):
        raw, mensagens = row.raw, []

        data = (
            readers.data_da_celula(row.resolution["date"])
            if "date" in row.resolution
            else readers.data_da_celula(raw.get("data"))
        )
        if data is None:
            mensagens.append(pendencia("Data inválida ou vazia.", "date"))

        peso = readers.decimal_da_celula(
            row.resolution.get("weight_kg", raw.get("peso"))
        )
        if peso is None or peso <= 0:
            mensagens.append(pendencia("Peso ausente ou inválido.", "weight_kg"))
        elif not (PESO_USUAL_KG[0] <= peso <= PESO_USUAL_KG[1]):
            mensagens.append(
                aviso(
                    f"Peso de {numero_br(peso, 0)} kg para um animal é fora do usual — confira."
                )
            )

        motivo = readers.texto_da_celula(raw.get("movimentacao"))
        return (
            {
                "date": data,
                "weight": peso,
                "ear_tag": self._brinco(raw.get("brinco")),
                "motivo_texto": motivo,
                "chave": chave_do_grupo(data, motivo) if data else None,
            },
            mensagens,
        )

    def descrever(self, row):
        raw = row.raw
        data = readers.data_da_celula(raw.get("data"))
        brinco = self._brinco(raw.get("brinco"))
        peso = readers.decimal_da_celula(raw.get("peso"))
        return " · ".join(
            [
                f"{data:%d/%m/%Y}" if data else "sem data",
                f"brinco {brinco}" if brinco else "sem brinco",
                f"{numero_br(peso, 0)} kg" if peso else "sem peso",
                readers.texto_da_celula(raw.get("movimentacao")) or "sem motivo",
                f"bloco {raw.get('bloco')}",
            ]
        )

    # ---- grupos (data, motivo) -------------------------------------------

    def grupos(self, batch) -> list[dict]:
        """Os grupos que viram uma `Weighing` cada, com o que a prévia precisa
        para o usuário reconhecê-los."""
        grupos: dict[str, dict] = {}
        for row in batch.rows.exclude(status=RowStatus.IMPORTADA).order_by("id"):
            if ignorada_pelo_usuario(row):
                continue
            dados, _ = self._interpretar(row)
            if dados["chave"] is None:
                continue
            grupo = grupos.setdefault(
                dados["chave"],
                {
                    "chave": dados["chave"],
                    "date": dados["date"],
                    "motivo_texto": dados["motivo_texto"],
                    "animais": 0,
                    "kg": Decimal("0"),
                },
            )
            grupo["animais"] += 1
            grupo["kg"] += dados["weight"] or Decimal("0")
        return sorted(grupos.values(), key=lambda g: (g["date"], g["chave"]))

    @staticmethod
    def rotulo_do_grupo(grupo) -> str:
        return (
            f"{grupo['date']:%d/%m/%Y} · {grupo['motivo_texto'] or 'sem motivo'} · "
            f"{numero_br(Decimal(grupo['animais']), 0)} animais · {numero_br(grupo['kg'], 0)} kg"
        )

    def sugestao_do_grupo(self, grupo) -> dict:
        """O que o sistema **sugere** para o grupo — nunca aplica sozinho.

        Lote: pela compra ou pela venda que casa com a data e o tamanho do
        grupo. Motivo: pelo texto da planilha (ou, sem texto, pela compra do
        mesmo dia).
        """
        from apps.purchases.models import Purchase
        from apps.sales.models import Sale

        data, n = grupo["date"], grupo["animais"]
        motivo = MOTIVOS_SUGERIDOS.get(readers.normalizar(grupo["motivo_texto"]))
        lote, por_que = None, ""

        if motivo in (WeighingReason.ABATE, WeighingReason.VENDA):
            venda = next(
                (
                    v
                    for v in Sale.objects.filter(
                        status=Status.CONFIRMADA, head_count=n
                    ).select_related("lot")
                    if abs((v.date - data).days) <= 3
                ),
                None,
            )
            if venda:
                lote = venda.lot
                por_que = f"a venda {venda.code} ({venda.head_count} cabeças, {venda.date:%d/%m/%Y}) saiu deste lote"
        else:
            compras = list(
                Purchase.objects.filter(
                    status=Status.CONFIRMADA, date=data
                ).select_related("lot")
            )
            if compras and motivo is None:
                motivo = WeighingReason.COMPRA
            if motivo == WeighingReason.COMPRA and compras:
                igual = next((c for c in compras if c.head_count == n), None)
                escolhida = igual or (compras[0] if len(compras) == 1 else None)
                if escolhida and escolhida.lot_id:
                    lote = escolhida.lot
                    por_que = f"a compra {escolhida.code} ({escolhida.head_count} cabeças) é de {escolhida.date:%d/%m/%Y}"
        return {"lote": lote, "motivo": motivo, "por_que": por_que}

    def _decisao(self, batch, chave) -> dict:
        return (batch.options.get("grupos") or {}).get(chave) or {}

    # ---- validação -------------------------------------------------------

    def validar(self, batch):
        # São milhares de linhas (4.058 na planilha real): só grava a que mudou.
        alteradas = []
        for row in linhas_abertas(batch):
            if ignorada_pelo_usuario(row):
                mensagens, status = (
                    [aviso("Ignorada por decisão do usuário.")],
                    RowStatus.IGNORADA,
                )
            else:
                _, mensagens = self._interpretar(row)
                status = status_pelas_mensagens(mensagens)
            if mensagens != row.messages or status != row.status:
                row.messages, row.status = mensagens, status
                alteradas.append(row)
        salvar_validacao(alteradas)

    def problemas_de_configuracao(self, batch) -> list[str]:
        """Cada grupo precisa de lote e de motivo, decididos nas opções —
        a planilha não diz de qual lote é cada pesagem."""
        problemas = []
        for grupo in self.grupos(batch):
            decisao = self._decisao(batch, grupo["chave"])
            if not decisao.get("lot_id") or not decisao.get("reason"):
                problemas.append(
                    f"Escolha o lote e o motivo da pesagem de {self.rotulo_do_grupo(grupo)} "
                    "nas opções."
                )
        return problemas

    def avisos_do_lote(self, batch) -> list[str]:
        sem_brinco, por_grupo = 0, defaultdict(Counter)
        for row in batch.rows.exclude(status=RowStatus.IMPORTADA):
            if ignorada_pelo_usuario(row):
                continue
            dados, _ = self._interpretar(row)
            if dados["chave"] is None:
                continue
            if dados["ear_tag"]:
                por_grupo[dados["chave"]][dados["ear_tag"]] += 1
            else:
                sem_brinco += 1

        avisos = []
        if sem_brinco:
            avisos.append(
                f"{sem_brinco} animais estão sem brinco (SB na planilha). Entram na "
                "pesagem com o brinco em branco — o peso conta, o brinco não existe."
            )
        for grupo in self.grupos(batch):
            repetidos = {
                brinco: n for brinco, n in por_grupo[grupo["chave"]].items() if n > 1
            }
            if repetidos:
                exemplo = max(repetidos, key=repetidos.get)
                avisos.append(
                    f"Pesagem de {grupo['date']:%d/%m/%Y}: {len(repetidos)} brinco(s) "
                    f"repetido(s) (o {exemplo} aparece {repetidos[exemplo]}×, com pesos "
                    "diferentes). Todos são importados — nenhum brinco é descartado."
                )
            decisao = self._decisao(batch, grupo["chave"])
            if decisao.get("lot_id") and decisao.get("reason"):
                parecida = Weighing.objects.filter(
                    status=Status.CONFIRMADA,
                    lot_id=decisao["lot_id"],
                    date=grupo["date"],
                    reason=decisao["reason"],
                    head_count=grupo["animais"],
                ).first()
                if parecida:
                    avisos.append(
                        f"A pesagem de {grupo['date']:%d/%m/%Y} parece já lançada "
                        "(mesmo lote, data, motivo e quantidade de animais)."
                    )
        pendentes = batch.rows.filter(status__in=[RowStatus.PENDENTE, RowStatus.ERRO])
        if pendentes.exists():
            avisos.append(
                f"{pendentes.count()} linha(s) pendentes ficarão de fora: a pesagem do "
                "grupo delas sai com menos animais. Resolva antes se isso importa."
            )
        return avisos

    def campos_da_linha(self, row, batch):
        campos = []
        for m in row.pendencias:
            campo, atual = m["campo"], str(row.resolution.get(m["campo"], ""))
            if campo == "date":
                campos.append(Campo(campo, "Data", "data", valor=atual))
            elif campo == "weight_kg":
                campos.append(Campo(campo, "Peso (kg)", "numero", valor=atual))
        if campos or ignorada_pelo_usuario(row):
            campos.append(
                Campo(
                    "acao",
                    "Ou, se não é uma pesagem",
                    "select",
                    [ACAO_IGNORAR],
                    str(row.resolution.get("acao", "")),
                )
            )
        return campos

    # ---- importação ------------------------------------------------------

    def importar(self, batch, usuario) -> dict:
        tipo = ContentType.objects.get_for_model(Weighing)
        por_grupo: dict[str, list] = defaultdict(list)
        for row in batch.rows.filter(status=RowStatus.VALIDA).order_by(
            "sheet", "row_number"
        ):
            dados, _ = self._interpretar(row)
            por_grupo[dados["chave"]].append((row, dados))

        pesagens, animais, total = 0, 0, Decimal("0")
        importadas = []
        for chave, itens in sorted(
            por_grupo.items(), key=lambda kv: (kv[1][0][1]["date"], kv[0])
        ):
            decisao = self._decisao(batch, chave)
            data = itens[0][1]["date"]
            lote = Lot.objects.select_related("farm").get(pk=decisao["lot_id"])
            if lote.status == LotStatus.EXCLUIDO:
                raise ImportacaoFalhou(f"O lote {lote.code} foi excluído.")
            peso_do_grupo = sum((d["weight"] for _, d in itens), Decimal("0"))
            try:
                pesagem = registrar_pesagem(
                    date=data,
                    farm=lote.farm,
                    lot=lote,
                    reason=decisao["reason"],
                    head_count=len(itens),
                    total_weight_kg=peso_do_grupo,
                    usuario=usuario,
                )
            except BusinessError as exc:
                raise ImportacaoFalhou(
                    f"Pesagem de {data:%d/%m/%Y} ({itens[0][1]['motivo_texto'] or 'sem motivo'}): {exc}"
                ) from exc
            WeighingAnimal.objects.bulk_create(
                [
                    WeighingAnimal(
                        weighing=pesagem, ear_tag=d["ear_tag"], weight_kg=d["weight"]
                    )
                    for _, d in itens
                ],
                batch_size=1000,
            )
            for row, _ in itens:
                row.status = RowStatus.IMPORTADA
                row.target_type, row.target_id = tipo, pesagem.pk
                importadas.append(row)
            pesagens += 1
            animais += len(itens)
            total += peso_do_grupo
        ImportRow.objects.bulk_update(
            importadas, ["status", "target_type", "target_id"], batch_size=500
        )
        return {"pesagens": pesagens, "animais": animais, "kg": total}
