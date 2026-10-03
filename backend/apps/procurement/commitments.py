"""Escrita do compromisso, dos itens e da comissão.

Aprovar o compromisso (`confirmar`) é o momento em que a regra de comissão é
**copiada** para o compromisso (snapshot): mudar `CommissionRule` depois não
toca a operação (docs/roadmap/fase-5, "dois pontos de cuidado").
"""

from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria, registrar_operacao
from apps.commercial.commission import escolher_regra
from apps.commercial.payment import aplicar_condicao
from apps.core import reversible
from apps.core.exceptions import (
    BlockingDependencyError,
    Bloqueio,
    BusinessError,
)
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.serialization import diff_fields, snapshot
from apps.herd.permissions import (
    pode_lancar_em_safra_encerrada,
    tem_acesso_de_escrita_a_fazenda,
)
from apps.herd.services import season_para_data
from apps.livestock.models import LotStatus
from apps.organizations.models import Season, SeasonStatus
from apps.partners.models import PartnerRoleChoice
from apps.procurement import selectors
from apps.procurement.codes import proximo_numero_da_operacao
from apps.procurement.lines import sincronizar_linhas
from apps.procurement.models import (
    Commission,
    CommissionSource,
    Commitment,
    CommitmentItem,
    PriceBasis,
)
from apps.procurement.permissions import (
    pode_aprovar_o_compromisso,
    pode_encerrar_a_operacao,
    pode_lancar_no_ciclo,
)

#: Os mesmos papéis que a compra aceita como vendedor: o item vira uma
#: `Purchase`, e ela recusaria qualquer outro.
PAPEIS_DE_PRODUTOR = (PartnerRoleChoice.PRODUTOR, PartnerRoleChoice.FORNECEDOR)

CAMPOS_EDITAVEIS = (
    "date",
    "seller",
    "destination_farm",
    "commissioned",
    "origin_property",
    "origin_city",
    "payment_days",
    "payment_condition",
    "pickup_date",
    "slaughter_date",
    "trucks",
    "distance_km",
    "notes",
)

CAMPOS_DO_ITEM = (
    "number",
    "category",
    "product_code",
    "head_count",
    "avg_weight_kg",
    "price_basis",
    "unit_price",
    "price_band_1",
    "price_band_2",
    "price_band_3",
    "price_band_4",
    "price_band_5",
    "expected_arrobas",
    "expected_band",
    "entry_yield_percent",
    "lot",
)


# --------------------------------------------------------------------------
# Trava de fechamento
# --------------------------------------------------------------------------


def bloqueio_do_acerto_aprovado(acerto, acao: str = "mudar isto") -> Bloqueio:
    """O caminho está na mensagem: reabrir o acerto (regras-negocio/06)."""
    return Bloqueio(
        texto=(
            f"o acerto {acerto.code} está aprovado e trava os valores. "
            f"Para {acao}, reabra o acerto antes (com motivo): as compras, "
            "os custos e os títulos que ele gerou são desfeitos."
        ),
        url=reverse("procurement:acerto_detalhe", args=[acerto.pk]),
        rotulo_url="Ir para o acerto",
    )


def exigir_acerto_aberto(commitment: Commitment, acao: str = "mudar isto") -> None:
    """Acerto aprovado impede edição livre dos valores consolidados."""
    acerto = selectors.acerto_aprovado(commitment)
    if acerto is not None:
        raise BlockingDependencyError(
            f"Não é possível prosseguir: {bloqueio_do_acerto_aprovado(acerto, acao)}"
        )


def exigir_operacao_aberta(commitment: Commitment, acao: str = "mudar isto") -> None:
    """Operação **encerrada** não recebe lançamento: reabra-a antes (com motivo)."""
    if commitment.encerrada:
        raise BlockingDependencyError(
            f"Não é possível prosseguir: a operação {commitment.code} está encerrada "
            f"desde {commitment.closed_at:%d/%m/%Y}. Para {acao}, reabra a operação "
            "antes (com motivo)."
        )


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------


