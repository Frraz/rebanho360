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
from apps.audit.services import registrar_auditoria
from apps.commercial.commission import escolher_regra
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
from apps.procurement.codes import proximo_codigo
from apps.procurement.lines import sincronizar_linhas
from apps.procurement.models import (
    Commission,
    CommissionSource,
    Commitment,
    CommitmentItem,
    PriceBasis,
)
from apps.procurement.permissions import pode_lancar_no_ciclo

#: Os mesmos papéis que a compra aceita como vendedor: o item vira uma
#: `Purchase`, e ela recusaria qualquer outro.
PAPEIS_DE_PRODUTOR = (PartnerRoleChoice.PRODUTOR, PartnerRoleChoice.FORNECEDOR)

CAMPOS_EDITAVEIS = (
    "date",
    "seller",
    "destination_farm",
    "commissioned",
    "second_buyer",
    "origin_property",
    "origin_city",
    "payment_days",
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
    for campo, rotulo in (
        ("commissioned", "comprador"),
        ("second_buyer", "comprador adicional"),
    ):
        parceiro = dados.get(campo)
        if (
            parceiro is not None
            and not parceiro.roles.filter(role=PartnerRoleChoice.COMISSIONADO).exists()
        ):
            raise BusinessError(
                f"{parceiro} não tem o papel de Comissionado, exigido para o {rotulo}."
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
def criar_compromisso(*, usuario, itens: list[dict], **dados) -> Commitment:
    """Cria o compromisso em negociação (`RASCUNHO`). Não afeta nada."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para lançar compromissos.")
    dados = {campo: dados.get(campo) for campo in CAMPOS_EDITAVEIS} | {
        "origin_property": dados.get("origin_property") or "",
        "origin_city": dados.get("origin_city") or "",
        "notes": dados.get("notes") or "",
    }
    season = _validar_compromisso(dados, usuario=usuario)
    season = Season.objects.select_for_update().get(pk=season.pk)

    compromisso = Commitment(**dados, season=season, created_by=usuario)
    compromisso.code = proximo_codigo(Commitment, "CM", season)
    compromisso.save()
    registrar_auditoria(
        action=AuditAction.CREATE,
        entity=compromisso,
        after=snapshot(compromisso),
        actor=usuario,
    )
    _sincronizar_itens(compromisso, itens, usuario=usuario)
    return compromisso


@transaction.atomic
def editar_rascunho(
    compromisso: Commitment, dados: dict, itens: list[dict] | None, *, usuario
) -> Commitment:
    """Rascunho se edita sem motivo (06#permissões): ainda não afeta nada."""
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.RASCUNHO:
        raise BusinessError(
            "Este compromisso já foi aprovado. Use a correção, que exige motivo."
        )
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para editar compromissos.")

    novos = _completar(compromisso, dados)
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
    return compromisso


@transaction.atomic
def aprovar_compromisso(compromisso: Commitment, *, usuario) -> Commitment:
    """RASCUNHO → CONFIRMADA (aprovado). Grava o snapshot da comissão."""
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.RASCUNHO:
        raise BusinessError("Este compromisso já foi aprovado.")
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para aprovar compromissos.")
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
) -> Commitment:
    """Compromisso aprovado: corrige com motivo. Acerto aprovado trava."""
    if compromisso.status == Status.RASCUNHO:
        return editar_rascunho(compromisso, dados, itens, usuario=usuario)
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar compromisso aprovado.")
    exigir_acerto_aberto(compromisso, "corrigir o compromisso")

    novos = _completar(compromisso, dados)
    novos["season"] = _validar_compromisso(novos, usuario=usuario)
    compromisso = reversible.editar(compromisso, novos, usuario=usuario, motivo=motivo)
    if itens is not None:
        _sincronizar_itens(compromisso, itens, usuario=usuario, motivo=motivo)
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
    """Por consulta, não pelo atributo: o acessor reverso guarda em cache o
    "não existe" e deixaria uma instância velha enxergando a comissão errada."""
    return Commission.objects.filter(commitment=compromisso).first()


def descrever_efeitos_do_compromisso(compromisso: Commitment) -> list[str]:
    efeitos = ["a aprovação do compromisso e o contrato dela"]
    comissao = comissao_do(compromisso)
    if comissao is not None:
        efeitos.append(f"a regra de comissão gravada ({comissao.regra_em_texto()})")
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


def garantir_comissao(compromisso: Commitment, *, usuario) -> Commission | None:
    """Copia a regra vigente para o compromisso — **uma vez**. Sem regra, não
    cria nada (a comissão fica "—" e pode ser informada à mão).

    Já existe: não se mexe, **exceto** se veio de regra e o comissionado do
    compromisso mudou — a regra de outra pessoa não vale para esta.
    """
    existente = comissao_do(compromisso)
    if existente is not None and not (
        existente.source == CommissionSource.REGRA
        and existente.payee_id != compromisso.commissioned_id
    ):
        return existente

    regra = escolher_regra(
        comissionado=compromisso.commissioned,
        categoria=_categoria_unica(compromisso),
        data=compromisso.date,
    )
    if regra is None:
        return existente

    antes = snapshot(existente) if existente else None
    comissao = existente or Commission(commitment=compromisso)
    comissao.payee = compromisso.commissioned
    comissao.source = CommissionSource.REGRA
    comissao.rule = regra
    comissao.type = regra.type
    comissao.base = regra.base
    comissao.value = regra.value
    comissao.save()
    registrar_auditoria(
        action=AuditAction.UPDATE if existente else AuditAction.CREATE,
        entity=comissao,
        before=antes,
        after=snapshot(comissao),
        changed_fields=diff_fields(antes, snapshot(comissao)) if antes else None,
        reason="Regra de comissão gravada na aprovação do compromisso.",
        actor=usuario,
    )
    return comissao


@transaction.atomic
def definir_comissao(
    compromisso: Commitment,
    *,
    tipo: str,
    base: str,
    valor: Decimal,
    extra: Decimal = Decimal("0"),
    favorecido=None,
    usuario,
    motivo: str = "",
) -> Commission:
    """Comissão informada **neste compromisso**, sem regra cadastrada — ou
    correção da que foi gravada. Vale só para este compromisso."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para alterar a comissão.")
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    if compromisso.status != Status.CONFIRMADA:
        raise BusinessError("A comissão se define depois da aprovação do compromisso.")
    exigir_acerto_aberto(compromisso, "mudar a comissão")
    if Decimal(valor) < 0 or Decimal(extra or 0) < 0:
        raise BusinessError("Comissão não pode ser negativa.")
    if tipo == "PERCENTUAL" and Decimal(valor) > 100:
        raise BusinessError("Um percentual não passa de 100.")
    if (
        favorecido is not None
        and not favorecido.roles.filter(role=PartnerRoleChoice.COMISSIONADO).exists()
    ):
        raise BusinessError(f"{favorecido} não tem o papel de Comissionado.")

    existente = comissao_do(compromisso)
    if existente is not None and not (motivo or "").strip():
        raise BusinessError("Informe o motivo da correção da comissão.")
    antes = snapshot(existente) if existente else None
    comissao = existente or Commission(commitment=compromisso)
    comissao.payee = favorecido
    comissao.source = CommissionSource.MANUAL
    comissao.rule = None
    comissao.type = tipo
    comissao.base = base
    comissao.value = valor
    comissao.extra_amount = extra or 0
    comissao.save()
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
