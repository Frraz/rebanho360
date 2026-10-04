"""Geração de PDF com WeasyPrint.

`solicitar_documento` registra o pedido; `gerar_documento` monta o relatório
**com o escopo de quem pediu**, renderiza, calcula o hash e guarda o arquivo.
Relatório pesado roda em Celery e o navegador não espera (docs/relatorios/01).
"""

import hashlib
import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import context as ctx
from apps.core.exceptions import BusinessError
from apps.documents import layout
from apps.documents.models import DocumentStatus, DocumentType, GeneratedDocument
from apps.organizations.models import Season
from apps.reports import services as relatorios
from apps.reports.parametros import parametros_do_relatorio

logger = logging.getLogger(__name__)

#: Muda quando o layout do PDF muda. Fica gravada em cada documento: o
#: arquivo é a reprodução, a versão diz com qual layout ele nasceu.
TEMPLATE_VERSION = "relatorio-v2"

#: Relatórios que percorrem lote a lote (rateio de custo, pesagens) e podem
#: demorar: vão para a fila em vez de segurar o navegador.
RELATORIOS_PESADOS = frozenset(
    {
        "resultado-do-lote",
        "desempenho-do-lote",
        "pesagens",
        "inventario-valorizado",
        "tir-da-safra",
        "confinamento",
    }
)

LARGURA_PARA_PAISAGEM = 7  # colunas


def _parametros_para_gravar(extras: dict, *, season, farm) -> dict:
    """Só JSON puro: ids, datas ISO e `Decimal` como texto."""
    params = {
        "season_id": season.pk if season else None,
        "farm_id": farm.pk if farm else None,
    }
    for chave, valor in extras.items():
        if valor is None:
            continue
        if chave in ("start", "end"):
            params[chave] = valor.isoformat()
        elif chave == "lote":
            params["lote_id"] = valor.pk
        elif chave in ("acerto", "comprador", "fazenda"):
            params[f"{chave}_id"] = valor.pk
        else:
            params[chave] = str(valor)
    return params


def _extras_a_partir_dos_parametros(params: dict, user) -> dict:
    import datetime
    from decimal import Decimal

    from apps.livestock.models import Lot

    extras = {}
    for chave in ("start", "end"):
        if params.get(chave):
            extras[chave] = datetime.date.fromisoformat(params[chave])
    if params.get("lote_id"):
        extras["lote"] = Lot.objects.for_user(user).filter(pk=params["lote_id"]).first()
    if params.get("acerto_id"):
        from apps.procurement.models import Settlement

        extras["acerto"] = (
            Settlement.objects.for_user(user).filter(pk=params["acerto_id"]).first()
        )
    if params.get("comprador_id"):
        from apps.reports.parametros import compradores_do_escopo

        extras["comprador"] = (
            compradores_do_escopo(user).filter(pk=params["comprador_id"]).first()
        )
    if params.get("fazenda_id"):
        extras["fazenda"] = (
            ctx.available_farms(user).filter(pk=params["fazenda_id"]).first()
        )
    if params.get("situacao"):
        extras["situacao"] = params["situacao"]
    if params.get("rendimento_entrada"):
        extras["rendimento_entrada"] = Decimal(params["rendimento_entrada"])
    if params.get("preco_arroba"):
        extras["preco_arroba"] = Decimal(params["preco_arroba"])
    return extras