def _validar_compromisso(dados: dict, *, usuario) -> Season:
    if dados["date"] > timezone.localdate():
        raise BusinessError("Compromisso com data de movimento futura não é permitido.")
    farm = dados["destination_farm"]
    if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")

    seller = dados["seller"]
    if not seller.roles.filter(role__in=PAPEIS_DE_PRODUTOR).exists():
        raise BusinessError(
            f"{seller} não tem o papel de Produtor nem de Fornecedor. "
            "Acrescente o papel no cadastro do parceiro."
        )
    parceiro = dados.get("commissioned")
    if (
        parceiro is not None
        and not parceiro.roles.filter(role=PartnerRoleChoice.COMISSIONADO).exists()
    ):
        raise BusinessError(
            f"{parceiro} não tem o papel de Comissionado, exigido para o comprador."
        )

    retirada, abate = dados.get("pickup_date"), dados.get("slaughter_date")
    if retirada and abate and abate < retirada:
        raise BusinessError("O abate não pode ser antes da retirada.")
    for campo, rotulo in (("trucks", "caminhões"), ("distance_km", "distância")):
        valor = dados.get(campo)
        if valor is not None and valor < 0:
            raise BusinessError(f"A quantidade de {rotulo} não pode ser negativa.")

    season = season_para_data(dados["date"])
    if season is None:
        raise BusinessError(
            "Não há safra cadastrada que cubra esta data. Cadastre a safra antes."
        )
    if season.status == SeasonStatus.ENCERRADA and not pode_lancar_em_safra_encerrada(
        usuario
    ):
        raise BusinessError(
            f"A safra {season.name} está encerrada. Só o administrador pode "
            "lançar nela — reabra a safra antes, ou lance na safra corrente."
        )
    return season


def _validar_item(entrada: dict, *, farm) -> None:
    numero = entrada.get("number")
    rotulo = f"Item {numero}" if numero else "Item"
    if not (entrada.get("head_count") or 0) > 0:
        raise BusinessError(f"{rotulo}: informe as cabeças previstas (mais de zero).")
    categoria = entrada["category"]
    if not categoria.is_active:
        raise BusinessError(f"{rotulo}: a categoria {categoria} está inativa.")

    base = entrada.get("price_basis") or PriceBasis.ARROBA
    faixas = [entrada.get(f"price_band_{n}") for n in range(1, 6)]
    for n, preco in enumerate(faixas, start=1):
        if preco is not None and Decimal(preco) <= 0:
            raise BusinessError(
                f"{rotulo}: o preço da Faixa {n} deve ser maior que zero."
            )
    if base == PriceBasis.ARROBA and not any(faixas):
        raise BusinessError(
            f"{rotulo}: informe o preço de pelo menos uma faixa (R$ por @)."
        )
    if base == PriceBasis.CABECA:
        preco = entrada.get("unit_price")
        if preco is None or Decimal(preco) <= 0:
            raise BusinessError(f"{rotulo}: informe o preço por cabeça.")

    esperada = entrada.get("expected_band")
    if esperada is not None:
        if not 1 <= esperada <= 5:
            raise BusinessError(f"{rotulo}: a faixa esperada vai de 1 a 5.")
        if entrada.get(f"price_band_{esperada}") is None:
            raise BusinessError(
                f"{rotulo}: a faixa esperada ({esperada}) não tem preço no contrato."
            )
    peso = entrada.get("avg_weight_kg")
    if peso is not None and Decimal(peso) <= 0:
        raise BusinessError(f"{rotulo}: o peso médio previsto deve ser maior que zero.")
    rendimento = entrada.get("entry_yield_percent")
    if rendimento is not None and not Decimal("1") <= Decimal(rendimento) <= Decimal(
        "100"
    ):
        raise BusinessError(f"{rotulo}: o rendimento de entrada fica entre 1% e 100%.")

    lote = entrada.get("lot")
    if lote is not None:
        if lote.farm_id != farm.pk:
            raise BusinessError(
                f"{rotulo}: o lote {lote.code} é da fazenda {lote.farm}, não de {farm}."
            )
        if lote.status == LotStatus.EXCLUIDO:
            raise BusinessError(f"{rotulo}: o lote {lote.code} foi excluído.")


