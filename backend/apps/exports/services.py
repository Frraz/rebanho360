"""Pedir, executar e cuidar do ciclo de vida de uma exportação.

`solicitar_exportacao` valida, grava o pedido e põe na fila; quem lê o banco e
escreve os arquivos é `executar_exportacao`, no processador (Celery) — o
navegador nunca espera. O pedido aparece na tela de andamento, que pergunta de
tempos em tempos (HTMX) e entrega o download quando termina.

Três regras que decidem o desenho:

1. **Escopo.** O que sai é sempre o que o usuário já veria na tela, conferido
   de novo **na hora de executar** (o papel dele pode ter mudado entre o pedido
   e o processamento).
2. **Nada incompleto em silêncio.** Se a leitura de um conjunto falha, a
   exportação inteira falha e diz qual — backup que perdeu uma tabela sem
   avisar é pior que backup nenhum. O que é opcional (um relatório, um anexo que
   sumiu do disco) vira aviso e o resto segue.
3. **O arquivo é temporário, o pedido não.** O arquivo expira
   (`EXPORT_RETENTION_DAYS`); o registro do pedido e a auditoria ficam.
"""

import logging
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import context as ctx
from apps.core.exceptions import BusinessError
from apps.exports import catalog, packaging, tabular, writers
from apps.exports.models import (
    STATUS_EM_ANDAMENTO,
    ExportJob,
    ExportStatus,
)
from apps.exports.permissions import pode_exportar
from apps.exports.tabular import TECNICO, Filtros
from apps.imports.permissions import pode_importar
from apps.organizations.models import Season

logger = logging.getLogger(__name__)

FORMATOS = (
    ("csv", "CSV", "Planilha simples; abre em qualquer programa"),
    ("xlsx", "Excel (XLSX)", "Uma pasta de trabalho com uma aba por conjunto"),
    ("json", "JSON", "Valores exatos do banco; o melhor para reimportar"),
    ("pdf", "PDF", "Para ler e imprimir; só as colunas principais"),
)
ESTILOS_DO_CSV = (
    (
        "br",
        "Excel brasileiro",
        "separador ponto e vírgula, vírgula decimal, dd/mm/aaaa",
    ),
    ("intl", "Padrão internacional", "separador vírgula, ponto decimal, aaaa-mm-dd"),
)

#: Quanto "trabalho" vale um relatório pronto ou um anexo, frente a 1 por
#: registro lido. Só serve para a barra de progresso andar de forma honesta.
PESO_DO_RELATORIO = 200
PESO_DO_ANEXO = 20

PASSO_DO_PROGRESSO = 500  # registros entre dois avisos ao banco
INTERVALO_DO_PROGRESSO = 2.0  # segundos

#: Sem sinal de vida por tanto tempo, a manutenção dá a exportação por morta.
INTERROMPIDA_APOS = timedelta(minutes=30)
NA_FILA_APOS = timedelta(hours=24)


class ExportacaoCancelada(Exception):
    """O usuário pediu para parar; sai do laço e limpa o que foi gerado."""


def _retencao() -> timedelta:
    return timedelta(days=getattr(settings, "EXPORT_RETENTION_DAYS", 30))


def _limite_de_ativas() -> int:
    return getattr(settings, "EXPORT_MAX_ACTIVE_PER_USER", 2)


# --------------------------------------------------------------------------
# Pedido
# --------------------------------------------------------------------------


def _em_ordem(chaves, catalogo_ordenado) -> list[str]:
    escolhidas = set(chaves)
    return [k for k in catalogo_ordenado if k in escolhidas]


def _frases_dos_filtros(*, fazenda, safra, de, ate, incluir_excluidos) -> list[str]:
    frases = [
        f"Fazenda: {fazenda.name}" if fazenda else "Todas as fazendas do seu acesso",
        f"Safra: {safra.name}" if safra else "Todas as safras",
    ]
    if de and ate:
        frases.append(f"Período: {de:%d/%m/%Y} a {ate:%d/%m/%Y}")
    elif de:
        frases.append(f"Período: a partir de {de:%d/%m/%Y}")
    elif ate:
        frases.append(f"Período: até {ate:%d/%m/%Y}")
    frases.append(
        "Registros excluídos incluídos"
        if incluir_excluidos
        else "Registros excluídos não incluídos"
    )
    return frases