def solicitar_documento(*, slug: str, user, season, farm, origem) -> GeneratedDocument:
    """Registra o pedido e gera — na hora ou na fila. Os filtros que o
    usuário viu na tela ficam gravados no documento."""
    if slug not in relatorios.RELATORIOS:
        raise BusinessError("Relatório desconhecido.")
    extras = parametros_do_relatorio(user, slug, origem)
    relatorio = relatorios.montar_relatorio(
        user, slug, season=season, farm=farm, extras=extras
    )
    with transaction.atomic():
        documento = GeneratedDocument.objects.create(
            doc_type=DocumentType.RELATORIO,
            entity_type="Relatorio",
            entity_id=slug,
            title=relatorio.titulo,
            template_version=TEMPLATE_VERSION,
            params=_parametros_para_gravar(extras, season=season, farm=farm),
            filters=list(relatorio.filtros),
            generated_by=user,
        )
        registrar_auditoria(
            action=AuditAction.EXPORT,
            entity_type="Documento",
            entity_id=str(documento.document_id),
            reason=f"{relatorio.titulo} (pdf) · " + " · ".join(relatorio.filtros),
            actor=user,
        )
        if slug in RELATORIOS_PESADOS:
            from apps.documents.tasks import gerar_pdf

            transaction.on_commit(lambda: gerar_pdf.delay(documento.pk))
    if slug not in RELATORIOS_PESADOS:
        gerar_documento(documento.pk)
        documento.refresh_from_db()
    return documento


def renderizar_html(relatorio, *, emitido_por: str, emitido_em, versao: str) -> str:
    """O HTML do documento: cabeçalho com sistema, relatório, emissão e
    **filtros aplicados**, repetido em toda página (CSS `running`)."""
    tabelas = [("", layout.preparar_tabela(relatorios.para_tela(relatorio)))] + [
        (s.titulo, layout.preparar_tabela(relatorios.para_tela(s)))
        for s in relatorio.secoes
    ]
    return render_to_string(
        "documents/relatorio.html",
        {
            "relatorio": relatorio,
            "tabelas": tabelas,
            "emitido_por": emitido_por,
            "emitido_em": emitido_em,
            "versao": versao,
            "paisagem": len(relatorio.colunas) > LARGURA_PARA_PAISAGEM,
            "densidade": layout.densidade_do_documento([t for _, t in tabelas]),
        },
    )


def renderizar_pdf(relatorio, *, emitido_por: str, emitido_em, versao: str) -> bytes:
    import weasyprint

    html = renderizar_html(
        relatorio, emitido_por=emitido_por, emitido_em=emitido_em, versao=versao
    )
    return weasyprint.HTML(string=html).write_pdf()


def gerar_documento(documento_id: int) -> GeneratedDocument:
    """Idempotente: um documento já pronto não é gerado de novo (a fila pode
    entregar a mesma tarefa duas vezes)."""
    with transaction.atomic():
        documento = GeneratedDocument.objects.select_for_update().get(pk=documento_id)
        if documento.status != DocumentStatus.PENDENTE:
            return documento
        try:
            user = documento.generated_by
            season = Season.objects.filter(pk=documento.params.get("season_id")).first()
            farm = None
            if documento.params.get("farm_id"):
                farm = (
                    ctx.available_farms(user)
                    .filter(pk=documento.params["farm_id"])
                    .first()
                )
                if farm is None:
                    raise BusinessError(
                        "A fazenda do relatório não está mais no seu acesso."
                    )
            relatorio = relatorios.montar_relatorio(
                user,
                documento.entity_id,
                season=season,
                farm=farm,
                extras=_extras_a_partir_dos_parametros(documento.params, user),
            )
            agora = timezone.localtime()
            pdf = renderizar_pdf(
                relatorio,
                emitido_por=str(user),
                emitido_em=agora,
                versao=documento.template_version,
            )
        except Exception as exc:  # o usuário vê o motivo, nunca um traceback
            logger.exception("Falha ao gerar o documento %s", documento.document_id)
            documento.status = DocumentStatus.ERRO
            documento.error = (
                str(exc)
                if isinstance(exc, BusinessError)
                else "Não foi possível gerar o PDF. Tente de novo; se persistir, avise o suporte "
                f"com o código {documento.document_id}."
            )
            documento.finished_at = timezone.now()
            documento.save(update_fields=["status", "error", "finished_at"])
            return documento

        documento.file.save(
            f"{documento.entity_id}-{documento.document_id}.pdf",
            ContentFile(pdf),
            save=False,
        )
        documento.file_hash = hashlib.sha256(pdf).hexdigest()
        documento.size_bytes = len(pdf)
        documento.status = DocumentStatus.PRONTO
        documento.finished_at = timezone.now()
        documento.save()
        return documento