def _completar(compromisso: Commitment, dados: dict) -> dict:
    return {
        campo: dados.get(campo, getattr(compromisso, campo))
        for campo in CAMPOS_EDITAVEIS
    }


# --------------------------------------------------------------------------
# Itens
# --------------------------------------------------------------------------


def _sincronizar_itens(
    compromisso: Commitment, itens: list[dict], *, usuario, motivo: str = ""
):
    """Cria, corrige e retira os itens. Item com viagem, romaneio ou compra
    não sai: tem coisa dependendo dele."""
    existentes = list(compromisso.items.all())
    usados = {i.number for i in existentes}
    proximo = max(usados, default=0)

    entradas = []
    for entrada in itens:
        entrada = dict(entrada)
        _validar_item(entrada, farm=compromisso.destination_farm)
        if entrada.get("id") is None and not entrada.get("number"):
            proximo += 1
            entrada["number"] = proximo
        entradas.append(entrada)

    if not entradas:
        raise BusinessError("O compromisso precisa de pelo menos um item.")

    def _impedir_retirada(item: CommitmentItem):
        if item.loads.exists() or item.gradings.exists() or item.purchase_id:
            raise BlockingDependencyError(
                f"Não é possível retirar o item {item.number}: ele já tem viagem, "
                "romaneio ou compra. Retire antes o que depende dele."
            )

    def _criar(entrada: dict) -> CommitmentItem:
        item = CommitmentItem(commitment=compromisso)
        for campo in CAMPOS_DO_ITEM:
            if campo in entrada:
                setattr(item, campo, entrada[campo])
        item.save()
        return item

    return sincronizar_linhas(
        existentes=existentes,
        entradas=entradas,
        campos=CAMPOS_DO_ITEM,
        criar=_criar,
        usuario=usuario,
        motivo=motivo,
        antes_de_retirar=_impedir_retirada,
    )


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


@transaction.atomic
def criar_compromisso(
    *, usuario, itens: list[dict], compradores: list[dict] | None = None, **dados
) -> Commitment:
    """Cria o compromisso em negociação (`RASCUNHO`). Não afeta nada.

    `compradores`: um ou mais, cada um com a sua comissão. O primeiro é o
    principal (`commissioned`).
    """
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para lançar compromissos.")
    if compradores:
        dados["commissioned"] = compradores[0]["partner"]
    dados = {campo: dados.get(campo) for campo in CAMPOS_EDITAVEIS} | {
        "origin_property": dados.get("origin_property") or "",
        "origin_city": dados.get("origin_city") or "",
        "notes": dados.get("notes") or "",
    }
    dados = aplicar_condicao(dados)
    season = _validar_compromisso(dados, usuario=usuario)
    season = Season.objects.select_for_update().get(pk=season.pk)

    compromisso = Commitment(**dados, season=season, created_by=usuario)
    compromisso.code = proximo_numero_da_operacao()
    compromisso.save()
    registrar_auditoria(
        action=AuditAction.CREATE,
        entity=compromisso,
        after=snapshot(compromisso),
        actor=usuario,
    )
    _sincronizar_itens(compromisso, itens, usuario=usuario)
    if compradores:
        _sincronizar_compradores(compromisso, compradores, usuario=usuario)
    return compromisso