def solicitar_exportacao(
    *,
    user,
    conjuntos=(),
    relatorios=(),
    formatos=(),
    fazenda=None,
    safra=None,
    de: date | None = None,
    ate: date | None = None,
    incluir_excluidos: bool = False,
    incluir_arquivos: bool = False,
    estilo_csv: str = "br",
) -> ExportJob:
    """Valida o pedido contra o que **este usuário** pode exportar, grava e
    enfileira. Erro de regra vira `BusinessError` com o caminho."""
    if not pode_exportar(user):
        raise PermissionDenied

    disponiveis = {c.chave for c in catalog.conjuntos_para(user)}
    relatorios_disponiveis = {slug for slug, _, _ in catalog.relatorios_para(user)}
    recusados = [k for k in conjuntos if k not in disponiveis]
    if recusados:
        raise BusinessError(
            "Você não tem acesso a estes conjuntos de dados: " + ", ".join(recusados)
        )
    if any(slug not in relatorios_disponiveis for slug in relatorios):
        raise BusinessError(
            "Um dos relatórios escolhidos não está disponível para você."
        )
    formatos_validos = {f for f, _, _ in FORMATOS}
    if any(f not in formatos_validos for f in formatos):
        raise BusinessError("Formato de arquivo desconhecido.")
    if estilo_csv not in {e for e, _, _ in ESTILOS_DO_CSV}:
        raise BusinessError("Estilo de CSV desconhecido.")

    if not (conjuntos or relatorios or incluir_arquivos):
        raise BusinessError(
            "Escolha pelo menos um conjunto de dados, um relatório ou os arquivos anexos."
        )
    if (conjuntos or relatorios) and not formatos:
        raise BusinessError("Escolha pelo menos um formato de arquivo.")
    if de and ate and de > ate:
        raise BusinessError("A data inicial é depois da data final.")
    if (
        fazenda is not None
        and not ctx.available_farms(user).filter(pk=fazenda.pk).exists()
    ):
        raise BusinessError("Essa fazenda não está no seu acesso.")

    ordem_conjuntos = [c.chave for c in catalog.CONJUNTOS]
    ordem_relatorios = [slug for slug, _, _ in catalog.relatorios_para(user)]
    conjuntos = _em_ordem(conjuntos, ordem_conjuntos)
    relatorios = _em_ordem(relatorios, ordem_relatorios)
    formatos = _em_ordem(formatos, [f for f, _, _ in FORMATOS])

    params = {
        "conjuntos": conjuntos,
        "relatorios": relatorios,
        "formatos": formatos,
        "filtros": {
            "fazenda_id": fazenda.pk if fazenda else None,
            "safra_id": safra.pk if safra else None,
            "de": de.isoformat() if de else None,
            "ate": ate.isoformat() if ate else None,
        },
        "opcoes": {
            "incluir_excluidos": bool(incluir_excluidos),
            "incluir_arquivos": bool(incluir_arquivos),
            "csv": estilo_csv,
        },
    }
    por_chave = {c.chave: c for c in catalog.CONJUNTOS}
    titulos_dos_relatorios = {s: t for s, t, _ in catalog.relatorios_para(user)}
    itens = [_item_novo(f"dados:{k}", "dados", por_chave[k].titulo) for k in conjuntos]
    itens += [
        _item_novo(f"relatorio:{s}", "relatorio", titulos_dos_relatorios[s])
        for s in relatorios
    ]
    if incluir_arquivos:
        itens.append(
            _item_novo("anexos", "anexos", "Planilhas importadas e PDFs gerados")
        )

    with transaction.atomic():
        # Trava o usuário: dois cliques juntos não furam o limite de pedidos.
        User.objects.select_for_update().get(pk=user.pk)
        ativas = ExportJob.objects.filter(
            requested_by=user, status__in=STATUS_EM_ANDAMENTO
        ).count()
        if ativas >= _limite_de_ativas():
            raise BusinessError(
                f"Você já tem {ativas} exportações em andamento. Espere uma "
                "terminar, ou cancele uma delas, para pedir outra."
            )
        job = ExportJob.objects.create(
            params=params,
            filters=_frases_dos_filtros(
                fazenda=fazenda,
                safra=safra,
                de=de,
                ate=ate,
                incluir_excluidos=incluir_excluidos,
            ),
            items=itens,
            requested_by=user,
        )
        registrar_auditoria(
            action=AuditAction.EXPORT,
            entity_type="Exportacao",
            entity_id=str(job.job_id),
            reason=(
                f"Pedido: {len(conjuntos)} conjunto(s), {len(relatorios)} relatório(s), "
                f"formatos {', '.join(formatos) or '—'}"
                + (", com arquivos anexos" if incluir_arquivos else "")
                + " · "
                + " · ".join(job.filters)
            ),
            after={"conjuntos": conjuntos, "relatorios": relatorios},
            actor=user,
        )
        transaction.on_commit(lambda: _enfileirar(job.pk))
    return job


