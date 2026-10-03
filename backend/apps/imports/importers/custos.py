"""F2-10 — importador de CUSTOS: 235 lançamentos reais, R$ 1.046.907,76.

Sem coluna de fazenda na planilha: a fazenda é escolhida na importação.
Os 106 sem centro (R$ 411.132,64) e os 96 sem descrição **não** são
descartados nem empurrados para "OUTROS": entram como pendência, com
classificação assistida por padrão de texto — sugestão com confirmação
humana, nunca adivinhação silenciosa.
"""

import re
from collections import defaultdict
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from apps.core.exceptions import BusinessError
from apps.costs.models import CostCenter, CostClass, CostEntry
from apps.costs.services import registrar_custo
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
    valor_da_linha,
)
from apps.imports.models import ImportBatch, ImportKind, ImportRow, RowStatus
from apps.organizations.models import SeasonStatus
from apps.partners.models import Partner
from apps.properties.models import Farm

#: Padrões de texto → centro de custo. Ficam sempre como SUGESTÃO: o que a
#: spec nomeou (SALÁRIO, POSTO, COMISSÃO CORRETOR) mais o que a própria aba
#: já faz nas linhas classificadas (PEÇAS/CONSERTO → PARQUE DE MÁQUINAS...).
PADROES_DE_CENTRO = [
    (r"^\s*SAL[ÁA]RIO", "FUNCIONARIO", 'texto começa com "SALÁRIO"'),
    (r"^\s*POSTO\b", "PARQUE DE MÁQUINAS", 'texto começa com "POSTO"'),
    (r"COMISS[ÃA]O\s+CORRETOR", "COMISSÃO", 'texto "COMISSÃO CORRETOR"'),
    (
        r"\bAUTO\s*PE[ÇC]AS\b|\bCONSERTO\b|\bTRATOR\b|\bBATERIA\b",
        "PARQUE DE MÁQUINAS",
        "peças, conserto ou trator",
    ),
    (
        r"^\s*(IR|ITR|IPTU|IPVA)\b|\bIMPOSTO\b|\bTAXA\b",
        "IMPOSTO E TAXAS",
        "imposto ou taxa",
    ),
    (
        r"\bCALC[ÁA]RIO\b|\bSEMENTES?\b|\bHERBICIDA\b|\bADUBO\b",
        "PASTAGEM",
        "insumo de pastagem",
    ),
    (r"\bVACINA\b|\bVERMIF", "SANIDADE", "vacina ou vermífugo"),
    (
        r"\bMANTIMENTOS?\b|\bMERCADO\b",
        "FUNCIONARIO",
        "mantimentos para os funcionários",
    ),
]


def sugerir_centro(item: str) -> tuple[str, str] | None:
    for padrao, centro, motivo in PADROES_DE_CENTRO:
        if re.search(padrao, item or "", flags=re.IGNORECASE):
            return centro, motivo
    return None


