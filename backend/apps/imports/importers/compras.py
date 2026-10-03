"""F2-11 — importador de COMPRA DE GADO: 13 compras, 954 cabeças,
R$ 2.457.752,15.

`MÉDIA/CAB` é derivada (com `#DIV/0!`) e nem é lida. Cada compra vira uma
compra `CONFIRMADA` com seu lote, a entrada no rebanho e os custos — pelo
mesmo caminho da tela, sem digitação dupla.

"BEZERROS" mapeia para `Machos Desm. até 12m` — **a confirmar com o
produtor**: o mapeamento só vale depois que o usuário o confirma nas opções.
"""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from apps.core.exceptions import BusinessError
from apps.core.reversible import Status
from apps.herd.permissions import pode_lancar_em_safra_encerrada
from apps.imports import readers
from apps.imports.importers.base import (
    ACAO_IGNORAR,
    Campo,
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
from apps.livestock.models import AnimalCategory
from apps.organizations.models import SeasonStatus
from apps.properties.models import Farm
from apps.purchases import services as compras
from apps.purchases.models import Purchase

#: O que a planilha chama de "BEZERROS" e o produtor ainda precisa confirmar.
SUGESTAO_BEZERROS = "Machos Desm. até 12m"


class ImportadorDeCompras(Importador):
    kind = ImportKind.COMPRAS

    def ler(self, workbook):
        return readers.ler_compras(workbook)

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

    def _fazenda_da_linha(self, row, batch, fazendas):
        if "destination_farm" in row.resolution:
            return Farm.objects.filter(pk=row.resolution["destination_farm"]).first()
        texto = readers.texto_da_celula(row.raw.get("fazenda"))
        mapeada = (batch.options.get("farm_map") or {}).get(readers.normalizar(texto))
        if mapeada:
            return Farm.objects.filter(pk=mapeada).first()
        return fazendas.get(readers.normalizar(texto))

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

    def textos_de_categoria(self, batch) -> list[str]:
        """Textos de categoria da planilha, para o mapeamento nas opções."""
        textos = {
            readers.texto_da_celula(r.raw.get("categoria")) for r in batch.rows.all()
        }
        return sorted(t for t in textos if t)

    def textos_de_fazenda(self, batch) -> list[str]:
        textos = {
            readers.texto_da_celula(r.raw.get("fazenda")) for r in batch.rows.all()
        }
        return sorted(t for t in textos if t)

    def descrever(self, row):
        raw = row.raw
        data = readers.data_da_celula(raw.get("data"))
        return " · ".join(
            [
                f"{data:%d/%m/%Y}" if data else "sem data",
                f"{readers.texto_da_celula(raw.get('quantidade')) or '?'} cabeças",
                readers.texto_da_celula(raw.get("categoria")) or "sem categoria",
                readers.texto_da_celula(raw.get("fazenda")) or "sem fazenda",
            ]
        )

    # ---- validação ------------------------------------------------------

    def _interpretar(self, row: ImportRow, batch, fazendas, categorias):
        raw, mensagens = row.raw, []

        data = (
            readers.data_da_celula(row.resolution["date"])
            if "date" in row.resolution
            else readers.data_da_celula(raw.get("data"))
        )
        if data is None:
            mensagens.append(pendencia("Data inválida ou vazia.", "date"))

        cabecas = readers.inteiro_da_celula(
            row.resolution.get("head_count", raw.get("quantidade"))
        )
        if cabecas is None or cabecas <= 0:
            mensagens.append(
                pendencia("Quantidade de cabeças ausente ou inválida.", "head_count")
            )

        valor = readers.decimal_da_celula(
            row.resolution.get("animal_value", raw.get("valor"))
        )
        if valor is None or valor <= 0:
            mensagens.append(
                pendencia("Valor da compra ausente ou inválido.", "animal_value")
            )

        fazenda = self._fazenda_da_linha(row, batch, fazendas)
        if fazenda is None:
            texto = readers.texto_da_celula(raw.get("fazenda")) or "(vazio)"
            mensagens.append(
                pendencia(f'Fazenda "{texto}" não cadastrada.', "destination_farm")
            )

        categoria = self._categoria_da_linha(row, batch, categorias)
        if categoria is None:
            texto = readers.texto_da_celula(raw.get("categoria")) or "(vazio)"
            sugestao = None
            alvo = categorias.get(readers.normalizar(SUGESTAO_BEZERROS))
            if readers.normalizar(texto) == "bezerros" and alvo:
                sugestao = {
                    "valor": alvo.pk,
                    "rotulo": alvo.name,
                    "motivo": "a confirmar com o produtor",
                }
            mensagens.append(
                pendencia(
                    f'Categoria "{texto}" sem mapeamento — confirme nas opções.',
                    "category",
                    sugestao,
                )
            )

        acessorios = {}
        for chave, rotulo in (
            ("frete", "frete"),
            ("comissao", "comissão"),
            ("impostos", "impostos"),
        ):
            bruto = raw.get(chave)
            if readers.eh_erro_de_celula(bruto):
                mensagens.append(
                    aviso(
                        f"{rotulo.capitalize()} com erro de célula ({bruto['erro']}) — tratado como zero."
                    )
                )
            acessorios[chave] = readers.decimal_da_celula(bruto) or Decimal("0")

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

        if data and fazenda and categoria and cabecas and valor:
            duplicada = Purchase.objects.filter(
                status=Status.CONFIRMADA,
                date=data,
                destination_farm=fazenda,
                category=categoria,
                head_count=cabecas,
                animal_value=valor,
            ).first()
            if duplicada:
                mensagens.append(
                    aviso(
                        f"Parece a compra {duplicada.code}, já lançada (mesma data, fazenda, categoria, cabeças e valor)."
                    )
                )

        parceria = readers.texto_da_celula(raw.get("parceria"))
        observacoes = " · ".join(
            x for x in (readers.texto_da_celula(raw.get("observacoes")),) if x
        )
        return (
            {
                "date": data,
                "head_count": cabecas,
                "animal_value": valor,
                "destination_farm": fazenda,
                "category": categoria,
                "freight_value": acessorios["frete"],
                "commission_value": acessorios["comissao"],
                "tax_value": acessorios["impostos"],
                "partnership": parceria,
                "notes": observacoes,
            },
            mensagens,
        )

    def validar(self, batch):
        fazendas, categorias = self._fazendas(), self._categorias()
        linhas = list(linhas_abertas(batch))
        for row in linhas:
            if ignorada_pelo_usuario(row):
                row.messages = [aviso("Ignorada por decisão do usuário.")]
                row.status = RowStatus.IGNORADA
                continue
            _, mensagens = self._interpretar(row, batch, fazendas, categorias)
            row.messages = mensagens
            row.status = status_pelas_mensagens(mensagens)
        salvar_validacao(linhas)

    def campos_da_linha(self, row, batch):
        campos = []
        fazendas = [(f.pk, f.name) for f in Farm.objects.filter(is_active=True)]
        categorias = [
            (c.pk, c.name) for c in AnimalCategory.objects.filter(is_active=True)
        ]
        for m in row.pendencias:
            campo, atual = m["campo"], str(row.resolution.get(m["campo"], ""))
            if campo == "destination_farm":
                campos.append(
                    Campo(campo, "Fazenda de destino", "select", fazendas, atual)
                )
            elif campo == "category":
                campos.append(
                    Campo(
                        campo,
                        "Categoria",
                        "select",
                        categorias,
                        atual,
                        (m.get("sugestao") or {}).get("rotulo", ""),
                    )
                )
            elif campo == "date":
                campos.append(Campo(campo, "Data", "data", valor=atual))
            elif campo == "head_count":
                campos.append(Campo(campo, "Cabeças", "numero", valor=atual))
            elif campo == "animal_value":
                campos.append(
                    Campo(campo, "Valor dos animais (R$)", "numero", valor=atual)
                )
        if campos or ignorada_pelo_usuario(row):
            campos.append(
                Campo(
                    "acao",
                    "Ou, se não é uma compra",
                    "select",
                    [ACAO_IGNORAR],
                    str(row.resolution.get("acao", "")),
                )
            )
        return campos

    # ---- importação -----------------------------------------------------

    def importar(self, batch, usuario) -> dict:
        fazendas, categorias = self._fazendas(), self._categorias()
        tipo = ContentType.objects.get_for_model(Purchase)
        importadas, cabecas, total = 0, 0, Decimal("0")

        for row in batch.rows.filter(status=RowStatus.VALIDA).order_by("row_number"):
            dados, _ = self._interpretar(row, batch, fazendas, categorias)
            notas = f"Importada da planilha, linha {row.row_number}."
            if dados["notes"]:
                notas += " " + dados["notes"]
            try:
                compra = compras.criar_compra(
                    usuario=usuario,
                    **{**dados, "notes": notas, "seller": None, "lot": None},
                )
                compras.confirmar_compra(compra, usuario=usuario, gerar_titulos=False)
            except BusinessError as exc:
                raise ImportacaoFalhou(
                    f"Linha {row.row_number} da aba {row.sheet}: {exc}"
                ) from exc
            row.status = RowStatus.IMPORTADA
            row.target_type, row.target_id = tipo, compra.pk
            row.save(update_fields=["status", "target_type", "target_id"])
            importadas += 1
            cabecas += compra.head_count
            total += compra.animal_value
        return {"importadas": importadas, "cabecas": cabecas, "total": total}