def _item_novo(item_id: str, tipo: str, rotulo: str) -> dict:
    return {
        "id": item_id,
        "tipo": tipo,
        "rotulo": rotulo,
        "estado": "pendente",
        "linhas": None,
        "aviso": "",
    }


def _enfileirar(job_pk: int) -> None:
    from apps.exports.tasks import executar

    try:
        executar.delay(job_pk)
    except Exception:  # broker fora do ar: o usuário precisa saber, não esperar
        logger.exception("Não foi possível enfileirar a exportação %s", job_pk)
        ExportJob.objects.filter(pk=job_pk, status=ExportStatus.PENDENTE).update(
            status=ExportStatus.ERRO,
            error=(
                "Não foi possível colocar a exportação na fila. Tente de novo; "
                "se persistir, avise o suporte."
            ),
            finished_at=timezone.now(),
        )


def contagens_para(user) -> dict[str, int | None]:
    """Quantos registros há em cada conjunto dentro do escopo do usuário, para
    a tela mostrar o tamanho do que vai pedir. `None` se a contagem falhar:
    a tela mostra "—" e a exportação continua possível."""
    contagens: dict[str, int | None] = {}
    for conjunto in catalog.conjuntos_para(user):
        try:
            contagens[conjunto.chave] = tabular.contar(conjunto, user, Filtros())
        except Exception:
            logger.exception("Contagem do conjunto %s falhou", conjunto.chave)
            contagens[conjunto.chave] = None
    return contagens


# --------------------------------------------------------------------------
# Execução (no processador)
# --------------------------------------------------------------------------


class Progresso:
    """Conta o trabalho feito e avisa o banco **de tempos em tempos** (a cada
    `PASSO_DO_PROGRESSO` unidades ou `INTERVALO_DO_PROGRESSO` segundos), não a
    cada linha. É também o ponto onde o cancelamento é percebido, e o
    "estou vivo" que a tela usa para saber se o processo parou."""

    def __init__(self, job: ExportJob):
        self.job = job
        self.feito = 0
        self.etapa = ""
        self._desde_o_ultimo = 0
        self._ultimo = time.monotonic()

    def passo(self, unidades: int = 1) -> None:
        self.feito += unidades
        self._desde_o_ultimo += unidades
        if (
            self._desde_o_ultimo >= PASSO_DO_PROGRESSO
            or time.monotonic() - self._ultimo >= INTERVALO_DO_PROGRESSO
        ):
            self.sincronizar()

    def etapa_atual(self, texto: str) -> None:
        self.etapa = texto
        self.sincronizar()

    def sincronizar(self) -> None:
        ExportJob.objects.filter(pk=self.job.pk).update(
            work_done=self.feito, stage=self.etapa, heartbeat_at=timezone.now()
        )
        self._desde_o_ultimo = 0
        self._ultimo = time.monotonic()
        if ExportJob.objects.filter(pk=self.job.pk, cancel_requested=True).exists():
            raise ExportacaoCancelada


@dataclass
class _Plano:
    conjuntos: list
    contagens: dict
    relatorios: list[tuple[str, str]]
    anexos: list


def _raiz_temporaria() -> Path:
    raiz = Path(settings.MEDIA_ROOT) / "exports-tmp"
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz


def _filtros_do_pedido(job: ExportJob, user) -> Filtros:
    pedido = job.params.get("filtros", {})
    fazenda = None
    if pedido.get("fazenda_id"):
        fazenda = ctx.available_farms(user).filter(pk=pedido["fazenda_id"]).first()
        if fazenda is None:
            raise BusinessError("A fazenda escolhida não está mais no seu acesso.")
    safra = (
        Season.objects.filter(pk=pedido["safra_id"]).first()
        if pedido.get("safra_id")
        else None
    )
    return Filtros(
        fazenda=fazenda,
        safra=safra,
        de=date.fromisoformat(pedido["de"]) if pedido.get("de") else None,
        ate=date.fromisoformat(pedido["ate"]) if pedido.get("ate") else None,
        incluir_excluidos=job.params.get("opcoes", {}).get("incluir_excluidos", False),
    )