@transaction.atomic
def editar_rascunho(
    compromisso: Commitment,
    dados: dict,
    itens: list[dict] | None,
    *,
    usuario,
    compradores: list[dict] | None = None,
) -> Commitment:
    """Rascunho se edita sem motivo (06#permissões): ainda não afeta nada."""
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.RASCUNHO:
        raise BusinessError(
            "Este compromisso já foi aprovado. Use a correção, que exige motivo."
        )
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para editar compromissos.")

    if compradores:
        dados = {**dados, "commissioned": compradores[0]["partner"]}
    novos = aplicar_condicao(
        _completar(compromisso, dados), atual=compromisso.payment_condition
    )
    compromisso.season = _validar_compromisso(novos, usuario=usuario)
    antes = snapshot(compromisso)
    for campo, valor in novos.items():
        setattr(compromisso, campo, valor)
    compromisso.updated_by = usuario
    compromisso.version += 1
    compromisso.save()
    depois = snapshot(compromisso)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=compromisso,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        actor=usuario,
    )
    if itens is not None:
        # Rascunho: tudo é livre, mas o helper pede motivo para corrigir linha.
        _sincronizar_itens(
            compromisso, itens, usuario=usuario, motivo="Edição do rascunho"
        )
    if compradores is not None:
        _sincronizar_compradores(
            compromisso, compradores, usuario=usuario, motivo="Edição do rascunho"
        )
    return compromisso


@transaction.atomic
def aprovar_compromisso(compromisso: Commitment, *, usuario) -> Commitment:
    """RASCUNHO → CONFIRMADA (aprovado). Grava o snapshot da comissão."""
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.RASCUNHO:
        raise BusinessError("Este compromisso já foi aprovado.")
    if not pode_aprovar_o_compromisso(usuario):
        raise BusinessError(
            "Você não tem permissão para aprovar compromissos. A aprovação é de "
            "administrador ou gestor."
        )
    if not compromisso.items.exists():
        raise BusinessError("O compromisso precisa de pelo menos um item.")
    compromisso.season = _validar_compromisso(
        _completar(compromisso, {}), usuario=usuario
    )
    return reversible.confirmar(compromisso, usuario=usuario)


@transaction.atomic
def editar_compromisso(
    compromisso: Commitment,
    dados: dict,
    itens: list[dict] | None,
    *,
    usuario,
    motivo: str,
    compradores: list[dict] | None = None,
) -> Commitment:
    """Compromisso aprovado: corrige com motivo. Acerto aprovado trava."""
    if compromisso.status == Status.RASCUNHO:
        return editar_rascunho(
            compromisso, dados, itens, usuario=usuario, compradores=compradores
        )
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar compromisso aprovado.")
    exigir_acerto_aberto(compromisso, "corrigir o compromisso")
    exigir_operacao_aberta(compromisso, "corrigir o compromisso")

    if compradores:
        dados = {**dados, "commissioned": compradores[0]["partner"]}
    novos = aplicar_condicao(
        _completar(compromisso, dados), atual=compromisso.payment_condition
    )
    novos["season"] = _validar_compromisso(novos, usuario=usuario)
    compromisso = reversible.editar(compromisso, novos, usuario=usuario, motivo=motivo)
    if itens is not None:
        _sincronizar_itens(compromisso, itens, usuario=usuario, motivo=motivo)
    if compradores is not None:
        _sincronizar_compradores(
            compromisso, compradores, usuario=usuario, motivo=motivo
        )
        # Comprador acrescentado sem valor informado recebe a regra vigente.
        garantir_comissao(compromisso, usuario=usuario)
    return compromisso


@transaction.atomic
def excluir_compromisso(
    compromisso: Commitment, *, usuario, motivo: str, cascata: bool = False
) -> Commitment:
    if compromisso.status == Status.RASCUNHO:
        if not pode_lancar_no_ciclo(usuario):
            raise BusinessError("Você não tem permissão para excluir este compromisso.")
    elif not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir compromisso aprovado.")
    return reversible.excluir(
        compromisso, usuario=usuario, motivo=motivo, cascata=cascata
    )


@transaction.atomic
def restaurar_compromisso(compromisso: Commitment, *, usuario) -> Commitment:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar compromisso.")
    if compromisso.bloqueios():
        raise BlockingDependencyError(
            f"Não é possível restaurar: {compromisso.bloqueios()[0]}"
        )
    if compromisso.approved_at is None:
        # Excluído ainda em negociação: volta em negociação. `restaurar`
        # genérico o devolveria **aprovado**, o que ninguém pediu.
        return _restaurar_como_rascunho(compromisso, usuario=usuario)
    return reversible.restaurar(compromisso, usuario=usuario)


