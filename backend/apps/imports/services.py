"""Escrita. O fluxo de importação:

    UPLOAD → STAGING → LEITURA → VALIDAÇÃO → PRÉVIA → ERROS POR LINHA
                                                          ↓
                                      IMPORTAÇÃO ← CONFIRMAÇÃO DO USUÁRIO

Nunca direto para as tabelas finais. Tudo numa transação: falhou no meio,
nada entrou. `file_hash` impede reimportar o mesmo arquivo sem confirmação.
Ver docs/migracao/01-planilhas-e-importacao.md.
"""

import hashlib
from collections import Counter
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.exceptions import BusinessError
from apps.imports import readers
from apps.imports.importers.base import ImportacaoFalhou, Importador
from apps.imports.importers.compras import ImportadorDeCompras
from apps.imports.importers.custos import ImportadorDeCustos
from apps.imports.importers.movimentacoes import ImportadorDeMovimentacoes
from apps.imports.importers.pesagens import ImportadorDePesagens
from apps.imports.importers.vendas import ImportadorDeVendas
from apps.imports.models import (
    BatchStatus,
    ImportBatch,
    ImportKind,
    ImportRow,
    RowStatus,
)
from apps.imports.permissions import pode_importar

IMPORTADORES: dict[str, type[Importador]] = {
    ImportKind.CUSTOS: ImportadorDeCustos,
    ImportKind.COMPRAS: ImportadorDeCompras,
    ImportKind.MOVIMENTACOES: ImportadorDeMovimentacoes,
    ImportKind.VENDAS: ImportadorDeVendas,
    ImportKind.PESAGENS: ImportadorDePesagens,
}

TAMANHO_MAXIMO = 20 * 1024 * 1024  # 20 MB — a planilha real tem ~1 MB
ASSINATURA_XLSX = b"PK\x03\x04"  # .xlsx é um zip


class ImportacaoDuplicada(BusinessError):
    """O mesmo arquivo já foi importado. Reimportar exige confirmação."""

    def __init__(self, anterior: ImportBatch):
        self.anterior = anterior
        super().__init__(
            f"Este arquivo já foi importado em {timezone.localtime(anterior.finished_at):%d/%m/%Y %H:%M} "
            "(mesmo conteúdo). Importar de novo duplica os registros. Se é isso "
            "mesmo que você quer, confirme a reimportação."
        )


def importador_de(batch: ImportBatch) -> Importador:
    return IMPORTADORES[batch.kind]()


def _hash(arquivo) -> str:
    sha = hashlib.sha256()
    arquivo.seek(0)
    for pedaco in iter(lambda: arquivo.read(1024 * 1024), b""):
        sha.update(pedaco)
    arquivo.seek(0)
    return sha.hexdigest()


def _checar_arquivo(arquivo) -> None:
    """Validação no servidor: extensão, tamanho e assinatura do zip."""
    nome = (arquivo.name or "").lower()
    if not nome.endswith(".xlsx"):
        raise BusinessError("Envie uma planilha Excel no formato .xlsx.")
    if arquivo.size > TAMANHO_MAXIMO:
        raise BusinessError(
            f"O arquivo tem {arquivo.size // (1024 * 1024)} MB; o limite é "
            f"{TAMANHO_MAXIMO // (1024 * 1024)} MB."
        )
    arquivo.seek(0)
    if arquivo.read(4) != ASSINATURA_XLSX:
        raise BusinessError("Este arquivo não é uma planilha .xlsx válida.")
    arquivo.seek(0)


def _auditar(batch, action, *, usuario, reason="", **extra):
    registrar_auditoria(
        action=action,
        entity=batch,
        after={
            "kind": batch.kind,
            "original_name": batch.original_name,
            "file_hash": batch.file_hash,
            "status": batch.status,
            "options": batch.options,
            **extra,
        },
        reason=reason,
        actor=usuario,
    )


def criar_importacao(
    *, kind, arquivo, usuario, confirmar_reimportacao: bool = False
) -> ImportBatch:
    """UPLOAD → STAGING → LEITURA → VALIDAÇÃO → PRÉVIA. Nada vai para as
    tabelas finais: só `ImportBatch` e `ImportRow`."""
    if not pode_importar(usuario):
        raise BusinessError("Você não tem permissão para importar planilhas.")
    if kind not in IMPORTADORES:
        raise BusinessError("Tipo de importação desconhecido.")
    _checar_arquivo(arquivo)

    file_hash = _hash(arquivo)
    anterior = (
        ImportBatch.objects.filter(
            kind=kind, file_hash=file_hash, status=BatchStatus.IMPORTADO
        )
        .order_by("-finished_at")
        .first()
    )
    if anterior is not None and not confirmar_reimportacao:
        raise ImportacaoDuplicada(anterior)

    importador = IMPORTADORES[kind]()
    workbook = readers.abrir_planilha(arquivo)
    try:
        leitura = importador.ler(workbook)
    except readers.PlanilhaInvalida as exc:
        raise BusinessError(str(exc)) from exc
    finally:
        workbook.close()
    arquivo.seek(0)

    with transaction.atomic():
        batch = ImportBatch(
            kind=kind,
            original_name=arquivo.name[:255],
            file_hash=file_hash,
            read_stats=leitura.stats,
            duplicate_confirmed=anterior is not None,
            created_by=usuario,
        )
        batch.file.save(arquivo.name, arquivo, save=False)
        batch.save()
        ImportRow.objects.bulk_create(
            [
                ImportRow(
                    batch=batch, sheet=lin.sheet, row_number=lin.row_number, raw=lin.raw
                )
                for lin in leitura.linhas
            ],
            batch_size=500,
        )
        importador.validar(batch)
        _auditar(batch, AuditAction.CREATE, usuario=usuario)
    return batch