def _anexos_do_usuario(user) -> list[tuple[str, object]]:
    """Planilhas importadas e PDFs gerados que o usuário já teria acesso a
    baixar pelas telas. Nome dentro do ZIP é gerado aqui, nunca o que veio no
    upload (zip-slip e nome hostil não entram)."""
    from apps.documents.models import DocumentStatus, GeneratedDocument
    from apps.imports.models import ImportBatch

    anexos = []
    if pode_importar(user):
        for lote in ImportBatch.objects.exclude(file="").order_by("pk"):
            extensao = Path(lote.file.name).suffix.lower()[:6]
            base = slugify(Path(lote.original_name).stem)[:60] or "planilha"
            anexos.append(
                (f"arquivos/importacoes/{lote.pk:05d}-{base}{extensao}", lote.file)
            )
    documentos = GeneratedDocument.objects.filter(status=DocumentStatus.PRONTO).exclude(
        file=""
    )
    for documento in catalog.so_os_proprios(documentos, user).order_by("pk"):
        anexos.append(
            (
                f"arquivos/documentos/{slugify(documento.entity_id)[:60]}-{documento.document_id}.pdf",
                documento.file,
            )
        )
    return anexos


def _gravar_itens(job: ExportJob) -> None:
    ExportJob.objects.filter(pk=job.pk).update(items=job.items)


def _item(job: ExportJob, item_id: str) -> dict | None:
    return next((i for i in job.items if i["id"] == item_id), None)


def _marcar(job, item_id, estado, *, linhas=None, aviso=""):
    item = _item(job, item_id)
    if item is None:
        return
    item["estado"] = estado
    if linhas is not None:
        item["linhas"] = linhas
    if aviso:
        item["aviso"] = aviso
    _gravar_itens(job)


def _falha_do_conjunto(job: ExportJob, conjunto, exc: Exception) -> BusinessError:
    """Falha ao ler um conjunto derruba a exportação inteira, nomeando o
    conjunto: um arquivo que perdeu uma tabela sem avisar é pior que nenhum.
    O traceback vai para o log; o usuário recebe o caminho e o código."""
    logger.error(
        "Falha ao exportar o conjunto %s (exportação %s)",
        conjunto.chave,
        job.job_id,
        exc_info=exc,
    )
    _marcar(
        job,
        f"dados:{conjunto.chave}",
        "erro",
        aviso="Não foi possível ler este conjunto.",
    )
    return BusinessError(
        f"Não foi possível exportar {conjunto.titulo}. Nada foi entregue, para não "
        "sair um arquivo incompleto sem aviso. Tente de novo; se persistir, avise "
        f"o suporte com o código {job.job_id}."
    )


def _planejar(job: ExportJob, user, filtros: Filtros, avisos: list[str]) -> _Plano:
    """Resolve o pedido contra o acesso **de agora**: o que o usuário perdeu
    desde que pediu é recusado (com aviso), não exportado."""
    conjuntos = []
    contagens = {}
    for chave in job.params.get("conjuntos", []):
        conjunto = catalog.conjunto_por_chave(chave)
        if conjunto is None or not conjunto.permitido(user):
            _marcar(
                job,
                f"dados:{chave}",
                "erro",
                aviso="Você não tem mais acesso a este conjunto.",
            )
            avisos.append(
                f"{chave}: sem acesso no momento da exportação; ficou de fora."
            )
            continue
        try:
            contagens[chave] = tabular.contar(conjunto, user, filtros)
        except Exception as exc:
            raise _falha_do_conjunto(job, conjunto, exc) from exc
        conjuntos.append(conjunto)

    liberados = {slug: titulo for slug, titulo, _ in catalog.relatorios_para(user)}
    relatorios = []
    for slug in job.params.get("relatorios", []):
        if slug not in liberados:
            _marcar(
                job,
                f"relatorio:{slug}",
                "erro",
                aviso="Você não tem mais acesso a este relatório.",
            )
            avisos.append(
                f"{slug}: sem acesso no momento da exportação; ficou de fora."
            )
            continue
        relatorios.append((slug, liberados[slug]))

    anexos = (
        _anexos_do_usuario(user)
        if job.params.get("opcoes", {}).get("incluir_arquivos")
        else []
    )
    return _Plano(conjuntos, contagens, relatorios, anexos)