def _restaurar_como_rascunho(registro, *, usuario):
    if registro.status != Status.EXCLUIDA:
        raise BusinessError("Só é possível restaurar um registro excluído.")
    registro = type(registro).objects.select_for_update().get(pk=registro.pk)
    antes = snapshot(registro)
    registro.status = Status.RASCUNHO
    registro.deleted_at = None
    registro.deleted_by = None
    registro.delete_reason = ""
    registro.save()
    registrar_auditoria(
        action=AuditAction.RESTORE,
        entity=registro,
        before=antes,
        after=snapshot(registro),
        actor=usuario,
    )
    return registro


# --------------------------------------------------------------------------
# Contrato ReversibleModel
# --------------------------------------------------------------------------


@transaction.atomic
def encerrar_operacao(compromisso: Commitment, *, usuario, observacao: str = ""):
    """Encerramento **manual** (cliente, 2026-10-03, pendência #29): o sistema
    não decide que a operação acabou porque as contas foram pagas. Guarda
    status, data, responsável e observação."""
    if not pode_encerrar_a_operacao(usuario):
        raise BusinessError(
            "Você não tem permissão para encerrar operações. O encerramento é de "
            "administrador ou gestor."
        )
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.CONFIRMADA:
        raise BusinessError("Só se encerra uma operação aprovada.")
    if compromisso.encerrada:
        raise BusinessError("Esta operação já está encerrada.")
    if selectors.acerto_aprovado(compromisso) is None:
        raise BusinessError(
            "Aprove o acerto antes de encerrar: sem ele a operação ainda não "
            "virou compra, custo e título."
        )
    antes = snapshot(compromisso)
    compromisso.closed_at = timezone.now()
    compromisso.closed_by = usuario
    compromisso.closure_note = (observacao or "").strip()
    compromisso.version += 1
    compromisso.updated_by = usuario
    compromisso.save()
    depois = snapshot(compromisso)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=compromisso,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=compromisso.closure_note or "Operação encerrada.",
        actor=usuario,
    )
    registrar_operacao(
        entity=compromisso,
        title="Operação encerrada",
        description=compromisso.closure_note or "Encerrada manualmente.",
        document=compromisso.code,
        actor=usuario,
    )
    return compromisso


@transaction.atomic
def reabrir_operacao(compromisso: Commitment, *, usuario, motivo: str):
    """Desfaz o encerramento (regra 5): com motivo, na auditoria."""
    if not pode_encerrar_a_operacao(usuario):
        raise BusinessError(
            "Você não tem permissão para reabrir operações. A reabertura é de "
            "administrador ou gestor."
        )
    if not (motivo or "").strip():
        raise BusinessError("Informe o motivo da reabertura da operação.")
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if not compromisso.encerrada:
        raise BusinessError("Esta operação não está encerrada.")
    antes = snapshot(compromisso)
    compromisso.closed_at = None
    compromisso.closed_by = None
    compromisso.closure_note = ""
    compromisso.version += 1
    compromisso.updated_by = usuario
    compromisso.save()
    depois = snapshot(compromisso)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=compromisso,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=motivo.strip(),
        actor=usuario,
    )
    registrar_operacao(
        entity=compromisso,
        title="Operação reaberta",
        description=f"Motivo: {motivo.strip()}",
        document=compromisso.code,
        actor=usuario,
    )
    return compromisso


def bloqueios_do_compromisso(compromisso: Commitment) -> list:
    bloqueios = []
    if compromisso.season.status == SeasonStatus.ENCERRADA:
        bloqueios.append(
            f"a safra {compromisso.season.name} está encerrada. Peça a um "
            "administrador para reabrir a safra antes de editar ou excluir."
        )
    acerto = selectors.acerto_aprovado(compromisso)
    if acerto is not None:
        bloqueios.append(bloqueio_do_acerto_aprovado(acerto, "mexer no compromisso"))
    if compromisso.encerrada:
        bloqueios.append(
            f"a operação {compromisso.code} está encerrada. Reabra a operação "
            "antes (com motivo)."
        )
    return bloqueios