class ImportadorDeCustos(Importador):
    kind = ImportKind.CUSTOS

    def ler(self, workbook):
        return readers.ler_custos(workbook)

    # ---- apoio ----------------------------------------------------------

    def _centros(self) -> dict[str, CostCenter]:
        return {
            readers.normalizar(c.name): c
            for c in CostCenter.objects.filter(is_active=True)
        }

    def _classe_da_planilha(self, texto: str) -> CostClass | None:
        norma = readers.normalizar(texto)
        if not norma:
            return None
        nome = (
            "INVESTIMENTO"
            if norma.startswith("invest")
            else ("CUSTEIO" if norma.startswith("custeio") else None)
        )
        return (
            CostClass.objects.filter(name=nome, is_active=True).first()
            if nome
            else None
        )

    def _por_id(self, modelo, valor):
        try:
            return modelo.objects.filter(pk=int(valor)).first()
        except (TypeError, ValueError):
            return None

    def _fazenda(self, batch) -> Farm | None:
        return self._por_id(Farm, batch.options.get("farm_id"))

    def _classe_padrao(self, batch) -> CostClass | None:
        return self._por_id(CostClass, batch.options.get("default_cost_class_id"))

    def descrever(self, row):
        raw = row.raw
        data = readers.data_da_celula(raw.get("data"))
        valor = readers.decimal_da_celula(raw.get("valor"))
        return " · ".join(
            [
                f"{data:%d/%m/%Y}" if data else "sem data",
                readers.texto_da_celula(raw.get("item")) or "sem descrição",
                (
                    f"R$ {valor:,.2f}".replace(",", "X")
                    .replace(".", ",")
                    .replace("X", ".")
                    if valor is not None
                    else "sem valor"
                ),
            ]
        )

    # ---- validação ------------------------------------------------------

    def _interpretar(self, row: ImportRow, batch: ImportBatch, centros, classe_padrao):
        """Devolve `(dados, mensagens)` da linha, com a decisão do usuário
        por cima do que veio da planilha."""
        raw, mensagens = row.raw, []

        data = (
            readers.data_da_celula(row.resolution["date"])
            if "date" in row.resolution
            else readers.data_da_celula(raw.get("data"))
        )
        if data is None:
            motivo = (
                "célula com erro (" + raw["data"]["erro"] + ")"
                if readers.eh_erro_de_celula(raw.get("data"))
                else "célula vazia"
            )
            mensagens.append(pendencia(f"Data inválida: {motivo}.", "date"))

        valor = (
            readers.decimal_da_celula(row.resolution["amount"])
            if "amount" in row.resolution
            else readers.decimal_da_celula(raw.get("valor"))
        )
        if valor is None or valor <= 0:
            motivo = (
                "com " + raw["valor"]["erro"]
                if readers.eh_erro_de_celula(raw.get("valor"))
                else "ausente ou zero"
            )
            mensagens.append(
                pendencia(
                    f"Valor {motivo} — informe o valor, ou ignore a linha (lançamento "
                    "de R$ 0,00 não é importado).",
                    "amount",
                )
            )
            valor = None

        descricao = valor_da_linha(row, "description") or readers.texto_da_celula(
            raw.get("item")
        )
        if not descricao.strip():
            descricao = (batch.options.get("default_description") or "").strip()
        if not descricao:
            mensagens.append(
                pendencia(
                    "Sem descrição — precisa de revisão manual (ou defina uma "
                    "descrição padrão nas opções).",
                    "description",
                )
            )

        centro = None
        if "cost_center" in row.resolution:
            centro = self._por_id(CostCenter, row.resolution["cost_center"])
        else:
            nome = readers.texto_da_celula(raw.get("centro"))
            if nome:
                centro = centros.get(readers.normalizar(nome))
                if centro is None:
                    mensagens.append(
                        pendencia(
                            f'Centro de custo "{nome}" não cadastrado.', "cost_center"
                        )
                    )
        if centro is None and not any(m["campo"] == "cost_center" for m in mensagens):
            sugestao = sugerir_centro(readers.texto_da_celula(raw.get("item")))
            dados_sugestao = None
            if sugestao and readers.normalizar(sugestao[0]) in centros:
                alvo = centros[readers.normalizar(sugestao[0])]
                dados_sugestao = {
                    "valor": alvo.pk,
                    "rotulo": alvo.name,
                    "motivo": sugestao[1],
                }
            mensagens.append(
                pendencia("Sem centro de custo.", "cost_center", dados_sugestao)
            )

        classe = None
        if "cost_class" in row.resolution:
            classe = self._por_id(CostClass, row.resolution["cost_class"])
        else:
            classe = self._classe_da_planilha(
                readers.texto_da_celula(raw.get("classe"))
            )
            if classe is None:
                classe = classe_padrao
                if classe is not None:
                    mensagens.append(
                        aviso(
                            f"Sem classe na planilha — assumida a classe padrão {classe.name}.",
                            "cost_class",
                        )
                    )
        if classe is None:
            mensagens.append(
                pendencia(
                    "Sem classe — escolha a classe padrão nas opções ou classifique a linha.",
                    "cost_class",
                )
            )

        season = None
        if data is not None:
            season = self.safra_da_data(data)
            if season is None:
                mensagens.append(self._data_fora_da_safra(row, data))
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

        return (
            {
                "date": data,
                "amount": valor,
                "description": descricao.strip(),
                "cost_center": centro,
                "cost_class": classe,
                "season": season,
                "payer": readers.texto_da_celula(raw.get("pagador")),
            },
            mensagens,
        )

    def _data_fora_da_safra(self, row: ImportRow, data) -> dict:
        """Data que nenhuma safra cobre. Se a coluna ANO da própria planilha
        aponta o ano certo (30 linhas de `2025-01-03` com ANO 2026), vira
        pendência com SUGESTÃO — o usuário confirma; nunca corrigida em
        silêncio, nunca descartada."""
        ano = readers.inteiro_da_celula(row.raw.get("ano"))
        if ano and ano != data.year and "date" not in row.resolution:
            try:
                corrigida = data.replace(year=ano)
            except ValueError:
                corrigida = None
            if corrigida and self.safra_da_data(corrigida):
                return pendencia(
                    f"A data {data:%d/%m/%Y} está fora de qualquer safra, mas a coluna ANO "
                    f"da planilha diz {ano}. Confirme a data.",
                    "date",
                    {
                        "valor": corrigida.isoformat(),
                        "rotulo": "ano corrigido pela coluna ANO da planilha",
                        "motivo": "a data e a coluna ANO divergem",
                    },
                )
        return erro(
            f"Não há safra cadastrada que cubra {data:%d/%m/%Y}. Cadastre a safra antes, "
            "ou corrija a data.",
            "date",
        )

    def validar(self, batch: ImportBatch) -> None:
        centros, classe_padrao = self._centros(), self._classe_padrao(batch)
        linhas = list(linhas_abertas(batch))
        for row in linhas:
            if ignorada_pelo_usuario(row):
                row.messages = [aviso("Ignorada por decisão do usuário.")]
                row.status = RowStatus.IGNORADA
                continue
            _, mensagens = self._interpretar(row, batch, centros, classe_padrao)
            row.messages = mensagens
            row.status = status_pelas_mensagens(mensagens)
        salvar_validacao(linhas)

    def problemas_de_configuracao(self, batch) -> list[str]:
        problemas = []
        if self._fazenda(batch) is None:
            problemas.append(
                "Escolha a fazenda: a planilha de custos não tem essa coluna."
            )
        return problemas

    def avisos_do_lote(self, batch) -> list[str]:
        avisos = []
        sem_classe = sum(
            1
            for r in batch.rows.all()
            if any(
                m["campo"] == "cost_class" and m["nivel"] == "aviso" for m in r.messages
            )
        )
        if sem_classe:
            classe = self._classe_padrao(batch)
            avisos.append(
                f"{sem_classe} lançamento(s) sem classe na planilha serão importados "
                f"como {classe.name}. Confira nas opções se é isso mesmo."
            )
        return avisos

    # ---- decisões do usuário -------------------------------------------

    def campos_da_linha(self, row, batch):
        campos = []
        centros = [(c.pk, c.name) for c in CostCenter.objects.filter(is_active=True)]
        classes = [(c.pk, c.name) for c in CostClass.objects.filter(is_active=True)]
        for m in row.pendencias:
            campo = m["campo"]
            atual = str(row.resolution.get(campo, ""))
            if campo == "cost_center":
                campos.append(
                    Campo(
                        campo,
                        "Centro de custo",
                        "select",
                        centros,
                        atual,
                        (m.get("sugestao") or {}).get("rotulo", ""),
                    )
                )
            elif campo == "cost_class":
                campos.append(Campo(campo, "Classe", "select", classes, atual))
            elif campo == "description":
                campos.append(Campo(campo, "Descrição", "texto", valor=atual))
            elif campo == "date":
                campos.append(
                    Campo(
                        campo,
                        "Data",
                        "data",
                        valor=atual,
                        sugestao=(m.get("sugestao") or {}).get("valor", ""),
                    )
                )
            elif campo == "amount":
                campos.append(Campo(campo, "Valor (R$)", "numero", valor=atual))
        if campos or ignorada_pelo_usuario(row):
            campos.append(
                Campo(
                    "acao",
                    "Ou, se não é um lançamento",
                    "select",
                    [ACAO_IGNORAR],
                    str(row.resolution.get("acao", "")),
                )
            )
        return campos

    def grupos_de_sugestao(self, batch):
        """Agrupa as pendências que têm sugestão: o usuário aceita o grupo
        inteiro de uma vez (ou decide linha a linha). A chave é
        `campo|rótulo|motivo`; cada linha recebe a SUA sugestão."""
        grupos: dict[tuple, dict] = defaultdict(
            lambda: {"linhas": 0, "total": Decimal("0")}
        )
        for row in batch.rows.filter(status=RowStatus.PENDENTE):
            for m in row.pendencias:
                sug = m.get("sugestao")
                if not sug or m["campo"] in row.resolution:
                    continue
                g = grupos[(m["campo"], sug["rotulo"], sug["motivo"])]
                g["linhas"] += 1
                valor = readers.decimal_da_celula(row.raw.get("valor"))
                if valor:
                    g["total"] += valor
        return [
            GrupoDeSugestao(
                f"{campo}|{rotulo}|{motivo}",
                campo,
                "",
                rotulo,
                motivo,
                g["linhas"],
                g["total"],
            )
            for (campo, rotulo, motivo), g in sorted(
                grupos.items(), key=lambda x: -x[1]["linhas"]
            )
        ]

    def aplicar_grupo(self, batch, chave: str) -> int:
        campo, rotulo, motivo = chave.split("|", 2)
        alterar = []
        for row in batch.rows.filter(status=RowStatus.PENDENTE):
            for m in row.pendencias:
                sug = m.get("sugestao")
                if (
                    m["campo"] == campo
                    and sug
                    and campo not in row.resolution
                    and sug["rotulo"] == rotulo
                    and sug["motivo"] == motivo
                ):
                    valor = sug["valor"]
                    row.resolution = {
                        **row.resolution,
                        campo: int(valor) if campo == "cost_center" else valor,
                    }
                    alterar.append(row)
        ImportRow.objects.bulk_update(alterar, ["resolution"])
        return len(alterar)

    # ---- importação -----------------------------------------------------

    def importar(self, batch, usuario) -> dict:
        farm = self._fazenda(batch)
        centros, classe_padrao = self._centros(), self._classe_padrao(batch)
        pagadores: dict[str, Partner] = {}
        tipo = ContentType.objects.get_for_model(CostEntry)
        importadas, total = 0, Decimal("0")

        for row in batch.rows.filter(status=RowStatus.VALIDA).order_by("row_number"):
            dados, _ = self._interpretar(row, batch, centros, classe_padrao)
            pagador = None
            if dados["payer"]:
                # Pendência #6: quem é "ONODA"? Até responder, vira um
                # parceiro sem papel definido (custo de mudar: um UPDATE).
                pagador = (
                    pagadores.get(dados["payer"])
                    or Partner.objects.filter(name=dados["payer"]).first()
                )
                if pagador is None:
                    pagador = Partner.objects.create(name=dados["payer"])
                pagadores[dados["payer"]] = pagador
            try:
                custo = registrar_custo(
                    date=dados["date"],
                    farm=farm,
                    cost_center=dados["cost_center"],
                    cost_class=dados["cost_class"],
                    amount=dados["amount"],
                    description=dados["description"],
                    payer=pagador,
                    notes=f"Importado da planilha, aba {row.sheet}, linha {row.row_number}.",
                    season=dados["season"],
                    usuario=usuario,
                )
            except BusinessError as exc:
                raise ImportacaoFalhou(
                    f"Linha {row.row_number} da aba {row.sheet}: {exc}"
                ) from exc
            row.status = RowStatus.IMPORTADA
            row.target_type, row.target_id = tipo, custo.pk
            row.save(update_fields=["status", "target_type", "target_id"])
            importadas += 1
            total += custo.amount
        return {"importadas": importadas, "total": total}