def _escritores(job, pasta, meta, progresso, conjunto_do_modelo):
    formatos = job.params.get("formatos", [])
    br = job.params.get("opcoes", {}).get("csv", "br") == "br"
    escritores = []
    if "csv" in formatos:
        escritores.append(writers.CsvEscritor(pasta, br=br))
    if "xlsx" in formatos:
        escritores.append(writers.PlanilhaEscritor(pasta, meta=meta))
    if "json" in formatos:
        escritores.append(
            writers.JsonEscritor(
                pasta, meta=meta, conjunto_do_modelo=conjunto_do_modelo
            )
        )
    if "pdf" in formatos:
        escritores.append(
            writers.PdfEscritor(pasta, meta=meta, ao_gerar_parte=progresso.sincronizar)
        )
    return escritores


def _ler_conjunto(conjunto, user, filtros, escritores, progresso, rotulos):
    """Uma passada pelo banco alimenta todos os formatos pedidos."""
    modos = {e.modo for e in escritores}
    colunas = {m: tabular.colunas_do_conjunto(conjunto, user, m) for m in modos}
    for escritor in escritores:
        escritor.abrir(conjunto, colunas[escritor.modo])
    funcoes = {
        modo: [tabular.extrator(c, rotulos) for c in cols]
        for modo, cols in colunas.items()
    }
    registros = tabular.consulta(conjunto, user, filtros).select_related(
        *tabular.vinculos_a_carregar(conjunto, user)
    )
    n = 0
    for registro in registros.iterator(chunk_size=1000):
        valores = {modo: [f(registro) for f in fs] for modo, fs in funcoes.items()}
        for escritor in escritores:
            escritor.linha(valores[escritor.modo])
        n += 1
        progresso.passo()
    arquivos = []
    for escritor in escritores:
        arquivos += escritor.fechar()
    return n, arquivos


