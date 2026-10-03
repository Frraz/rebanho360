"""Contrato de um importador e utilidades comuns.

Cada importador sabe: **ler** a planilha, **validar** as linhas (sem gravar
nada fora de `ImportRow`), dizer o que o usuário ainda precisa decidir, e
**importar** as linhas prontas — tudo ou nada.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.exceptions import BusinessError
from apps.imports.models import ImportBatch, ImportRow, RowStatus


class ImportacaoFalhou(BusinessError):
    """Falha ao importar. A transação inteira é desfeita: nada entrou."""


def erro(texto: str, campo: str | None = None) -> dict:
    return {"nivel": "erro", "campo": campo, "texto": texto}


def pendencia(
    texto: str, campo: str | None = None, sugestao: dict | None = None
) -> dict:
    mensagem = {"nivel": "pendencia", "campo": campo, "texto": texto}
    if sugestao:
        mensagem["sugestao"] = sugestao
    return mensagem


def aviso(texto: str, campo: str | None = None) -> dict:
    return {"nivel": "aviso", "campo": campo, "texto": texto}


def status_pelas_mensagens(mensagens: list[dict]) -> str:
    niveis = {m["nivel"] for m in mensagens}
    if "erro" in niveis:
        return RowStatus.ERRO
    if "pendencia" in niveis:
        return RowStatus.PENDENTE
    return RowStatus.VALIDA


@dataclass
class Campo:
    """Um campo que o usuário pode preencher para destravar uma linha."""

    nome: str
    rotulo: str
    tipo: str  # "select" | "texto" | "data" | "numero"
    opcoes: list = field(default_factory=list)  # [(valor, rótulo)]
    valor: str = ""
    sugestao: str = ""


@dataclass
class GrupoDeSugestao:
    """Linhas pendentes que o sistema sugere classificar do mesmo jeito —
    o usuário aceita o grupo inteiro de uma vez (ou não)."""

    chave: str
    campo: str
    valor: str
    rotulo: str
    motivo: str
    linhas: int
    total: Decimal | None = None


class Importador:
    kind: str = ""

    def __init__(self):
        self._safras: dict = {}

    def safra_da_data(self, data):
        """`season_para_data` com cache por importador: a prévia consulta a
        mesma data em centenas de linhas."""
        from apps.herd.services import season_para_data

        if data not in self._safras:
            self._safras[data] = season_para_data(data)
        return self._safras[data]

    # --- leitura -----------------------------------------------------------
    def ler(self, workbook):
        raise NotImplementedError

    # --- validação ---------------------------------------------------------
    def validar(self, batch: ImportBatch) -> None:
        """Recalcula status e mensagens de todas as linhas ainda abertas.
        Só escreve em `ImportRow`."""
        raise NotImplementedError

    def problemas_de_configuracao(self, batch: ImportBatch) -> list[str]:
        """O que falta escolher nas opções antes de poder importar."""
        return []

    def avisos_do_lote(self, batch: ImportBatch) -> list[str]:
        return []

    def campos_da_linha(self, row: ImportRow, batch: ImportBatch) -> list[Campo]:
        return []

    def descrever(self, row: ImportRow) -> str:
        """Uma linha de texto para reconhecer a linha da planilha na tela."""
        partes = [
            str(v)
            for v in row.raw.values()
            if v not in (None, "") and not isinstance(v, dict)
        ]
        return " · ".join(partes)

    def grupos_de_sugestao(self, batch: ImportBatch) -> list[GrupoDeSugestao]:
        return []

    def aplicar_grupo(self, batch: ImportBatch, chave: str) -> int:
        return 0

    # --- importação --------------------------------------------------------
    def importar(self, batch: ImportBatch, usuario) -> dict:
        raise NotImplementedError


def linhas_abertas(batch: ImportBatch):
    """Linhas que ainda podem mudar: nunca a já importada."""
    return batch.rows.exclude(status=RowStatus.IMPORTADA)


def salvar_validacao(linhas: list[ImportRow]) -> None:
    ImportRow.objects.bulk_update(
        linhas, ["status", "messages", "meta"], batch_size=200
    )


ACAO_IGNORAR = ("IGNORAR", "Ignorar esta linha (não importar)")


def ignorada_pelo_usuario(row: ImportRow) -> bool:
    return row.resolution.get("acao") == "IGNORAR"


def valor_da_linha(row: ImportRow, campo: str, padrao=None):
    """A decisão do usuário vence a planilha."""
    return row.resolution.get(campo, padrao)
