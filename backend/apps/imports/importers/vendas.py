"""F3-08 — importador de VENDAS: 3 abates, 354 cabeças, R$ 2.298.586,23.

Os sete derivados da planilha (peso médio, carcaça média, rendimento %,
valor/cabeça, valor/@, mês, ano) **não viram campo**. Mas são lidos para a
conferência: depois de importar, o `CarcassService` recalcula e a diferença
vira aviso — foi assim que a pendência #7 (`SOMA RENDIMENTO`) apareceu.

**O que a spec não previu (e a planilha real mostrou):** a aba da fazenda
`SÃO FRANCISCO` já registra os 3 abates, e o importador de movimentações os
importa como saídas no rebanho. Importar `VENDAS` por cima debitaria as 354
cabeças **duas vezes**. Por isso, antes de criar uma saída nova, o importador
procura a que já existe (mesma categoria e quantidade, data a ≤ 3 dias) e
**propõe vincular**: a venda adota a saída em vez de debitar de novo. O
vínculo é decisão do usuário — o sistema sugere, não decide — e a diferença
de peso ou de data entre a venda e o movimento vira aviso (pendência #12),
nunca correção silenciosa.
"""

import datetime
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from apps.core.exceptions import BusinessError
from apps.core.formatting import numero_br
from apps.core.reversible import Status
from apps.herd.models import HerdMovement, MovementType
from apps.herd.permissions import pode_lancar_em_safra_encerrada
from apps.imports import readers
from apps.imports.importers.base import (
    ACAO_IGNORAR,
    Campo,
    GrupoDeSugestao,
    ImportacaoFalhou,
    Importador,
    aviso,
    erro,
    ignorada_pelo_usuario,
    linhas_abertas,
    pendencia,
    salvar_validacao,
    status_pelas_mensagens,
)
from apps.imports.models import ImportKind, ImportRow, RowStatus
from apps.livestock.models import AnimalCategory, Lot, LotStatus
from apps.organizations.models import SeasonStatus
from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
from apps.properties.models import Farm
from apps.sales import carcass, services
from apps.sales.models import Sale, SaleForm, SaleType

#: Janela, em dias, entre a data da venda e a da saída que a aba da fazenda
#: registrou (a planilha real tem diferenças de 0 e de 1 dia).
JANELA_DE_DATA = 3

TIPOS = {"abate": SaleType.ABATE, "venda": SaleType.VENDA}
FORMAS = {"pasto": SaleForm.PASTO, "confinamento": SaleForm.CONFINAMENTO}
TIPO_DO_MOVIMENTO = {
    SaleType.ABATE: MovementType.ABATE,
    SaleType.VENDA: MovementType.VENDA,
}

SUGESTAO_ROTULO = "a saída que já está no rebanho"
SUGESTAO_MOTIVO = f"mesma categoria e quantidade, data a até {JANELA_DE_DATA} dias"

PAPEIS_DE_COMPRADOR = (
    (PartnerRoleChoice.FRIGORIFICO, "Frigorífico"),
    (PartnerRoleChoice.COMPRADOR, "Comprador"),
)