def _produzir(job: ExportJob, user, pasta: Path, progresso: Progresso):
    if not pode_exportar(user):
        raise BusinessError(
            "Seu acesso à exportação foi alterado depois do pedido. Fale com o administrador."
        )
    avisos: list[str] = []
    filtros = _filtros_do_pedido(job, user)
    progresso.etapa_atual("Contando os registros")
    plano = _planejar(job, user, filtros, avisos)
    total = (
        sum(plano.contagens.values())
        + len(plano.relatorios) * PESO_DO_RELATORIO
        + len(plano.anexos) * PESO_DO_ANEXO
    )
    ExportJob.objects.filter(pk=job.pk).update(work_total=total)
    job.work_total = total

    agora = timezone.localtime()
    meta = {
        "gerado_em": agora.isoformat(),
        "gerado_em_dt": agora,
        "gerado_em_texto": agora.strftime("%d/%m/%Y %H:%M"),
        "gerado_por": str(user),
        "filtros": job.filters,
        "incluir_excluidos": filtros.incluir_excluidos,
        "opcoes": job.params.get("opcoes", {}),
        "avisos": avisos,
    }
    conjunto_do_modelo = {c.modelo: c.chave for c in catalog.CONJUNTOS}
    escritores = _escritores(job, pasta, meta, progresso, conjunto_do_modelo)
    rotulos = tabular.Rotulos()
    arquivos: list[writers.Arquivo] = []
    resumo_dos_conjuntos: list[dict] = []
    resumo_dos_relatorios: list[dict] = []

    try:
        for numero, conjunto in enumerate(plano.conjuntos, start=1):
            progresso.etapa_atual(
                f"Lendo {conjunto.titulo} ({numero} de {len(plano.conjuntos)})"
            )
            _marcar(job, f"dados:{conjunto.chave}", "lendo")
            try:
                n, gerados = _ler_conjunto(
                    conjunto, user, filtros, escritores, progresso, rotulos
                )
            except ExportacaoCancelada:
                raise
            except Exception as exc:
                raise _falha_do_conjunto(job, conjunto, exc) from exc
            arquivos += gerados
            avisos += [a.aviso for a in gerados if a.aviso]
            _marcar(
                job,
                f"dados:{conjunto.chave}",
                "ok" if n else "vazio",
                linhas=n,
                aviso=next((a.aviso for a in gerados if a.aviso), ""),
            )
            colunas_tecnicas = tabular.colunas_do_conjunto(conjunto, user, TECNICO)
            resumo_dos_conjuntos.append(
                {
                    "chave": conjunto.chave,
                    "rotulo": conjunto.titulo,
                    "grupo": conjunto.grupo,
                    "registros": n,
                    "colunas": [
                        writers._coluna_para_dicionario(c, conjunto_do_modelo)
                        for c in colunas_tecnicas
                    ],
                }
            )
        progresso.etapa_atual("Finalizando os arquivos")
        for escritor in escritores:
            arquivos += escritor.finalizar()
    except BaseException:
        for escritor in escritores:
            escritor.abortar()
        raise

    for numero, (slug, titulo) in enumerate(plano.relatorios, start=1):
        progresso.etapa_atual(
            f"Montando o relatório {titulo} ({numero} de {len(plano.relatorios)})"
        )
        _marcar(job, f"relatorio:{slug}", "lendo")
        try:
            relatorio = _montar_relatorio(slug, user, filtros)
            gerados = writers.escrever_relatorio(
                relatorio, slug, job.params["formatos"], pasta, meta
            )
        except ExportacaoCancelada:
            raise
        except PermissionDenied:
            _marcar(
                job, f"relatorio:{slug}", "erro", aviso="Sem acesso a este relatório."
            )
            avisos.append(f"{titulo}: sem acesso; ficou de fora.")
        except Exception:
            logger.exception("Falha ao montar o relatório %s na exportação", slug)
            _marcar(
                job,
                f"relatorio:{slug}",
                "erro",
                aviso="Não foi possível montar este relatório.",
            )
            avisos.append(f"{titulo}: não foi possível montar; ficou de fora.")
        else:
            arquivos += gerados
            _marcar(job, f"relatorio:{slug}", "ok")
            resumo_dos_relatorios.append({"slug": slug, "rotulo": titulo})
        progresso.passo(PESO_DO_RELATORIO)

    if plano.anexos:
        progresso.etapa_atual("Reunindo os arquivos anexos")
        _marcar(job, "anexos", "lendo")

    if not arquivos and not plano.anexos:
        raise BusinessError(
            "Nenhum arquivo foi gerado: todos os itens escolhidos ficaram de fora. "
            "Veja os avisos de cada item."
        )

    progresso.etapa_atual("Empacotando")
    nome_base = f"rebanho360-exportacao-{agora:%Y%m%d-%H%M}"
    caminho, nome, tipo, avisos_do_pacote = packaging.empacotar(
        pasta,
        arquivos,
        [(arcname, campo) for arcname, campo in plano.anexos],
        meta=meta,
        conjuntos=resumo_dos_conjuntos,
        relatorios=resumo_dos_relatorios,
        nome_base=nome_base,
        ao_anexo=lambda: progresso.passo(PESO_DO_ANEXO),
    )
    avisos += avisos_do_pacote
    if plano.anexos:
        _marcar(
            job,
            "anexos",
            "ok",
            linhas=len(plano.anexos) - len(avisos_do_pacote),
            aviso=avisos_do_pacote[0] if avisos_do_pacote else "",
        )
    return caminho, nome, tipo, avisos


def _montar_relatorio(slug, user, filtros: Filtros):
    from apps.reports import services as relatorios

    aceitos = relatorios.PARAMETROS.get(slug, ())
    extras = {}
    if "de" in aceitos and filtros.de:
        extras["start"] = filtros.de
    if "ate" in aceitos and filtros.ate:
        extras["end"] = filtros.ate
    return relatorios.montar_relatorio(
        user, slug, season=filtros.safra, farm=filtros.fazenda, extras=extras
    )


