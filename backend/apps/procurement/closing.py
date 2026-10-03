"""O fechamento: criar o acerto, lançar tributos e notas, **aprovar**, reabrir.

Aprovar é uma transação só: cria e confirma **uma `Purchase` por item
recebido**, com os valores que o acerto apurou. A compra, por sua vez, dá a
entrada no rebanho, lança os custos e gera os títulos — a mecânica de sempre.
`CONFIRMADA` é alcançada aqui, depois do acerto, e não direto (ADR 0008).

**Trava de fechamento = `bloqueios()`**, não estado: com o acerto aprovado,
tudo que alimenta o valor recusa edição e diz o caminho (reabrir o acerto).
Reabrir é formal: motivo obrigatório, quem e quando na auditoria, efeitos
desfeitos juntos.
"""

import datetime
import uuid

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria, registrar_operacao
from apps.core import reversible
from apps.core.exceptions import (
    BlockingDependencyError,
    Bloqueio,
    BusinessError,
    DependencyError,
)
from apps.core.formatting import dinheiro_br
from apps.core.permissions import pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.serialization import diff_fields, snapshot
from apps.herd.permissions import tem_acesso_de_escrita_a_fazenda
from apps.organizations.models import Season
from apps.procurement import selectors
from apps.procurement.codes import proximo_codigo
from apps.procurement.commitments import (
    _restaurar_como_rascunho,
    exigir_acerto_aberto,
)
from apps.procurement.lines import sincronizar_linhas
from apps.procurement.models import (
    Commitment,
    FiscalNote,
    Settlement,
    SettlementLine,
)
from apps.procurement.permissions import pode_aprovar_o_acerto, pode_lancar_no_ciclo
from apps.procurement.settlement import calcular_acerto
from apps.purchases import services as compras

CAMPOS_DA_LINHA = ("tax_type", "amount", "reference", "notes")
CAMPOS_DA_NOTA = ("number", "series", "issue_date", "amount")


# --------------------------------------------------------------------------
# Criar e lançar
# --------------------------------------------------------------------------


@transaction.atomic
def criar_acerto(
    *, usuario, compromisso: Commitment, date: datetime.date, notes: str = ""
) -> Settlement:
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para lançar acertos.")
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.CONFIRMADA:
        raise BusinessError("O acerto se abre depois da aprovação do compromisso.")
    if not tem_acesso_de_escrita_a_fazenda(usuario, compromisso.destination_farm):
        raise BusinessError(
            f"Você não tem permissão de lançamento em {compromisso.destination_farm}."
        )
    existente = selectors.acerto_ativo(compromisso)
    if existente is not None:
        raise BusinessError(
            f"O compromisso {compromisso.code} já tem o acerto {existente.code}. "
            "Trabalhe nele, ou exclua-o para abrir outro."
        )
    if date > timezone.localdate():
        raise BusinessError("Acerto com data futura não é permitido.")

    season = Season.objects.select_for_update().get(pk=compromisso.season_id)
    acerto = Settlement(
        commitment=compromisso, date=date, notes=notes or "", created_by=usuario
    )
    acerto.code = proximo_codigo(Settlement, "AC", season)
    acerto.save()
    registrar_auditoria(
        action=AuditAction.CREATE,
        entity=acerto,
        after=snapshot(acerto),
        actor=usuario,
    )
    return acerto