class ImportadorDeVendas(Importador):
    kind = ImportKind.VENDAS

    def ler(self, workbook):
        return readers.ler_vendas(workbook)

    # ---- apoio ----------------------------------------------------------

    def _fazendas(self) -> dict[str, Farm]:
        return {
            readers.normalizar(f.name): f for f in Farm.objects.filter(is_active=True)
        }

    def _categorias(self) -> dict[str, AnimalCategory]:
        return {
            readers.normalizar(c.name): c
            for c in AnimalCategory.objects.filter(is_active=True)
        }

    def _textos(self, batch, chave) -> list[str]:
        textos = {readers.texto_da_celula(r.raw.get(chave)) for r in batch.rows.all()}
        return sorted(t for t in textos if t)

    def textos_de_categoria(self, batch):
        return self._textos(batch, "categoria")

    def textos_de_fazenda(self, batch):
        return self._textos(batch, "fazenda")

    def textos_de_comprador(self, batch):
        return self._textos(batch, "comprador")

    def _categoria_da_linha(self, row, batch, categorias):
        if "category" in row.resolution:
            return AnimalCategory.objects.filter(pk=row.resolution["category"]).first()
        texto = readers.texto_da_celula(row.raw.get("categoria"))
        mapeada = (batch.options.get("category_map") or {}).get(
            readers.normalizar(texto)
        )
        if mapeada:
            return AnimalCategory.objects.filter(pk=mapeada).first()
        return categorias.get(readers.normalizar(texto))

    def _fazenda_da_linha(self, row, batch, fazendas):
        if "farm" in row.resolution:
            return Farm.objects.filter(pk=row.resolution["farm"]).first()
        texto = readers.texto_da_celula(row.raw.get("fazenda"))
        mapeada = (batch.options.get("farm_map") or {}).get(readers.normalizar(texto))
        if mapeada:
            return Farm.objects.filter(pk=mapeada).first()
        return fazendas.get(readers.normalizar(texto))

    def _decisao_do_comprador(self, row, batch) -> dict | None:
        texto = readers.texto_da_celula(row.raw.get("comprador"))
        return (batch.options.get("buyer_map") or {}).get(readers.normalizar(texto))

    def _lote_legado(self, farm):
        from apps.imports.importers.movimentacoes import MARCA_LOTE_LEGADO

        return Lot.objects.filter(
            farm=farm, notes__startswith=MARCA_LOTE_LEGADO
        ).first()

    def _candidatos(self, data, categoria, cabecas, tipo, usados) -> list[HerdMovement]:
        """Saídas já no razão que podem ser esta venda."""
        janela = datetime.timedelta(days=JANELA_DE_DATA)
        return [
            m
            for m in HerdMovement.objects.filter(
                status=Status.CONFIRMADA,
                type=TIPO_DO_MOVIMENTO[tipo],
                origin_sale__isnull=True,
                origin_purchase__isnull=True,
                quantity=cabecas,
                origin_category=categoria,
                date__gte=data - janela,
                date__lte=data + janela,
            )
            .select_related("origin_farm", "origin_lot", "origin_category")
            .order_by("date", "id")
            if m.pk not in usados
        ]

    @staticmethod
    def _rotulo_do_movimento(m: HerdMovement) -> str:
        peso = f" · {numero_br(m.total_weight_kg, 0)} kg" if m.total_weight_kg else ""
        return f"{m.code} · {m.date:%d/%m/%Y} · {m.quantity} cb{peso} · {m.origin_farm}"

    def descrever(self, row):
        raw = row.raw
        data = readers.data_da_celula(raw.get("data"))
        return " · ".join(
            [
                f"{data:%d/%m/%Y}" if data else "sem data",
                readers.texto_da_celula(raw.get("tipo")) or "sem tipo",
                f"{readers.texto_da_celula(raw.get('animais')) or '?'} cabeças",
                readers.texto_da_celula(raw.get("categoria")) or "sem categoria",
                readers.texto_da_celula(raw.get("comprador")) or "sem comprador",
                readers.texto_da_celula(raw.get("fazenda")) or "sem fazenda",
            ]
        )

    # ---- validação ------------------------------------------------------

    def _comparar_com_a_planilha(self, raw, ind) -> list[dict]:
        """Os derivados que a planilha gravou × o que o `CarcassService`
        calcula. Divergência é aviso, não erro."""
        planilha = raw.get("planilha") or {}
        avisos = []

        def numero(chave):
            return readers.decimal_da_celula(planilha.get(chave))

        tolerancia = Decimal("0.01")
        comparacoes = [
            ("peso médio", numero("peso_medio"), ind.peso_medio_vivo, " kg"),
            ("carcaça média", numero("carcaca_media"), ind.carcaca_media, " kg"),
            (
                "rendimento",
                (
                    numero("rendimento") * 100
                    if numero("rendimento") is not None
                    else None
                ),
                ind.rendimento,
                "%",
            ),
            ("valor por cabeça", numero("valor_cabeca"), ind.valor_por_cabeca, ""),
            ("valor por @", numero("valor_arroba"), ind.valor_por_arroba, ""),
        ]
        for nome, da_planilha, calculado, unidade in comparacoes:
            if da_planilha is None or calculado is None:
                continue
            if abs(da_planilha - calculado) > tolerancia:
                avisos.append(
                    f"Planilha diz {nome} {numero_br(da_planilha, 2)}{unidade}; o cálculo "
                    f"dá {numero_br(calculado, 2)}{unidade}."
                )
        soma = numero("soma_rendimento")
        if soma is not None:
            rendimento = (
                f"{numero_br(ind.rendimento, 2)}%"
                if ind.rendimento is not None
                else "—"
            )
            avisos.append(
                f"SOMA RENDIMENTO da planilha ({numero_br(soma, 2)}) não corresponde a "
                f"nenhum indicador (não é o rendimento, {rendimento}, nem arroba). Não é "
                "importada — pendência #7."
            )
        return avisos

    def _interpretar(self, row: ImportRow, batch, ctx):
        """`ctx` = fazendas, categorias, `usados` (saídas já reivindicadas
        por outra linha nesta passada)."""
        raw, mensagens = row.raw, []
        fazendas, categorias, usados = ctx["fazendas"], ctx["categorias"], ctx["usados"]

        data = (
            readers.data_da_celula(row.resolution["date"])
            if "date" in row.resolution
            else readers.data_da_celula(raw.get("data"))
        )
        if data is None:
            mensagens.append(pendencia("Data inválida ou vazia.", "date"))

        texto_tipo = row.resolution.get("type") or readers.normalizar(raw.get("tipo"))
        tipo = TIPOS.get(readers.normalizar(texto_tipo))
        if tipo is None:
            mensagens.append(
                pendencia(
                    f'Tipo de venda "{raw.get("tipo") or "(vazio)"}" desconhecido: '
                    "informe se é abate ou venda de animal vivo.",
                    "type",
                )
            )

        cabecas = readers.inteiro_da_celula(
            row.resolution.get("head_count", raw.get("animais"))
        )
        if cabecas is None or cabecas <= 0:
            mensagens.append(
                pendencia("Quantidade de cabeças ausente ou inválida.", "head_count")
            )

        peso = readers.decimal_da_celula(
            row.resolution.get("total_weight_kg", raw.get("peso_total"))
        )
        if peso is None or peso <= 0:
            mensagens.append(
                pendencia("Peso vivo ausente ou inválido.", "total_weight_kg")
            )

        valor = readers.decimal_da_celula(
            row.resolution.get("total_value", raw.get("valor_total"))
        )
        if valor is None or valor <= 0:
            mensagens.append(
                pendencia("Valor da venda ausente ou inválido.", "total_value")
            )

        carcaca = readers.decimal_da_celula(raw.get("carcaca_total"))
        if tipo == SaleType.VENDA:
            carcaca = None
        if carcaca is not None and peso and carcaca >= peso:
            mensagens.append(
                erro(
                    "A carcaça pesa tanto quanto o animal vivo: rendimento acima de 100%."
                )
            )

        categoria = self._categoria_da_linha(row, batch, categorias)
        if categoria is None:
            texto = readers.texto_da_celula(raw.get("categoria")) or "(vazio)"
            mensagens.append(
                pendencia(
                    f'Categoria "{texto}" sem mapeamento — confirme nas opções.',
                    "category",
                )
            )

        # Comprador: o papel (Frigorífico/Comprador) é decisão do usuário.
        decisao = self._decisao_do_comprador(row, batch)
        if decisao is None:
            texto = readers.texto_da_celula(raw.get("comprador")) or "(vazio)"
            mensagens.append(
                pendencia(
                    f'Comprador "{texto}" sem vínculo — confirme nas opções.', "buyer"
                )
            )

        forma = FORMAS.get(readers.normalizar(raw.get("forma")))
        if forma is None:
            if readers.texto_da_celula(raw.get("forma")):
                mensagens.append(
                    pendencia(f'Forma "{raw["forma"]}" desconhecida.', "sale_form")
                )
            else:
                forma = SaleForm.PASTO
                mensagens.append(
                    aviso("Forma não informada na planilha: assumido PASTO.")
                )
        if "sale_form" in row.resolution:
            forma = row.resolution["sale_form"]

        # --- a saída: vincular à que já existe, ou criar uma nova ---
        movimento = farm = lote = None
        escolha = row.resolution.get("movement")
        candidatos = []
        if data and categoria and cabecas and tipo:
            candidatos = self._candidatos(data, categoria, cabecas, tipo, usados)

        if not (data and categoria and cabecas and tipo):
            # Sem os dados-base não há como procurar a saída: as pendências
            # acima já dizem o que falta, sem somar outras em cascata.
            pass
        elif escolha not in (None, "", "NOVA"):
            movimento = next((m for m in candidatos if str(m.pk) == str(escolha)), None)
            if movimento is None:
                mensagens.append(
                    erro(
                        "A saída escolhida não está mais disponível (outra venda a "
                        "reivindicou, ou ela mudou). Escolha de novo."
                    )
                )
        elif escolha == "NOVA" or not candidatos:
            farm = self._fazenda_da_linha(row, batch, fazendas)
            if farm is None:
                texto = readers.texto_da_celula(raw.get("fazenda")) or "(vazio)"
                mensagens.append(
                    pendencia(f'Fazenda "{texto}" não cadastrada.', "farm")
                )
            lote_id = row.resolution.get("lot")
            lote = Lot.objects.filter(pk=lote_id).first() if lote_id else None
            if farm is not None and lote is None:
                legado = self._lote_legado(farm)
                sugestao = (
                    {
                        "valor": legado.pk,
                        "rotulo": legado.code,
                        "motivo": "o lote 'saldo anterior' da planilha nesta fazenda",
                    }
                    if legado
                    else None
                )
                mensagens.append(
                    pendencia(
                        "Esta venda vai criar uma saída nova: escolha de qual lote "
                        "saem as cabeças.",
                        "lot",
                        sugestao,
                    )
                )
        else:  # há candidato(s) e o usuário ainda não decidiu
            primeiro = candidatos[0]
            sugestao = (
                {
                    "valor": primeiro.pk,
                    "rotulo": SUGESTAO_ROTULO,
                    "motivo": SUGESTAO_MOTIVO,
                    "detalhe": self._rotulo_do_movimento(primeiro),
                }
                if len(candidatos) == 1
                else None
            )
            mensagens.append(
                pendencia(
                    "Esta venda parece ser uma saída que a aba da fazenda já registrou "
                    f"({'; '.join(self._rotulo_do_movimento(m) for m in candidatos)}). "
                    "Vincule-a — ou crie uma saída nova, o que debitaria as cabeças de novo.",
                    "movement",
                    sugestao,
                )
            )

        if movimento is not None:
            usados.add(movimento.pk)
            farm, lote = movimento.origin_farm, movimento.origin_lot
            categoria = movimento.origin_category
            if (
                movimento.total_weight_kg is not None
                and peso is not None
                and movimento.total_weight_kg != peso
            ):
                mensagens.append(
                    aviso(
                        f"O peso da venda ({numero_br(peso, 0)} kg) difere do da saída "
                        f"{movimento.code} ({numero_br(movimento.total_weight_kg, 0)} kg). "
                        "O movimento não é alterado — pendência #12."
                    )
                )
            if movimento.date != data and data:
                mensagens.append(
                    aviso(
                        f"A venda é de {data:%d/%m/%Y}; a saída {movimento.code} é de "
                        f"{movimento.date:%d/%m/%Y}. O razão mantém a data da saída."
                    )
                )

        season = None
        if data is not None:
            season = self.safra_da_data(data)
            if season is None:
                mensagens.append(
                    erro(f"Não há safra cadastrada que cubra {data:%d/%m/%Y}.", "date")
                )
            elif (
                season.status == SeasonStatus.ENCERRADA
                and not pode_lancar_em_safra_encerrada(batch.created_by)
            ):
                mensagens.append(
                    erro(
                        f"A safra {season.name} está encerrada: só o administrador importa nela.",
                        "date",
                    )
                )

        if data and valor and categoria and cabecas:
            existente = Sale.objects.filter(
                status=Status.CONFIRMADA,
                date=data,
                category=categoria,
                head_count=cabecas,
                total_value=valor,
            ).first()
            if existente:
                mensagens.append(
                    aviso(
                        f"Parece a venda {existente.code}, já lançada (mesma data, "
                        "categoria, cabeças e valor)."
                    )
                )

        if cabecas and peso and valor:
            indicadores = carcass.calcular_carcaca(
                head_count=cabecas,
                total_weight_kg=peso,
                total_value=valor,
                carcass_weight_kg=carcaca,
            )
            for texto in self._comparar_com_a_planilha(raw, indicadores):
                mensagens.append({**aviso(texto), "divergencia": True})
            mensagens.extend(
                {**aviso(t), "divergencia": False}
                for t in carcass.alertas_de_rendimento(indicadores.rendimento)
            )

        return (
            {
                "date": data,
                "type": tipo,
                "head_count": cabecas,
                "total_weight_kg": peso,
                "carcass_weight_kg": carcaca,
                "total_value": valor,
                "category": categoria,
                "farm": farm,
                "lot": lote,
                "movement": movimento,
                "decisao_comprador": decisao,
                "sale_form": forma,
                "partnership": readers.texto_da_celula(raw.get("parceria")),
                "candidatos": candidatos,
            },
            mensagens,
        )

    def _ctx(self):
        return {
            "fazendas": self._fazendas(),
            "categorias": self._categorias(),
            "usados": set(),
        }

    def _ordenadas(self, linhas):
        """Mesma ordem na prévia e na importação, para a saída ser
        reivindicada pela mesma linha nas duas."""
        return sorted(
            linhas,
            key=lambda r: (
                readers.data_da_celula(r.resolution.get("date", r.raw.get("data")))
                or datetime.date.min,
                r.row_number,
            ),
        )

    def validar(self, batch):
        ctx = self._ctx()
        linhas = self._ordenadas(linhas_abertas(batch))
        for row in linhas:
            if ignorada_pelo_usuario(row):
                row.messages = [aviso("Ignorada por decisão do usuário.")]
                row.status = RowStatus.IGNORADA
                continue
            _, mensagens = self._interpretar(row, batch, ctx)
            row.messages = mensagens
            row.status = status_pelas_mensagens(mensagens)
        salvar_validacao(linhas)

    def avisos_do_lote(self, batch) -> list[str]:
        divergencias = [
            (r.row_number, m["texto"])
            for r in batch.rows.exclude(status=RowStatus.IGNORADA)
            for m in r.messages
            if m.get("divergencia")
        ]
        if not divergencias:
            return []
        return [
            f"{len(divergencias)} divergência(s) entre a planilha e o cálculo — "
            + " · ".join(f"linha {n}: {t}" for n, t in divergencias[:4])
        ]

    # ---- decisões ---------------------------------------------------------

    def campos_da_linha(self, row, batch):
        campos = []
        categorias = [
            (c.pk, c.name) for c in AnimalCategory.objects.filter(is_active=True)
        ]
        for m in row.pendencias:
            campo, atual = m["campo"], str(row.resolution.get(m["campo"], ""))
            sugestao = m.get("sugestao") or {}
            if campo == "movement":
                ctx = self._ctx()
                dados, _ = self._interpretar(row, batch, ctx)
                opcoes = [
                    (c.pk, self._rotulo_do_movimento(c)) for c in dados["candidatos"]
                ]
                opcoes.append(
                    ("NOVA", "Nenhuma delas: criar uma saída nova (debita de novo)")
                )
                campos.append(
                    Campo(
                        campo,
                        "Esta venda é a saída…",
                        "select",
                        opcoes,
                        atual,
                        sugestao.get("detalhe", ""),
                    )
                )
            elif campo == "lot":
                dados, _ = self._interpretar(row, batch, self._ctx())
                farm = dados["farm"]
                lotes = (
                    [
                        (lote.pk, lote.code)
                        for lote in Lot.objects.filter(farm=farm).exclude(
                            status=LotStatus.EXCLUIDO
                        )
                    ]
                    if farm
                    else []
                )
                campos.append(
                    Campo(
                        campo,
                        "Lote de saída",
                        "select",
                        lotes,
                        atual,
                        sugestao.get("rotulo", ""),
                    )
                )
            elif campo == "farm":
                campos.append(
                    Campo(
                        campo,
                        "Fazenda",
                        "select",
                        [(f.pk, f.name) for f in Farm.objects.filter(is_active=True)],
                        atual,
                    )
                )
            elif campo == "category":
                campos.append(Campo(campo, "Categoria", "select", categorias, atual))
            elif campo == "type":
                campos.append(
                    Campo(
                        campo,
                        "Tipo",
                        "select",
                        [("abate", "Abate"), ("venda", "Venda de animal vivo")],
                        atual,
                    )
                )
            elif campo == "sale_form":
                campos.append(
                    Campo(campo, "Forma", "select", list(SaleForm.choices), atual)
                )
            elif campo == "date":
                campos.append(Campo(campo, "Data", "data", valor=atual))
            elif campo in ("head_count", "total_weight_kg", "total_value"):
                rotulos = {
                    "head_count": "Cabeças",
                    "total_weight_kg": "Peso vivo (kg)",
                    "total_value": "Valor total (R$)",
                }
                campos.append(Campo(campo, rotulos[campo], "numero", valor=atual))
        if campos or ignorada_pelo_usuario(row):
            campos.append(
                Campo(
                    "acao",
                    "Ou, se não é uma venda",
                    "select",
                    [ACAO_IGNORAR],
                    str(row.resolution.get("acao", "")),
                )
            )
        return campos

    def grupos_de_sugestao(self, batch) -> list[GrupoDeSugestao]:
        linhas = 0
        total = Decimal("0")
        for row in batch.rows.filter(status=RowStatus.PENDENTE):
            for m in row.pendencias:
                if (
                    m["campo"] == "movement"
                    and m.get("sugestao")
                    and "movement" not in row.resolution
                ):
                    linhas += 1
                    total += readers.decimal_da_celula(
                        row.raw.get("valor_total")
                    ) or Decimal("0")
        if not linhas:
            return []
        return [
            GrupoDeSugestao(
                f"movement|{SUGESTAO_ROTULO}|{SUGESTAO_MOTIVO}",
                "movement",
                "",
                f"vincular cada venda a {SUGESTAO_ROTULO}",
                SUGESTAO_MOTIVO + ". Evita debitar as mesmas cabeças duas vezes.",
                linhas,
                total,
            )
        ]

    def aplicar_grupo(self, batch, chave: str) -> int:
        alterar = []
        for row in batch.rows.filter(status=RowStatus.PENDENTE):
            for m in row.pendencias:
                sug = m.get("sugestao")
                if (
                    m["campo"] == "movement"
                    and sug
                    and "movement" not in row.resolution
                    and chave == f"movement|{sug['rotulo']}|{sug['motivo']}"
                ):
                    row.resolution = {**row.resolution, "movement": sug["valor"]}
                    alterar.append(row)
        ImportRow.objects.bulk_update(alterar, ["resolution"])
        return len(alterar)

    # ---- importação -----------------------------------------------------

    def _comprador(self, decisao: dict, texto: str) -> Partner:
        """Vincula ou cria o parceiro e **garante o papel** escolhido — o
        `COPERFRIGU` que a importação de movimentações cria não tem papel
        nenhum, e a venda exige Frigorífico ou Comprador."""
        parceiro = (
            Partner.objects.filter(pk=decisao["partner_id"]).first()
            if decisao.get("partner_id")
            else None
        )
        if parceiro is None:
            parceiro = Partner.objects.filter(
                name=texto
            ).first() or Partner.objects.create(name=texto)
        PartnerRole.objects.get_or_create(partner=parceiro, role=decisao["role"])
        return parceiro

    def importar(self, batch, usuario) -> dict:
        ctx = self._ctx()
        tipo = ContentType.objects.get_for_model(Sale)
        importadas, cabecas, total, vinculadas = 0, 0, Decimal("0"), 0

        prontas = self._ordenadas(batch.rows.filter(status=RowStatus.VALIDA))
        for row in prontas:
            dados, _ = self._interpretar(row, batch, ctx)
            nota = f"Importada da planilha, linha {row.row_number}."
            fazenda_planilha = readers.texto_da_celula(row.raw.get("fazenda"))
            if fazenda_planilha:
                nota += f" Fazenda na planilha: {fazenda_planilha}."
            if dados["movement"]:
                nota += f" Vinculada à saída {dados['movement'].code}."
            try:
                comprador = self._comprador(
                    dados["decisao_comprador"],
                    readers.texto_da_celula(row.raw.get("comprador")),
                )
                venda = services.criar_venda(
                    usuario=usuario,
                    date=dados["date"],
                    type=dados["type"],
                    buyer=comprador,
                    farm=dados["farm"],
                    lot=dados["lot"],
                    category=dados["category"],
                    head_count=dados["head_count"],
                    total_weight_kg=dados["total_weight_kg"],
                    carcass_weight_kg=dados["carcass_weight_kg"],
                    total_value=dados["total_value"],
                    sale_form=dados["sale_form"],
                    partnership=dados["partnership"],
                    notes=nota,
                )
                if dados["movement"]:
                    services.vincular_a_saida_existente(
                        venda, dados["movement"], usuario=usuario
                    )
                    vinculadas += 1
                venda = services.confirmar_venda(
                    venda, usuario=usuario, gerar_titulos=False
                )
            except BusinessError as exc:
                raise ImportacaoFalhou(
                    f"Linha {row.row_number} da aba {row.sheet}: {exc}"
                ) from exc
            row.status = RowStatus.IMPORTADA
            row.target_type, row.target_id = tipo, venda.pk
            row.save(update_fields=["status", "target_type", "target_id"])
            importadas += 1
            cabecas += venda.head_count
            total += venda.total_value
        return {
            "importadas": importadas,
            "cabecas": cabecas,
            "total": total,
            "vinculadas": vinculadas,
        }