def dependentes_do_compromisso(compromisso: Commitment) -> list:
    return [
        *selectors.viagens_ativas(compromisso).order_by("pickup_date", "id"),
        *(
            [acerto]
            if (acerto := selectors.acerto_ativo(compromisso)) is not None
            else []
        ),
    ]


def comissao_do(compromisso: Commitment) -> Commission | None:
    """A comissão do comprador principal. Por consulta, não pelo atributo: o
    cache guardaria o "não existe" e deixaria uma instância velha enxergando a
    comissão errada."""
    return Commitment.objects.get(pk=compromisso.pk).commission


def comissoes_do(compromisso: Commitment) -> list[Commission]:
    """Uma por comprador, na ordem em que foram informados."""
    return list(
        Commission.objects.filter(commitment=compromisso)
        .select_related("payee")
        .order_by("position", "id")
    )


def descrever_efeitos_do_compromisso(compromisso: Commitment) -> list[str]:
    efeitos = ["a aprovação do compromisso e o contrato dela"]
    for comissao in comissoes_do(compromisso):
        quem = f"{comissao.payee}: " if comissao.payee_id else ""
        efeitos.append(f"a comissão gravada ({quem}{comissao.regra_em_texto()})")
    return efeitos


def aplicar_efeitos_do_compromisso(compromisso: Commitment, *, usuario) -> None:
    """Aprovar: quem aprovou, quando, e a comissão gravada. Chamado também
    ao corrigir e ao restaurar — `approved_*` só é escrito na primeira vez."""
    if compromisso.approved_at is None:
        compromisso.approved_by = usuario
        compromisso.approved_at = timezone.now()
    garantir_comissao(compromisso, usuario=usuario)


# --------------------------------------------------------------------------
# Comissão: snapshot da regra
# --------------------------------------------------------------------------


def _categoria_unica(compromisso: Commitment):
    """A regra pode ser por categoria; só vale se todos os itens têm a mesma."""
    categorias = {item.category_id: item.category for item in compromisso.items.all()}
    return next(iter(categorias.values())) if len(categorias) == 1 else None


def _validar_comprador(entrada: dict, posicao: int) -> None:
    rotulo = f"Comprador {posicao}"
    parceiro = entrada.get("partner")
    if parceiro is None:
        raise BusinessError(f"{rotulo}: escolha o comprador.")
    if not parceiro.roles.filter(role=PartnerRoleChoice.COMISSIONADO).exists():
        raise BusinessError(
            f"{rotulo}: {parceiro} não tem o papel de Comissionado. Acrescente o "
            "papel no cadastro do parceiro."
        )
    tipo = entrada.get("type")
    if tipo not in ("PERCENTUAL", "POR_CABECA", "VALOR"):
        raise BusinessError(f"{rotulo}: escolha o tipo da comissão.")
    valor = Decimal(entrada.get("value") or 0)
    extra = Decimal(entrada.get("extra_amount") or 0)
    if valor < 0 or extra < 0:
        raise BusinessError(f"{rotulo}: a comissão não pode ser negativa.")
    if tipo == "PERCENTUAL" and valor > 100:
        raise BusinessError(f"{rotulo}: um percentual não passa de 100.")