def _batch_aberto(batch: ImportBatch, usuario) -> ImportBatch:
    if not pode_importar(usuario):
        raise BusinessError("Você não tem permissão para importar planilhas.")
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != BatchStatus.PREVIA:
        raise BusinessError(
            f"Esta importação está {batch.get_status_display().lower()} — "
            "não dá mais para alterá-la."
        )
    return batch


@transaction.atomic
def salvar_opcoes(batch: ImportBatch, opcoes: dict, *, usuario) -> ImportBatch:
    """Guarda as escolhas do usuário e revalida — "Corrigir e revalidar"."""
    batch = _batch_aberto(batch, usuario)
    batch.options = {**batch.options, **opcoes}
    batch.save(update_fields=["options"])
    importador_de(batch).validar(batch)
    return batch


@transaction.atomic
def salvar_decisoes(
    batch: ImportBatch, decisoes: dict[int, dict], grupos: list[str], *, usuario
) -> ImportBatch:
    """Decisões do usuário linha a linha (e por grupo de sugestão), depois
    revalida. O sistema nunca preenche decisão sozinho."""
    batch = _batch_aberto(batch, usuario)
    importador = importador_de(batch)
    for chave in grupos:
        importador.aplicar_grupo(batch, chave)

    linhas = {
        r.pk: r
        for r in batch.rows.filter(pk__in=decisoes).exclude(status=RowStatus.IMPORTADA)
    }
    alteradas = []
    for pk, campos in decisoes.items():
        row = linhas.get(pk)
        if row is None:
            continue
        resolucao = dict(row.resolution)
        for campo, valor in campos.items():
            if valor in (None, ""):
                resolucao.pop(campo, None)
            else:
                resolucao[campo] = valor
        if resolucao != row.resolution:
            row.resolution = resolucao
            alteradas.append(row)
    ImportRow.objects.bulk_update(alteradas, ["resolution"])
    importador.validar(batch)
    return batch


@transaction.atomic
def cancelar_importacao(batch: ImportBatch, *, usuario) -> ImportBatch:
    """Cancelar não deixa resíduo: nada além do próprio lote de importação
    (que fica, para a auditoria) foi gravado."""
    batch = _batch_aberto(batch, usuario)
    batch.status = BatchStatus.CANCELADO
    batch.finished_at = timezone.now()
    batch.finished_by = usuario
    batch.save(update_fields=["status", "finished_at", "finished_by"])
    _auditar(
        batch,
        AuditAction.CANCEL,
        usuario=usuario,
        reason="Importação cancelada na prévia.",
    )
    return batch


def resumo_da_previa(batch: ImportBatch) -> dict:
    contagem = Counter(batch.rows.values_list("status", flat=True))
    importador = importador_de(batch)
    return {
        "lidas": batch.read_stats.get("lidas"),
        "em_branco": batch.read_stats.get("em_branco"),
        "prontas": contagem[RowStatus.VALIDA],
        "pendentes": contagem[RowStatus.PENDENTE],
        "erros": contagem[RowStatus.ERRO],
        "ignoradas": contagem[RowStatus.IGNORADA],
        "importadas": contagem[RowStatus.IMPORTADA],
        "problemas": importador.problemas_de_configuracao(batch),
        "avisos": importador.avisos_do_lote(batch),
    }


def importar(batch: ImportBatch, *, usuario) -> dict:
    """PRÉVIA → IMPORTAÇÃO, tudo ou nada.

    A transação cobre todas as linhas: se uma falhar, nada entra, o lote
    fica como `FALHOU` (em transação própria, depois do desfazer) com a
    linha e o motivo.
    """
    try:
        return _importar_em_transacao(batch, usuario)
    except ImportacaoFalhou as exc:
        with transaction.atomic():
            ImportBatch.objects.filter(pk=batch.pk).update(failure_message=str(exc))
        raise


@transaction.atomic
def _importar_em_transacao(batch: ImportBatch, usuario) -> dict:
    batch = _batch_aberto(batch, usuario)
    importador = importador_de(batch)

    problemas = importador.problemas_de_configuracao(batch)
    if problemas:
        raise BusinessError(problemas[0])

    # Revalida dentro da transação: o estado do banco pode ter mudado
    # desde que a prévia foi aberta.
    importador.validar(batch)
    prontas = batch.rows.filter(status=RowStatus.VALIDA).count()
    if not prontas:
        raise BusinessError(
            "Não há nenhuma linha pronta para importar. Resolva as pendências "
            "ou corrija os erros listados na prévia."
        )

    resultado = importador.importar(batch, usuario)

    batch.status = BatchStatus.IMPORTADO
    batch.finished_at = timezone.now()
    batch.finished_by = usuario
    batch.failure_message = ""
    batch.save(
        update_fields=["status", "finished_at", "finished_by", "failure_message"]
    )

    pendentes = batch.rows.filter(
        status__in=[RowStatus.PENDENTE, RowStatus.ERRO]
    ).count()
    _auditar(
        batch,
        AuditAction.IMPORT,
        usuario=usuario,
        reason=f"{prontas} linhas importadas; {pendentes} ficaram de fora.",
        resultado={
            k: str(v) if isinstance(v, Decimal) else v for k, v in resultado.items()
        },
    )
    return {**resultado, "pendentes_restantes": pendentes}