@transaction.atomic
def editar_acerto(acerto: Settlement, dados: dict, *, usuario) -> Settlement:
    """Data e observação do acerto **em andamento**. Corrigir o aprovado é
    reabri-lo — editar não o desfaz nem o refaz."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para editar acertos.")
    acerto = Settlement.objects.select_for_update().get(pk=acerto.pk)
    if acerto.status != Status.RASCUNHO:
        raise BusinessError(
            "Este acerto está aprovado. Para corrigir, reabra-o (com motivo)."
        )
    novo_dia = dados.get("date", acerto.date)
    if novo_dia > timezone.localdate():
        raise BusinessError("Acerto com data futura não é permitido.")
    antes = snapshot(acerto)
    acerto.date = novo_dia
    acerto.notes = dados.get("notes", acerto.notes) or ""
    acerto.updated_by = usuario
    acerto.version += 1
    acerto.save()
    depois = snapshot(acerto)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=acerto,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        actor=usuario,
    )
    return acerto


@transaction.atomic
def registrar_linhas(
    acerto: Settlement, linhas: list[dict], *, usuario, motivo: str = ""
):
    """Tributos, taxas, descontos, adiantamentos e créditos — **valor digitado**
    (pendência #21). Só com o acerto em andamento."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para lançar no acerto.")
    acerto = Settlement.objects.select_for_update().get(pk=acerto.pk)
    exigir_acerto_aberto(acerto.commitment, "mudar os valores do acerto")
    if acerto.status != Status.RASCUNHO:
        raise BusinessError("Este acerto está excluído.")

    existentes = {linha.pk: linha for linha in acerto.lines.all()}
    for posicao, entrada in enumerate(linhas, start=1):
        tipo = entrada.get("tax_type")
        if tipo is None:
            raise BusinessError(f"Linha {posicao}: escolha o tipo.")
        usado_antes = existentes.get(entrada.get("id"))
        if not tipo.is_active and not (
            usado_antes and usado_antes.tax_type_id == tipo.pk
        ):
            raise BusinessError(f"Linha {posicao}: o tipo {tipo} está inativo.")
        valor = entrada.get("amount")
        if valor is None or valor <= 0:
            raise BusinessError(f"Linha {posicao}: informe um valor maior que zero.")

    def _criar(entrada: dict) -> SettlementLine:
        linha = SettlementLine(settlement=acerto)
        for campo in CAMPOS_DA_LINHA:
            if campo in entrada:
                setattr(linha, campo, entrada[campo])
        linha.reference = linha.reference or ""
        linha.notes = linha.notes or ""
        linha.save()
        return linha

    return sincronizar_linhas(
        existentes=list(existentes.values()),
        entradas=linhas,
        campos=CAMPOS_DA_LINHA,
        criar=_criar,
        usuario=usuario,
        motivo=motivo,
    )


@transaction.atomic
def registrar_notas(
    acerto: Settlement, notas: list[dict], *, usuario, motivo: str = ""
):
    """Notas fiscais **registradas** (o sistema não emite nota). Não mudam
    valor nenhum, por isso valem também com o acerto aprovado — e, registradas,
    bloqueiam reabri-lo."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para lançar notas fiscais.")
    acerto = Settlement.objects.select_for_update().get(pk=acerto.pk)
    if acerto.status == Status.EXCLUIDA:
        raise BusinessError("Este acerto está excluído.")
    for posicao, entrada in enumerate(notas, start=1):
        if not (entrada.get("number") or "").strip():
            raise BusinessError(f"Nota {posicao}: informe o número.")
        if entrada.get("issue_date") is None:
            raise BusinessError(f"Nota {posicao}: informe a data de emissão.")
        valor = entrada.get("amount")
        if valor is None or valor < 0:
            raise BusinessError(f"Nota {posicao}: informe o valor (zero ou mais).")

    def _criar(entrada: dict) -> FiscalNote:
        nota = FiscalNote(settlement=acerto)
        for campo in CAMPOS_DA_NOTA:
            if campo in entrada:
                setattr(nota, campo, entrada[campo])
        nota.series = nota.series or ""
        nota.save()
        return nota

    return sincronizar_linhas(
        existentes=list(acerto.fiscal_notes.all()),
        entradas=notas,
        campos=CAMPOS_DA_NOTA,
        criar=_criar,
        usuario=usuario,
        motivo=motivo,
    )


# --------------------------------------------------------------------------
# Aprovar, reabrir, excluir, restaurar
# --------------------------------------------------------------------------


@transaction.atomic
def aprovar_acerto(acerto: Settlement, *, usuario) -> Settlement:
    """RASCUNHO → CONFIRMADA. Cria e confirma uma compra por item recebido.
    Clique duplo ou duas pessoas ao mesmo tempo: a trava faz a segunda ver o
    acerto já aprovado."""
    if not pode_aprovar_o_acerto(usuario):
        raise BusinessError(
            "Você não tem permissão para aprovar acertos. A aprovação é de "
            "administrador ou gestor."
        )
    Commitment.objects.select_for_update().get(pk=acerto.commitment_id)
    acerto = Settlement.objects.select_for_update().get(pk=acerto.pk)
    if acerto.status == Status.CONFIRMADA:
        raise BusinessError("Este acerto já foi aprovado.")
    if acerto.status == Status.EXCLUIDA:
        raise BusinessError("Este acerto está excluído.")
    return reversible.confirmar(acerto, usuario=usuario)


@transaction.atomic
def reabrir_acerto(
    acerto: Settlement, *, usuario, motivo: str, cascata: bool = False
) -> Settlement:
    """Reabertura **formal** do acerto aprovado: desfaz as compras (e com elas
    o rebanho, os custos e os títulos) e devolve o acerto a "em andamento".

    Baixa de título já feita, nota fiscal registrada e safra encerrada
    **bloqueiam**, cada um com o caminho. O que depende das compras (saída de
    animais do lote, por exemplo) só é desfeito com a cascata confirmada.
    """
    if not pode_aprovar_o_acerto(usuario):
        raise BusinessError(
            "Você não tem permissão para reabrir acertos. A reabertura é de "
            "administrador ou gestor."
        )
    if not (motivo or "").strip():
        raise BusinessError("Motivo é obrigatório para reabrir um acerto aprovado.")
    Commitment.objects.select_for_update().get(pk=acerto.commitment_id)
    acerto = Settlement.objects.select_for_update().get(pk=acerto.pk)
    if acerto.status != Status.CONFIRMADA:
        raise BusinessError("Só se reabre um acerto aprovado.")

    bloqueios = acerto.bloqueios()
    if bloqueios:
        raise BlockingDependencyError(f"Não é possível reabrir: {bloqueios[0]}")
    dependentes = acerto.dependentes()
    if dependentes and not cascata:
        raise DependencyError(dependentes)

    raiz = uuid.uuid4()
    for dependente in dependentes:
        reversible.excluir(
            dependente, usuario=usuario, motivo=motivo, cascata=True, raiz=raiz
        )

    antes = snapshot(acerto)
    acerto.cascade_root = raiz
    acerto.cascade_root_usado = False
    acerto.desfazer_efeitos(usuario=usuario)
    acerto.status = Status.RASCUNHO
    acerto.approved_by = None
    acerto.approved_at = None
    acerto.version += 1
    acerto.updated_by = usuario
    acerto.save()
    depois = snapshot(acerto)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=acerto,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=motivo,
        cascade_root=raiz,
        actor=usuario,
    )
    registrar_operacao(
        entity=acerto,
        title="Acerto reaberto",
        description=f"Motivo: {motivo.strip()}",
        previous_status=Status.CONFIRMADA,
        new_status=Status.RASCUNHO,
        document=acerto.code,
        actor=usuario,
    )
    return acerto


@transaction.atomic
def excluir_acerto(
    acerto: Settlement, *, usuario, motivo: str, cascata: bool = False
) -> Settlement:
    if acerto.status == Status.RASCUNHO:
        if not pode_lancar_no_ciclo(usuario):
            raise BusinessError("Você não tem permissão para excluir este acerto.")
    elif not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir acerto aprovado.")
    return reversible.excluir(acerto, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar_acerto(acerto: Settlement, *, usuario) -> Settlement:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar acerto.")
    if acerto.commitment.status != Status.CONFIRMADA:
        raise BusinessError(
            "O compromisso deste acerto está excluído: restaure o compromisso antes."
        )
    outro = selectors.acerto_ativo(acerto.commitment)
    if outro is not None:
        raise BusinessError(
            f"O compromisso já tem o acerto {outro.code}: só um acerto vale por vez."
        )
    if acerto.approved_at is None:
        # Excluído ainda em andamento: volta em andamento, sem aprovar.
        return _restaurar_como_rascunho(acerto, usuario=usuario)
    return reversible.restaurar(acerto, usuario=usuario)


# --------------------------------------------------------------------------
# Contrato ReversibleModel
# --------------------------------------------------------------------------


def _compras_do_acerto(acerto: Settlement, *, confirmadas: bool = True) -> list:
    compras_ = []
    for item in acerto.commitment.items.select_related("purchase"):
        compra = item.purchase
        if compra is None:
            continue
        if confirmadas and compra.status != Status.CONFIRMADA:
            continue
        compras_.append(compra)
    return compras_


def bloqueios_do_acerto(acerto: Settlement) -> list:
    """Só o acerto aprovado bloqueia: baixa de título, safra encerrada e nota
    fiscal registrada (o documento fiscal já existe)."""
    if acerto.status != Status.CONFIRMADA:
        return []
    bloqueios, vistos = [], set()
    for compra in _compras_do_acerto(acerto):
        for bloqueio in compra.bloqueios():
            if str(bloqueio) not in vistos:
                vistos.add(str(bloqueio))
                bloqueios.append(bloqueio)
    notas = list(acerto.fiscal_notes.all())
    if notas:
        numeros = ", ".join(n.number for n in notas)
        bloqueios.append(
            Bloqueio(
                texto=(
                    f"há nota fiscal registrada no acerto ({numeros}). O documento "
                    "fiscal já existe: retire a nota (com motivo) antes."
                ),
                url=reverse("procurement:acerto_detalhe", args=[acerto.pk])
                + "#notas-fiscais",
                rotulo_url="Ir para as notas fiscais",
            )
        )
    return bloqueios


def dependentes_do_acerto(acerto: Settlement) -> list:
    """O que depende das compras do acerto: saída de animais do lote, pesagens,
    custos avulsos. Sem cascata confirmada, nada disso é desfeito."""
    if acerto.status != Status.CONFIRMADA:
        return []
    dependentes, vistos = [], set()
    for compra in _compras_do_acerto(acerto):
        for dep in compra.dependentes():
            chave = (type(dep).__name__, dep.pk)
            if chave not in vistos:
                vistos.add(chave)
                dependentes.append(dep)
    return dependentes


def descrever_efeitos_do_acerto(acerto: Settlement) -> list[str]:
    efeitos = []
    for compra in _compras_do_acerto(acerto):
        efeitos.append(f"a compra {compra.code} e tudo que ela gerou:")
        efeitos.extend(f"  · {linha}" for linha in compra.descrever_efeitos())
    return efeitos


def aplicar_efeitos_do_acerto(acerto: Settlement, *, usuario) -> None:
    """Aprovar (e restaurar o que estava aprovado): uma compra por item recebido."""
    compromisso = acerto.commitment
    calculo = calcular_acerto(compromisso)
    if calculo.pendencias:
        raise BusinessError(
            "Não é possível aprovar o acerto: "
            + " ".join(p if p.endswith(".") else f"{p}." for p in calculo.pendencias)
        )

    criadas = []
    for dados in calculo.itens:
        if not dados.recebido:
            continue
        item, rateio = dados.item, calculo.rateios[dados.item.pk]
        campos = dict(
            date=dados.primeiro_recebimento,
            seller=compromisso.seller,
            destination_farm=compromisso.destination_farm,
            category=item.category,
            head_count=dados.cabecas_recebidas,
            total_weight_kg=dados.peso_recebido_kg,
            animal_value=rateio.animal_value,
            freight_value=rateio.freight_value,
            commission_value=rateio.commission_value,
            tax_value=rateio.tax_value,
            lot=item.lot,
            payment_days=compromisso.payment_days,
            notes=f"Gerada pelo acerto {acerto.code} (compromisso {compromisso.code}).",
        )
        compra = item.purchase
        if compra is None:
            compra = compras.criar_compra(usuario=usuario, **campos)
            item.purchase = compra
            item.save(update_fields=["purchase"])
            compras.confirmar_compra(compra, usuario=usuario)
        elif compra.status == Status.EXCLUIDA:
            # Restauração: a compra volta com os valores de agora.
            for campo, valor in campos.items():
                setattr(compra, campo, valor)
            compra.season = compras.season_para_data(compra.date)
            compra.save()
            reversible.restaurar(compra, usuario=usuario)
        else:
            raise BusinessError(
                f"O item {item.number} já tem a compra {compra.code} confirmada."
            )
        criadas.append(compra)

    if acerto.approved_at is None:
        acerto.approved_by = usuario
        acerto.approved_at = timezone.now()
    registrar_operacao(
        entity=acerto,
        title="Acerto aprovado",
        description=(
            f"{len(criadas)} compra(s) gerada(s); custo de aquisição "
            f"{dinheiro_br(calculo.custo_aquisicao)}; líquido ao produtor "
            f"{dinheiro_br(calculo.liquido_ao_produtor)}."
        ),
        previous_status=Status.RASCUNHO,
        new_status=Status.CONFIRMADA,
        document=acerto.code,
        actor=usuario,
    )


def desfazer_efeitos_do_acerto(acerto: Settlement, *, usuario) -> None:
    """Exclui as compras do acerto (movimento, custos, títulos e lote saem na
    mesma cascata). O vínculo item → compra fica: é o que a restauração usa."""
    raiz = getattr(acerto, "cascade_root", None) or uuid.uuid4()
    acerto.cascade_root_usado = True
    motivo = f"Desfeito junto com o acerto {acerto.code}"
    for compra in _compras_do_acerto(acerto):
        reversible.excluir(
            compra, usuario=usuario, motivo=motivo, cascata=True, raiz=raiz
        )