def _sincronizar_compradores(
    compromisso: Commitment, compradores: list[dict], *, usuario, motivo: str = ""
) -> list[Commission]:
    """Os compradores do compromisso, cada um com a sua comissão **digitada**
    (cliente, 2026-10-03). Cria, corrige e retira as linhas de `Commission`;
    o primeiro é o principal. Quem ficou sem valor informado recebe, na
    aprovação, a regra vigente (`garantir_comissao`).

    Com o compromisso aprovado, corrigir exige motivo.
    """
    aprovado = compromisso.status != Status.RASCUNHO
    if aprovado and not (motivo or "").strip():
        raise BusinessError("Informe o motivo da correção dos compradores.")
    vistos = set()
    for posicao, entrada in enumerate(compradores, start=1):
        _validar_comprador(entrada, posicao)
        if entrada["partner"].pk in vistos:
            raise BusinessError(
                f"{entrada['partner']} aparece mais de uma vez nos compradores."
            )
        vistos.add(entrada["partner"].pk)

    existentes = {
        c.payee_id: c for c in Commission.objects.filter(commitment=compromisso)
    }
    resultado = []
    for posicao, entrada in enumerate(compradores, start=1):
        parceiro = entrada["partner"]
        valor = Decimal(entrada.get("value") or 0)
        extra = Decimal(entrada.get("extra_amount") or 0)
        # Sem valor e sem extra: o comprador entra "à espera da regra".
        sem_valor = valor == 0 and extra == 0
        atual = existentes.pop(parceiro.pk, None)
        antes = snapshot(atual) if atual else None
        linha = atual or Commission(commitment=compromisso, payee=parceiro)
        linha.position = posicao
        linha.type = entrada["type"]
        linha.base = "BRUTO"
        linha.value = valor
        linha.extra_amount = extra
        linha.due_date = entrada.get("due_date")
        if sem_valor and (atual is None or atual.source == CommissionSource.REGRA):
            linha.source, linha.rule = CommissionSource.REGRA, None
        else:
            linha.source, linha.rule = CommissionSource.MANUAL, None
        linha.save()
        depois = snapshot(linha)
        if antes != depois:
            registrar_auditoria(
                action=AuditAction.UPDATE if atual else AuditAction.CREATE,
                entity=linha,
                before=antes,
                after=depois,
                changed_fields=diff_fields(antes, depois) if antes else None,
                reason=motivo or "",
                actor=usuario,
            )
        resultado.append(linha)

    for sobra in existentes.values():
        if sobra.payee_id is None:
            continue  # comissão sem comprador (regra genérica): não some numa edição
        registrar_auditoria(
            action=AuditAction.DELETE,
            entity=sobra,
            before=snapshot(sobra),
            reason=motivo or "Comprador retirado do compromisso.",
            actor=usuario,
        )
        sobra.delete()

    principal = compradores[0]["partner"] if compradores else None
    if compromisso.commissioned_id != (principal.pk if principal else None):
        compromisso.commissioned = principal
        compromisso.save(update_fields=["commissioned"])
    return resultado


def _snapshot_da_regra(linha: Commission, compromisso: Commitment, *, usuario):
    """Copia a regra vigente para a linha que ficou sem comissão informada."""
    regra = escolher_regra(
        comissionado=linha.payee,
        categoria=_categoria_unica(compromisso),
        data=compromisso.date,
    )
    if regra is None:
        return linha
    antes = snapshot(linha) if linha.pk else None
    linha.source = CommissionSource.REGRA
    linha.rule = regra
    linha.type = regra.type
    linha.base = regra.base
    linha.value = regra.value
    linha.save()
    registrar_auditoria(
        action=AuditAction.UPDATE if antes else AuditAction.CREATE,
        entity=linha,
        before=antes,
        after=snapshot(linha),
        changed_fields=diff_fields(antes, snapshot(linha)) if antes else None,
        reason="Regra de comissão gravada na aprovação do compromisso.",
        actor=usuario,
    )
    return linha


def garantir_comissao(compromisso: Commitment, *, usuario) -> list[Commission]:
    """Na aprovação, copia a regra vigente para **cada comprador** que ainda não
    tem comissão informada — **uma vez**. Sem regra, nada é criado (a comissão
    fica "—" e pode ser informada à mão). Comissão digitada (`MANUAL`) ou já
    gravada nunca é sobrescrita.
    """
    linhas = comissoes_do(compromisso)
    principal = compromisso.commissioned
    if not any(
        linha.payee_id == (principal.pk if principal else None) for linha in linhas
    ):
        # Comprador principal sem linha: tenta a regra dele.
        nova = Commission(
            commitment=compromisso,
            payee=principal,
            position=1,
            type="PERCENTUAL",
            value=Decimal("0"),
        )
        if escolher_regra(
            comissionado=principal,
            categoria=_categoria_unica(compromisso),
            data=compromisso.date,
        ):
            linhas.insert(0, _snapshot_da_regra(nova, compromisso, usuario=usuario))
    for linha in linhas:
        espera_regra = (
            linha.source == CommissionSource.REGRA
            and linha.rule_id is None
            and linha.value == 0
            and linha.extra_amount == 0
        )
        if espera_regra:
            _snapshot_da_regra(linha, compromisso, usuario=usuario)
    return comissoes_do(compromisso)