def executar_exportacao(job_id: int) -> ExportJob:
    """Idempotente: só um pedido `PENDENTE` é executado — a fila pode entregar
    a mesma tarefa duas vezes, e o clique duplo não gera dois arquivos."""
    with transaction.atomic():
        job = (
            ExportJob.objects.select_for_update()
            .select_related("requested_by")
            .get(pk=job_id)
        )
        if job.status != ExportStatus.PENDENTE:
            return job
        agora = timezone.now()
        if job.cancel_requested:
            job.status, job.finished_at = ExportStatus.CANCELADO, agora
            job.save(update_fields=["status", "finished_at"])
            return job
        job.status = ExportStatus.PROCESSANDO
        job.started_at = job.heartbeat_at = agora
        job.stage = "Começando"
        job.save(update_fields=["status", "started_at", "heartbeat_at", "stage"])

    user = job.requested_by
    pasta = Path(tempfile.mkdtemp(prefix="export-", dir=_raiz_temporaria()))
    progresso = Progresso(job)
    try:
        caminho, nome, tipo, avisos = _produzir(job, user, pasta, progresso)
        _concluir(job, user, caminho, nome, tipo, avisos)
    except ExportacaoCancelada:
        _encerrar(job, ExportStatus.CANCELADO, "")
    except BusinessError as exc:
        _encerrar(job, ExportStatus.ERRO, str(exc))
    except SoftTimeLimitExceeded:
        logger.error("Exportação %s passou do limite de tempo", job.job_id)
        _encerrar(
            job,
            ExportStatus.ERRO,
            "A exportação passou de uma hora e foi interrompida. Peça de novo "
            "com menos conjuntos, ou separe os maiores.",
        )
    except Exception:
        logger.exception("Falha inesperada na exportação %s", job.job_id)
        _encerrar(
            job,
            ExportStatus.ERRO,
            "Não foi possível concluir a exportação. Tente de novo; se persistir, "
            f"avise o suporte com o código {job.job_id}.",
        )
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    job.refresh_from_db()
    return job


def _encerrar(job: ExportJob, status: str, erro: str) -> None:
    ExportJob.objects.filter(pk=job.pk).update(
        status=status, error=erro, finished_at=timezone.now(), stage=""
    )
    if status == ExportStatus.CANCELADO:
        registrar_auditoria(
            action=AuditAction.CANCEL,
            entity_type="Exportacao",
            entity_id=str(job.job_id),
            reason="Exportação cancelada antes de terminar",
            actor=job.requested_by,
        )


def _concluir(
    job, user, caminho: Path, nome: str, tipo: str, avisos: list[str]
) -> None:
    sha = packaging.sha256_do_arquivo(caminho)
    tamanho = caminho.stat().st_size
    agora = timezone.now()
    with transaction.atomic():
        atual = ExportJob.objects.select_for_update().get(pk=job.pk)
        if atual.cancel_requested:
            raise ExportacaoCancelada
        if atual.status != ExportStatus.PROCESSANDO:
            # A manutenção já deu esta exportação por interrompida: o
            # estado dela está decidido, e o arquivo que sobrou é descartado.
            return
        with open(caminho, "rb") as f:
            atual.file.save(f"{atual.job_id}{caminho.suffix}", File(f), save=False)
        atual.status = ExportStatus.PRONTO
        atual.file_name, atual.content_type = nome, tipo
        atual.file_hash, atual.size_bytes = sha, tamanho
        atual.warnings = [a for a in dict.fromkeys(avisos) if a]
        atual.items = job.items
        atual.work_done = atual.work_total
        atual.stage = ""
        atual.finished_at = agora
        atual.expires_at = agora + _retencao()
        atual.save()
        registrar_auditoria(
            action=AuditAction.EXPORT,
            entity_type="Exportacao",
            entity_id=str(atual.job_id),
            reason=(
                f"Exportação concluída: {nome} ({tamanho} bytes) · "
                + " · ".join(atual.filters)
            ),
            after={"sha256": sha, "bytes": tamanho, "arquivo": nome},
            actor=user,
        )


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


def cancelar_exportacao(job: ExportJob, *, user) -> ExportJob:
    """Na fila, cancela na hora; rodando, avisa o processador, que para no
    próximo ponto de controle (em segundos)."""
    with transaction.atomic():
        job = ExportJob.objects.select_for_update().get(pk=job.pk)
        if job.status == ExportStatus.PENDENTE:
            job.status, job.finished_at = ExportStatus.CANCELADO, timezone.now()
            job.cancel_requested = True
            job.save(update_fields=["status", "finished_at", "cancel_requested"])
            registrar_auditoria(
                action=AuditAction.CANCEL,
                entity_type="Exportacao",
                entity_id=str(job.job_id),
                reason="Exportação cancelada na fila",
                actor=user,
            )
        elif job.status == ExportStatus.PROCESSANDO:
            job.cancel_requested = True
            job.save(update_fields=["cancel_requested"])
        else:
            raise BusinessError("Esta exportação já terminou; não há o que cancelar.")
    return job