@transaction.atomic
def definir_comissao(
    compromisso: Commitment,
    *,
    tipo: str,
    base: str = "BRUTO",
    valor: Decimal,
    extra: Decimal = Decimal("0"),
    favorecido=None,
    vencimento=None,
    usuario,
    motivo: str = "",
) -> Commission:
    """Comissão de **um comprador**, informada neste compromisso — ou correção
    da que foi gravada. Informar um comprador novo o acrescenta. Vale só para
    este compromisso."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para alterar a comissão.")
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.CONFIRMADA:
        raise BusinessError("A comissão se define depois da aprovação do compromisso.")
    exigir_acerto_aberto(compromisso, "mudar a comissão")
    exigir_operacao_aberta(compromisso, "mudar a comissão")
    if Decimal(valor) < 0 or Decimal(extra or 0) < 0:
        raise BusinessError("Comissão não pode ser negativa.")
    if tipo == "PERCENTUAL" and Decimal(valor) > 100:
        raise BusinessError("Um percentual não passa de 100.")
    if (
        favorecido is not None
        and not favorecido.roles.filter(role=PartnerRoleChoice.COMISSIONADO).exists()
    ):
        raise BusinessError(f"{favorecido} não tem o papel de Comissionado.")

    existente = Commission.objects.filter(
        commitment=compromisso, payee=favorecido
    ).first()
    if existente is not None and not (motivo or "").strip():
        raise BusinessError("Informe o motivo da correção da comissão.")
    antes = snapshot(existente) if existente else None
    comissao = existente or Commission(
        commitment=compromisso,
        payee=favorecido,
        position=Commission.objects.filter(commitment=compromisso).count() + 1,
    )
    comissao.source = CommissionSource.MANUAL
    comissao.rule = None
    comissao.type = tipo
    comissao.base = base or "BRUTO"
    comissao.value = valor
    comissao.extra_amount = extra or 0
    comissao.due_date = vencimento
    comissao.save()
    if compromisso.commissioned_id is None and favorecido is not None:
        compromisso.commissioned = favorecido
        compromisso.save(update_fields=["commissioned"])
    depois = snapshot(comissao)
    registrar_auditoria(
        action=AuditAction.UPDATE if existente else AuditAction.CREATE,
        entity=comissao,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois) if antes else None,
        reason=motivo,
        actor=usuario,
    )
    return comissao


@transaction.atomic
def retirar_comprador(
    compromisso: Commitment, comissao: Commission, *, usuario, motivo: str
) -> None:
    """Tira um comprador (e a comissão dele) do compromisso aprovado."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para alterar a comissão.")
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    exigir_acerto_aberto(compromisso, "retirar um comprador")
    exigir_operacao_aberta(compromisso, "retirar um comprador")
    if not (motivo or "").strip():
        raise BusinessError("Informe o motivo para retirar o comprador.")
    comissao = Commission.objects.get(pk=comissao.pk, commitment=compromisso)
    registrar_auditoria(
        action=AuditAction.DELETE,
        entity=comissao,
        before=snapshot(comissao),
        reason=motivo,
        actor=usuario,
    )
    era_principal = comissao.payee_id == compromisso.commissioned_id
    comissao.delete()
    if era_principal:
        proxima = comissoes_do(compromisso)
        compromisso.commissioned = proxima[0].payee if proxima else None
        compromisso.save(update_fields=["commissioned"])