def repetir_exportacao(job: ExportJob, *, user) -> ExportJob:
    """Um pedido novo com os mesmos parâmetros — para a que deu erro, foi
    cancelada ou cujo arquivo já expirou. Passa pela validação de novo: se o
    acesso mudou, o pedido novo reflete o acesso de agora."""
    pedido = job.params
    filtros = pedido.get("filtros", {})
    fazenda = (
        ctx.available_farms(user).filter(pk=filtros["fazenda_id"]).first()
        if filtros.get("fazenda_id")
        else None
    )
    if filtros.get("fazenda_id") and fazenda is None:
        raise BusinessError("A fazenda deste pedido não está mais no seu acesso.")
    return solicitar_exportacao(
        user=user,
        conjuntos=pedido.get("conjuntos", []),
        relatorios=pedido.get("relatorios", []),
        formatos=pedido.get("formatos", []),
        fazenda=fazenda,
        safra=(
            Season.objects.filter(pk=filtros["safra_id"]).first()
            if filtros.get("safra_id")
            else None
        ),
        de=date.fromisoformat(filtros["de"]) if filtros.get("de") else None,
        ate=date.fromisoformat(filtros["ate"]) if filtros.get("ate") else None,
        incluir_excluidos=pedido.get("opcoes", {}).get("incluir_excluidos", False),
        incluir_arquivos=pedido.get("opcoes", {}).get("incluir_arquivos", False),
        estilo_csv=pedido.get("opcoes", {}).get("csv", "br"),
    )


def _remover_arquivo(job: ExportJob, *, motivo: str, ator) -> None:
    """Apaga o arquivo do disco (o pedido fica). Chamado de dentro de uma
    transação com o job travado."""
    if job.file:
        job.file.delete(save=False)
    job.status = ExportStatus.EXPIRADO
    job.file_removed_at = timezone.now()
    job.save(update_fields=["file", "status", "file_removed_at"])
    registrar_auditoria(
        action=AuditAction.DELETE,
        entity_type="Exportacao",
        entity_id=str(job.job_id),
        reason=motivo,
        actor=ator,
    )


def apagar_arquivo(job: ExportJob, *, user) -> ExportJob:
    with transaction.atomic():
        job = ExportJob.objects.select_for_update().get(pk=job.pk)
        if job.status != ExportStatus.PRONTO:
            raise BusinessError("Só dá para apagar o arquivo de uma exportação pronta.")
        _remover_arquivo(job, motivo="Arquivo apagado por quem pediu", ator=user)
    return job


def manutencao() -> dict[str, int]:
    """Roda de tempos em tempos (Celery beat): dá por interrompida a
    exportação sem sinal de vida e apaga os arquivos vencidos."""
    agora = timezone.now()
    interrompidas = 0
    for job in ExportJob.objects.filter(status=ExportStatus.PROCESSANDO).filter(
        heartbeat_at__lt=agora - INTERROMPIDA_APOS
    ):
        interrompidas += ExportJob.objects.filter(
            pk=job.pk,
            status=ExportStatus.PROCESSANDO,
            heartbeat_at__lt=agora - INTERROMPIDA_APOS,
        ).update(
            status=ExportStatus.ERRO,
            finished_at=agora,
            error=(
                "A exportação foi interrompida (o processador parou no meio). "
                "Peça de novo: nada foi entregue pela metade."
            ),
        )
    ExportJob.objects.filter(
        status=ExportStatus.PENDENTE, created_at__lt=agora - NA_FILA_APOS
    ).update(
        status=ExportStatus.ERRO,
        finished_at=agora,
        error="A exportação não chegou a ser processada. Peça de novo.",
    )
    expiradas = 0
    for pk in list(
        ExportJob.objects.filter(
            status=ExportStatus.PRONTO, expires_at__lt=agora
        ).values_list("pk", flat=True)
    ):
        with transaction.atomic():
            job = ExportJob.objects.select_for_update().get(pk=pk)
            if job.status == ExportStatus.PRONTO and job.expires_at < agora:
                _remover_arquivo(
                    job,
                    motivo=f"Arquivo removido: passou o prazo de {_retencao().days} dias",
                    ator=None,
                )
                expiradas += 1
    # Pastas temporárias de processos que morreram sem limpar.
    raiz = _raiz_temporaria()
    for pasta in raiz.glob("export-*"):
        if time.time() - pasta.stat().st_mtime > 24 * 3600:
            shutil.rmtree(pasta, ignore_errors=True)
    return {"interrompidas": interrompidas, "expiradas": expiradas}
