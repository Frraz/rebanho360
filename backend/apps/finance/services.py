"""Escrita. Toda operação que altera estado do financeiro passa por aqui.

Três disciplinas, as mesmas de compra e venda — com dinheiro em jogo:

1. **Idempotência.** Gerar título e dar baixa têm chave: `(operação,
   componente)` e `(título, documento)`. Clique duplo, duas abas ou duas pessoas
   chegam à mesma chave, e a segunda é recusada — no serviço, sob
   `select_for_update`, e no banco, por `UNIQUE`.
2. **Trava antes de decidir.** O título é lido com `select_for_update` no início
   de cada transição; o estado que vale é o de dentro da transação.
3. **Quem aprova não é quem executa.** Ver `_exigir_separacao_de_funcoes`.

Ver docs/regras-negocio/07-financeiro.md.
"""

import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria, registrar_operacao
from apps.core import reversible
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.formatting import dinheiro_br
from apps.core.permissions import pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.serialization import diff_fields, snapshot
from apps.costs.allocation import ratear_em_centavos
from apps.finance.models import (
    COMPONENTES_A_PAGAR,
    COMPONENTES_A_RECEBER,
    Component,
    Direction,
    Invoice,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from apps.finance.permissions import (
    PAPEIS_QUE_EXECUTAM_PAGAMENTO,
    pode_aprovar_pagamento,
    pode_desfazer_baixa,
    pode_executar_pagamento,
    pode_gerenciar_titulos,
)
from apps.herd.permissions import (
    pode_lancar_em_safra_encerrada,
    tem_acesso_de_escrita_a_fazenda,
)
from apps.herd.services import season_para_data
from apps.organizations.models import Season, SeasonStatus

#: Quanto da compra vira título, e em que componente (F4-02). Só os animais
#: têm favorecido conhecido (o vendedor); frete, comissão e impostos nascem
#: "a definir" — pendência #17.
COMPONENTES_DA_COMPRA = (
    ("animal_value", Component.ANIMAIS),
    ("freight_value", Component.FRETE),
    ("commission_value", Component.COMISSAO),
    ("tax_value", Component.IMPOSTOS),
)


# --------------------------------------------------------------------------
# Códigos
# --------------------------------------------------------------------------


def _rotulo_da_safra(season: Season) -> str:
    inicio, _, fim = season.name.partition("/")
    return f"{inicio}/{fim[-2:]}" if fim else season.name


def gerar_codigo_titulo(season: Season) -> str:
    """`TT-2025/26-0001` — sequência por safra. A safra é travada pelo
    chamador. Conta também os cancelados: número nunca é reaproveitado."""
    prefixo = f"TT-{_rotulo_da_safra(season)}-"
    existentes = Invoice.objects.filter(code__startswith=prefixo).count()
    return f"{prefixo}{existentes + 1:04d}"


def gerar_codigo_baixa(season: Season, direction: str) -> str:
    """`PG-2025/26-0001` (pagamento) ou `RC-2025/26-0001` (recebimento)."""
    sigla = "RC" if direction == Direction.RECEBER else "PG"
    prefixo = f"{sigla}-{_rotulo_da_safra(season)}-"
    existentes = Payment.objects.filter(code__startswith=prefixo).count()
    return f"{prefixo}{existentes + 1:04d}"


def conta_padrao(parceiro):
    """A conta do favorecido a usar: a padrão, ou a única que ele tem. Dado
    bancário vem do cadastro — nunca é digitado de novo (F4-01)."""
    if parceiro is None:
        return None
    contas = list(parceiro.bank_accounts.all()[:2])
    for conta in contas:
        if conta.is_default:
            return conta
    return contas[0] if len(contas) == 1 else None


# --------------------------------------------------------------------------
# Auditoria e linha do tempo
# --------------------------------------------------------------------------


def _registrar_transicao(
    titulo: Invoice,
    antes: dict,
    *,
    action: str,
    usuario,
    titulo_do_evento: str,
    descricao: str = "",
    motivo: str = "",
    situacao_anterior: str = "",
):
    depois = snapshot(titulo)
    registrar_auditoria(
        action=action,
        entity=titulo,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=motivo,
        actor=usuario,
    )
    registrar_operacao(
        entity=titulo,
        title=titulo_do_evento,
        description=descricao,
        previous_status=situacao_anterior,
        new_status=titulo.payment_status,
        document=titulo.code,
        actor=usuario,
    )


def _travar(titulo: Invoice) -> Invoice:
    # `of=("self",)`: travar só o título — `payee` é FK anulável, e o Postgres
    # não trava o lado anulável de um join.
    return (
        Invoice.objects.select_for_update(of=("self",))
        .select_related("season", "farm", "payee")
        .get(pk=titulo.pk)
    )


def _exigir_ativo(titulo: Invoice) -> None:
    if titulo.status == Status.EXCLUIDA:
        raise BusinessError(f"O título {titulo.code} foi cancelado.")


def _exigir_escrita_na_fazenda(titulo: Invoice, usuario) -> None:
    if not tem_acesso_de_escrita_a_fazenda(usuario, titulo.farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {titulo.farm}.")


# --------------------------------------------------------------------------
# Criar título (avulso) e validar
# --------------------------------------------------------------------------

CAMPOS_DO_TITULO = (
    "direction",
    "component",
    "farm",
    "payee",
    "bank_account",
    "origin_purchase",
    "origin_sale",
    "document",
    "issue_date",
    "due_date",
    "amount",
    "notes",
)


def _validar_titulo(dados: dict, *, usuario) -> Season:
    if Decimal(dados["amount"] or 0) <= 0:
        raise BusinessError("O valor do título deve ser maior que zero.")
    if dados["due_date"] < dados["issue_date"]:
        raise BusinessError("O vencimento não pode ser anterior à emissão.")

    direction = dados["direction"]
    if direction not in Direction.values:
        raise BusinessError("Informe se o título é a pagar ou a receber.")
    permitidos = (
        COMPONENTES_A_RECEBER if direction == Direction.RECEBER else COMPONENTES_A_PAGAR
    )
    if dados["component"] not in permitidos:
        raise BusinessError(
            "Esta origem não vale para título "
            f"{'a receber' if direction == Direction.RECEBER else 'a pagar'}."
        )
    if direction == Direction.PAGAR and dados.get("origin_sale"):
        raise BusinessError("Título a pagar não nasce de uma venda.")
    if direction == Direction.RECEBER and dados.get("origin_purchase"):
        raise BusinessError("Título a receber não nasce de uma compra.")
    if dados.get("origin_purchase") and dados.get("origin_sale"):
        raise BusinessError("O título tem uma operação de origem só.")

    farm = dados["farm"]
    if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")

    conta, payee = dados.get("bank_account"), dados.get("payee")
    if conta is not None and (payee is None or conta.partner_id != payee.pk):
        raise BusinessError(
            "A conta bancária escolhida não é do favorecido do título. Cadastre "
            "ou escolha uma conta dele em Parceiros."
        )

    season = season_para_data(dados["issue_date"])
    if season is None:
        raise BusinessError(
            "Não há safra cadastrada que cubra a data de emissão. Cadastre a safra antes."
        )
    if season.status == SeasonStatus.ENCERRADA and not pode_lancar_em_safra_encerrada(
        usuario
    ):
        raise BusinessError(
            f"A safra {season.name} está encerrada. Só o administrador pode "
            "lançar nela — reabra a safra antes, ou use uma emissão da safra corrente."
        )

    for campo in ("origin_purchase", "origin_sale"):
        origem = dados.get(campo)
        if origem is None:
            continue
        existente = (
            Invoice.objects.filter(
                **{campo: origem},
                component=dados["component"],
                status=Status.CONFIRMADA,
            )
            .exclude(pk=dados.get("_pk"))
            .first()
        )
        if existente is not None:
            raise BusinessError(
                f"Já existe o título {existente.code} de "
                f"{Component(dados['component']).label.lower()} para {origem}. "
                "Corrija o existente em vez de criar outro."
            )
    return season


@transaction.atomic
def criar_titulo(*, usuario, **dados) -> Invoice:
    """Título lançado à mão (frete que o vendedor não pagou, adiantamento…).
    Os que nascem da compra e da venda saem de `gerar_titulos_da_*`."""
    if not pode_gerenciar_titulos(usuario):
        raise BusinessError("Você não tem permissão para lançar títulos.")
    dados = {campo: dados.get(campo) for campo in CAMPOS_DO_TITULO} | {
        "document": dados.get("document") or "",
        "notes": dados.get("notes") or "",
        "component": dados.get("component") or Component.OUTRO,
    }
    if dados["bank_account"] is None and dados["payee"] is not None:
        dados["bank_account"] = conta_padrao(dados["payee"])
    season = _validar_titulo(dados, usuario=usuario)
    season = Season.objects.select_for_update().get(pk=season.pk)

    titulo = Invoice(**dados, season=season, created_by=usuario)
    titulo.code = gerar_codigo_titulo(season)
    try:
        with transaction.atomic():
            titulo.status = Status.CONFIRMADA
            titulo.save()
    except IntegrityError as exc:
        raise BusinessError(
            "Já existe um título para esta operação e esta origem."
        ) from exc
    registrar_auditoria(
        action=AuditAction.CREATE, entity=titulo, after=snapshot(titulo), actor=usuario
    )
    registrar_operacao(
        entity=titulo,
        title="Título lançado",
        description=f"{dinheiro_br(titulo.amount)}, vencimento {titulo.due_date:%d/%m/%Y}.",
        new_status=titulo.payment_status,
        document=titulo.code,
        actor=usuario,
    )
    return titulo


# --------------------------------------------------------------------------
# Gerar a partir da operação (F4-02) — idempotente
# --------------------------------------------------------------------------


def _vencimento(data: datetime.date, prazo_em_dias) -> datetime.date:
    return data + datetime.timedelta(days=prazo_em_dias or 0)


def _sincronizar_titulo(
    *,
    campo_origem: str,
    origem,
    componente: str,
    direction: str,
    farm,
    season,
    payee,
    amount,
    issue_date: datetime.date,
    due_date: datetime.date,
    usuario,
    criar: bool,
    restaurar_cancelados: bool,
    seguir_favorecido: bool,
    ref: str = "",
) -> Invoice | None:
    """Cria, atualiza ou cancela o título `(origem, componente)` para ficar
    igual à operação. É a única porta de entrada dos títulos que nascem de
    compra ou venda — por isso é aqui que mora a idempotência.

    - Não existe: cria (se `criar` e houver valor).
    - Existe e a operação mudou: atualiza; **se mudou valor ou favorecido, a
      programação e a aprovação deixam de valer** (valiam para os dados antigos).
    - Existe e nada mudou: mantém tudo, inclusive a aprovação.
    - O valor da operação foi a zero: cancela o título.
    """
    titulo = (
        Invoice.objects.select_for_update()
        .filter(**{campo_origem: origem}, component=componente, ref=ref)
        .first()
    )
    tem_valor = amount is not None and Decimal(amount) > 0

    if titulo is None:
        if not (criar and tem_valor):
            return None
        titulo = Invoice(
            direction=direction,
            component=componente,
            ref=ref,
            season=season,
            farm=farm,
            payee=payee,
            bank_account=conta_padrao(payee),
            issue_date=issue_date,
            due_date=due_date,
            amount=amount,
            status=Status.CONFIRMADA,
            created_by=usuario,
            **{campo_origem: origem},
        )
        titulo.code = gerar_codigo_titulo(
            Season.objects.select_for_update().get(pk=season.pk)
        )
        try:
            with transaction.atomic():
                titulo.save()
        except IntegrityError:
            # Outra transação criou o mesmo título entre a leitura e a escrita:
            # a chave `(origem, componente)` fez o trabalho dela. Vale o que ficou.
            return Invoice.objects.get(
                **{campo_origem: origem}, component=componente, ref=ref
            )
        registrar_auditoria(
            action=AuditAction.CREATE,
            entity=titulo,
            after=snapshot(titulo),
            actor=usuario,
        )
        registrar_operacao(
            entity=titulo,
            title=f"Título gerado pela operação {origem}",
            description=(
                f"{dinheiro_br(titulo.amount)}, vencimento {titulo.due_date:%d/%m/%Y}."
            ),
            new_status=titulo.payment_status,
            document=titulo.code,
            actor=usuario,
        )
        return titulo

    if not tem_valor:
        if titulo.status == Status.CONFIRMADA:
            _cancelar_com_a_origem(titulo, origem, usuario=usuario)
        return titulo

    if titulo.status == Status.EXCLUIDA:
        if not (titulo.voided_with_origin or restaurar_cancelados):
            return titulo  # cancelado à mão: continua cancelado
        reversible.restaurar(titulo, usuario=usuario)
        titulo = Invoice.objects.select_for_update().get(pk=titulo.pk)

    antes = snapshot(titulo)
    mudou_o_que_o_pagamento_depende = amount != titulo.amount or (
        seguir_favorecido and payee is not None and payee.pk != titulo.payee_id
    )
    if amount != titulo.amount:
        titulo.amount = amount
    if seguir_favorecido and payee is not None:
        if payee.pk != titulo.payee_id:
            titulo.payee = payee
            titulo.bank_account = conta_padrao(payee)
    titulo.farm, titulo.season = farm, season
    # O vencimento acompanha a operação só quando a data dela muda: depois de
    # gerado, o prazo se ajusta no próprio título.
    if titulo.issue_date != issue_date:
        titulo.issue_date, titulo.due_date = issue_date, due_date
        mudou_o_que_o_pagamento_depende = True
    elif ref and not ref.startswith("parcela") and titulo.due_date != due_date:
        # Título com vencimento **próprio** (frete, comissão, tributo, parcela):
        # o vencimento é dado da origem, não ajuste do título.
        titulo.due_date = due_date
        mudou_o_que_o_pagamento_depende = True
    titulo.voided_with_origin = False
    if mudou_o_que_o_pagamento_depende:
        _anular_programacao(titulo)
    titulo.updated_by = usuario
    titulo.version += 1
    titulo.save()
    depois = snapshot(titulo)
    if depois != antes:
        registrar_auditoria(
            action=AuditAction.UPDATE,
            entity=titulo,
            before=antes,
            after=depois,
            changed_fields=diff_fields(antes, depois),
            reason=f"Acompanha a correção da operação {origem}.",
            actor=usuario,
        )
    return titulo


def _anular_programacao(titulo: Invoice) -> None:
    """Valor, favorecido ou vencimento mudaram: o que foi programado e
    aprovado valia para os dados antigos. Volta a `A_PAGAR`."""
    if titulo.payment_status in (PaymentStatus.PROGRAMADO, PaymentStatus.APROVADO):
        titulo.payment_status = PaymentStatus.A_PAGAR
    titulo.scheduled_date = None
    titulo.scheduled_by = None
    titulo.approved_by = None
    titulo.approved_at = None


def _cancelar_com_a_origem(titulo: Invoice, origem, *, usuario, raiz=None) -> None:
    motivo = f"Desfeito junto com {origem._meta.verbose_name.lower()} {origem}"
    reversible.excluir(titulo, usuario=usuario, motivo=motivo, cascata=True, raiz=raiz)
    Invoice.objects.filter(pk=titulo.pk).update(voided_with_origin=True)


def _dados_da_compra(compra):
    return dict(
        campo_origem="origin_purchase",
        origem=compra,
        direction=Direction.PAGAR,
        farm=compra.destination_farm,
        season=compra.season,
        issue_date=compra.date,
        due_date=_vencimento(compra.date, compra.payment_days),
        usuario=None,
    )


def _dados_da_venda(venda):
    return dict(
        campo_origem="origin_sale",
        origem=venda,
        direction=Direction.RECEBER,
        farm=venda.farm,
        season=venda.season,
        issue_date=venda.date,
        due_date=_vencimento(venda.date, venda.payment_days),
        usuario=None,
    )


def _parcelas(
    operacao, valor, data: datetime.date
) -> list[tuple[str, Decimal, datetime.date]]:
    """`[(ref, valor, vencimento)]`: um título só (`ref` vazio) ou uma parcela por
    prazo da condição de pagamento parcelada (`parcela:1`, `parcela:2`…). O valor
    se divide em centavos exatos, a última parcela fecha a conta."""
    condicao = getattr(operacao, "payment_condition", None)
    if condicao is None or not condicao.parcelado:
        return [("", valor, _vencimento(data, operacao.payment_days))]
    prazos = condicao.prazos
    valor = Decimal(valor)
    fatias = ratear_em_centavos(valor, {i: Decimal(1) for i in range(len(prazos))})
    return [
        (f"parcela:{i + 1}", fatias[i], _vencimento(data, prazo))
        for i, prazo in enumerate(prazos)
    ]


def _cancelar_obsoletos(base: dict, componente: str, refs_vigentes: set, *, usuario):
    """Título do componente cuja `ref` não faz mais parte da operação (a condição
    deixou de ser parcelada, a viagem saiu…) é cancelado junto com a origem."""
    origem = base["origem"]
    for titulo in Invoice.objects.select_for_update().filter(
        **{base["campo_origem"]: origem},
        component=componente,
        status=Status.CONFIRMADA,
    ):
        if titulo.ref not in refs_vigentes:
            _cancelar_com_a_origem(titulo, origem, usuario=usuario)


def _sincronizar_compra(
    compra, *, usuario, criar, restaurar_cancelados
) -> list[Invoice]:
    base = _dados_da_compra(compra) | {"usuario": usuario}
    # Compra que nasceu de um acerto sabe pagar o vendedor pelo líquido; frete,
    # comissão e tributos têm título próprio, do acerto (ver
    # `gerar_titulos_do_acerto`). Compra direta: `{}`, igual a antes.
    from apps.procurement.settlement import ajustes_financeiros_da_compra

    ajustes = ajustes_financeiros_da_compra(compra)
    somente_animais = ajustes.get("somente_animais", False)
    titulos = []
    for campo, componente in COMPONENTES_DA_COMPRA:
        if somente_animais and componente != Component.ANIMAIS:
            continue
        ajuste = ajustes.get(componente, {})
        favorecido = compra.seller if componente == Component.ANIMAIS else None
        valor = ajuste.get("amount", getattr(compra, campo))
        if componente == Component.ANIMAIS and valor and Decimal(valor) > 0:
            parcelas = _parcelas(compra, valor, compra.date)
        else:
            parcelas = [("", valor, base["due_date"])]
        for ref, valor_da_parcela, vencimento in parcelas:
            titulo = _sincronizar_titulo(
                **(base | {"due_date": vencimento}),
                componente=componente,
                payee=favorecido,
                amount=valor_da_parcela,
                criar=criar,
                restaurar_cancelados=restaurar_cancelados,
                seguir_favorecido=componente == Component.ANIMAIS,
                ref=ref,
            )
            if titulo is not None:
                titulos.append(titulo)
        if componente == Component.ANIMAIS:
            _cancelar_obsoletos(
                base, componente, {ref for ref, _, _ in parcelas}, usuario=usuario
            )
    return titulos


def _sincronizar_venda(venda, *, usuario, criar, restaurar_cancelados) -> list[Invoice]:
    base = _dados_da_venda(venda) | {"usuario": usuario}
    parcelas = _parcelas(venda, venda.total_value, venda.date)
    titulos = []
    for ref, valor, vencimento in parcelas:
        titulo = _sincronizar_titulo(
            **(base | {"due_date": vencimento}),
            componente=Component.VENDA,
            payee=venda.buyer,
            amount=valor,
            criar=criar,
            restaurar_cancelados=restaurar_cancelados,
            seguir_favorecido=True,
            ref=ref,
        )
        if titulo is not None:
            titulos.append(titulo)
    _cancelar_obsoletos(
        base, Component.VENDA, {ref for ref, _, _ in parcelas}, usuario=usuario
    )
    return titulos


# --------------------------------------------------------------------------
# Títulos do acerto: frete por viagem, comissão por comprador, tributos por
# linha — cada um com favorecido e vencimento próprios (cliente, 2026-10-03)
# --------------------------------------------------------------------------


def gerar_titulos_do_acerto(acerto, calculo, *, usuario) -> list[Invoice]:
    """Idempotente (chave `(acerto, componente, ref)`). Chamado na aprovação do
    acerto, depois das compras.

    - **Frete**: um título por viagem, ao transportador dela;
    - **Comissão**: um título por comprador, a ele;
    - **Tributos e taxas** (efeito de custo): um título por linha, ao
      favorecido que o usuário informou — o sistema não presume o destinatário.

    O vencimento de cada um é o próprio (viagem, comprador, linha); sem ele,
    vence na data do acerto. Independem do vencimento dos animais.
    """
    from apps.procurement.settlement import Tratamento, efeito_da_linha

    compromisso = acerto.commitment
    base = dict(
        campo_origem="origin_settlement",
        origem=acerto,
        direction=Direction.PAGAR,
        farm=compromisso.destination_farm,
        season=compromisso.season,
        issue_date=acerto.date,
        usuario=usuario,
        criar=True,
        restaurar_cancelados=False,
        seguir_favorecido=True,
    )
    esperados: dict[str, set] = {
        Component.FRETE: set(),
        Component.COMISSAO: set(),
        Component.IMPOSTOS: set(),
    }
    titulos = []

    def _emitir(componente, ref, favorecido, valor, vencimento):
        if not valor or Decimal(valor) <= 0:
            return
        esperados[componente].add(ref)
        titulo = _sincronizar_titulo(
            **(base | {"due_date": vencimento or acerto.date}),
            componente=componente,
            payee=favorecido,
            amount=valor,
            ref=ref,
        )
        if titulo is not None:
            titulos.append(titulo)

    for frete in calculo.fretes:
        _emitir(
            Component.FRETE,
            f"viagem:{frete.viagem.pk}",
            frete.favorecido,
            frete.valor,
            frete.vencimento,
        )
    for comissao in calculo.comissoes:
        _emitir(
            Component.COMISSAO,
            f"comissao:{comissao.commission.pk}",
            comissao.payee,
            comissao.total,
            comissao.commission.due_date,
        )
    for linha in calculo.linhas:
        if efeito_da_linha(linha) == Tratamento.CUSTO:
            _emitir(
                Component.IMPOSTOS,
                f"linha:{linha.pk}",
                linha.payee,
                linha.amount,
                linha.due_date,
            )
    for componente, refs in esperados.items():
        _cancelar_obsoletos(base, componente, refs, usuario=usuario)
    return titulos


def desfazer_titulos_do_acerto(acerto, *, usuario, raiz) -> None:
    """Reabrir ou excluir o acerto cancela os títulos dele, na mesma cascata.
    Baixa já feita bloqueia antes de chegar aqui (`bloqueios_do_acerto`)."""
    for titulo in acerto.invoices.filter(status=Status.CONFIRMADA):
        _cancelar_com_a_origem(titulo, acerto, usuario=usuario, raiz=raiz)


def gerar_titulos_da_compra(compra, *, usuario, restaurar_cancelados=False):
    """Idempotente: chamar duas vezes — ou duas pessoas ao mesmo tempo — gera
    **um** título por componente. Chamado na confirmação da compra."""
    if compra.status != Status.CONFIRMADA:
        raise BusinessError("Só uma compra confirmada gera títulos.")
    return _sincronizar_compra(
        compra, usuario=usuario, criar=True, restaurar_cancelados=restaurar_cancelados
    )


def gerar_titulos_da_venda(venda, *, usuario, restaurar_cancelados=False):
    if venda.status != Status.CONFIRMADA:
        raise BusinessError("Só uma venda confirmada gera títulos.")
    return _sincronizar_venda(
        venda, usuario=usuario, criar=True, restaurar_cancelados=restaurar_cancelados
    )


@transaction.atomic
def gerar_titulos_de_operacao_existente(operacao, *, usuario):
    """O botão "Gerar títulos" de uma compra ou venda que já estava confirmada
    antes do financeiro existir (as do histórico, por exemplo)."""
    if not pode_gerenciar_titulos(usuario):
        raise BusinessError("Você não tem permissão para lançar títulos.")
    tipo = type(operacao)
    operacao = tipo.objects.select_for_update().get(pk=operacao.pk)
    farm = getattr(operacao, "destination_farm", None) or operacao.farm
    if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")
    if tipo.__name__ == "Purchase":
        return gerar_titulos_da_compra(
            operacao, usuario=usuario, restaurar_cancelados=True
        )
    return gerar_titulos_da_venda(operacao, usuario=usuario, restaurar_cancelados=True)


def sincronizar_da_compra(compra, *, usuario) -> None:
    """Chamado ao aplicar os efeitos da compra (correção ou restauração).
    Só mexe se a compra já tem título: compra do histórico, que nunca passou
    pelo financeiro, não ganha título por ter sido corrigida."""
    if compra.invoices.exists():
        _sincronizar_compra(
            compra, usuario=usuario, criar=True, restaurar_cancelados=False
        )


def sincronizar_da_venda(venda, *, usuario) -> None:
    if venda.invoices.exists():
        _sincronizar_venda(
            venda, usuario=usuario, criar=True, restaurar_cancelados=False
        )


def desfazer_titulos_da_origem(origem, *, usuario, raiz) -> None:
    """Chamado ao desfazer os efeitos da compra/venda: os títulos em aberto
    saem junto, na mesma cascata (mesma `cascade_root`). Com baixa o desfazer
    nem chega aqui — `bloqueios()` da operação barra antes."""
    for titulo in origem.invoices.filter(status=Status.CONFIRMADA):
        _cancelar_com_a_origem(titulo, origem, usuario=usuario, raiz=raiz)


def descrever_titulos_da_origem(origem) -> list[str]:
    """Para a análise de impacto e a tela de confirmação. Rascunho: o que
    confirmar vai **gerar**. Confirmada: o que desfazer vai **cancelar**."""
    if origem.status == Status.RASCUNHO:
        if hasattr(origem, "destination_farm"):
            base = _dados_da_compra(origem)
            itens = [
                (componente, getattr(origem, campo))
                for campo, componente in COMPONENTES_DA_COMPRA
            ]
            verbo = "a pagar"
        else:
            base = _dados_da_venda(origem)
            itens = [(Component.VENDA, origem.total_value)]
            verbo = "a receber"
        return [
            f"gera o título {verbo} de {Component(componente).label.lower()}: "
            f"{dinheiro_br(valor)}, vencimento {base['due_date']:%d/%m/%Y}"
            for componente, valor in itens
            if valor and Decimal(valor) > 0
        ]
    frases = []
    for titulo in origem.invoices.filter(status=Status.CONFIRMADA).select_related(
        "payee"
    ):
        tipo = "a receber" if titulo.a_receber else "a pagar"
        frases.append(
            f"o título {tipo} {titulo.code} ({titulo.get_component_display().lower()}, "
            f"{dinheiro_br(titulo.amount)}) é cancelado"
        )
    return frases


# --------------------------------------------------------------------------
# Editar, excluir, restaurar o título
# --------------------------------------------------------------------------

#: Com operação de origem, valor e favorecido (de animais e venda) vêm dela.
CAMPOS_LIVRES_COM_ORIGEM = ("bank_account", "document", "due_date", "notes")
CAMPOS_LIVRES_SEM_ORIGEM = (
    "component",
    "farm",
    "payee",
    "bank_account",
    "document",
    "issue_date",
    "due_date",
    "amount",
    "notes",
)


def campos_editaveis(titulo: Invoice) -> tuple[str, ...]:
    if titulo.origem is None:
        return CAMPOS_LIVRES_SEM_ORIGEM
    campos = CAMPOS_LIVRES_COM_ORIGEM
    if titulo.component not in (Component.ANIMAIS, Component.VENDA):
        campos = ("payee", *campos)
    return campos


@transaction.atomic
def editar_titulo(titulo: Invoice, dados: dict, *, usuario, motivo: str) -> Invoice:
    """Corrige um título que ainda não recebeu baixa, com motivo. Valor,
    favorecido, conta ou vencimento diferentes anulam a programação e a
    aprovação: elas valiam para os dados antigos."""
    if not pode_gerenciar_titulos(usuario):
        raise BusinessError("Você não tem permissão para editar títulos.")
    titulo = _travar(titulo)
    _exigir_ativo(titulo)
    _exigir_escrita_na_fazenda(titulo, usuario)
    bloqueios = titulo.bloqueios()
    if bloqueios:
        raise BlockingDependencyError(f"Não é possível editar: {bloqueios[0]}")

    permitidos = campos_editaveis(titulo)
    novos = {campo: dados.get(campo, getattr(titulo, campo)) for campo in permitidos}
    completos = {
        campo: novos.get(campo, getattr(titulo, campo)) for campo in CAMPOS_DO_TITULO
    } | {"_pk": titulo.pk}
    if "payee" in novos and "bank_account" not in dados:
        # Trocou o favorecido: a conta antiga não é mais dele.
        if titulo.payee_id != (novos["payee"].pk if novos["payee"] else None):
            novos["bank_account"] = completos["bank_account"] = conta_padrao(
                novos["payee"]
            )
    season = _validar_titulo(completos, usuario=usuario)
    novos["season"] = season

    mudou = any(
        getattr(titulo, campo) != valor
        for campo, valor in novos.items()
        if campo in ("amount", "payee", "bank_account", "due_date")
    )
    if mudou and titulo.payment_status in (
        PaymentStatus.PROGRAMADO,
        PaymentStatus.APROVADO,
    ):
        novos.update(
            payment_status=PaymentStatus.A_PAGAR,
            scheduled_date=None,
            scheduled_by=None,
            approved_by=None,
            approved_at=None,
        )
    return reversible.editar(titulo, novos, usuario=usuario, motivo=motivo)


@transaction.atomic
def excluir_titulo(
    titulo: Invoice, *, usuario, motivo: str, cascata: bool = False
) -> Invoice:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir título.")
    return reversible.excluir(titulo, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar_titulo(titulo: Invoice, *, usuario) -> Invoice:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar título.")
    titulo = _travar(titulo)
    origem = titulo.origem
    if origem is not None and origem.status == Status.EXCLUIDA:
        raise BlockingDependencyError(
            f"Não é possível restaurar: {origem._meta.verbose_name.lower()} "
            f"{origem} está excluída. Restaure-a primeiro — o título volta junto."
        )
    if titulo.bloqueios():
        raise BlockingDependencyError(
            f"Não é possível restaurar: {titulo.bloqueios()[0]}"
        )
    titulo = reversible.restaurar(titulo, usuario=usuario)
    Invoice.objects.filter(pk=titulo.pk).update(voided_with_origin=False)
    titulo.voided_with_origin = False
    return titulo


# --------------------------------------------------------------------------
# Programar, aprovar (F4-03)
# --------------------------------------------------------------------------


def _exigir_a_pagar(titulo: Invoice) -> None:
    if titulo.a_receber:
        raise BusinessError(
            "Título a receber não passa por programação nem aprovação: "
            "registre o recebimento quando o dinheiro entrar."
        )


@transaction.atomic
def programar_titulo(
    titulo: Invoice, *, usuario, data: datetime.date, bank_account=None
) -> Invoice:
    """A_PAGAR → PROGRAMADO. Programar de novo (PROGRAMADO) troca a data."""
    if not pode_gerenciar_titulos(usuario):
        raise BusinessError("Você não tem permissão para programar pagamentos.")
    titulo = _travar(titulo)
    _exigir_ativo(titulo)
    _exigir_a_pagar(titulo)
    _exigir_escrita_na_fazenda(titulo, usuario)
    if titulo.payment_status not in (PaymentStatus.A_PAGAR, PaymentStatus.PROGRAMADO):
        raise BusinessError(
            f"O título {titulo.code} está '{titulo.situacao_rotulo.lower()}': só se "
            "programa título em aberto e ainda sem aprovação. Para mudar a data de "
            "um título aprovado, devolva-o antes."
        )
    if titulo.payee_id is None:
        raise BusinessError(
            f"O título {titulo.code} não tem favorecido. Informe a quem se paga "
            "(editar o título) antes de programar."
        )
    if data < datetime.date.today():
        raise BusinessError("A data programada não pode estar no passado.")
    if bank_account is not None and bank_account.partner_id != titulo.payee_id:
        raise BusinessError("A conta escolhida não é do favorecido do título.")

    antes = snapshot(titulo)
    anterior = titulo.payment_status
    titulo.payment_status = PaymentStatus.PROGRAMADO
    titulo.scheduled_date = data
    titulo.scheduled_by = usuario
    if bank_account is not None:
        titulo.bank_account = bank_account
    titulo.updated_by = usuario
    titulo.version += 1
    titulo.save()
    _registrar_transicao(
        titulo,
        antes,
        action=AuditAction.UPDATE,
        usuario=usuario,
        titulo_do_evento="Pagamento programado",
        descricao=f"Para {data:%d/%m/%Y}.",
        situacao_anterior=anterior,
    )
    return titulo


@transaction.atomic
def aprovar_titulo(titulo: Invoice, *, usuario) -> Invoice:
    """PROGRAMADO → APROVADO. Permissão própria (`finance.approve_payment`)."""
    if not pode_aprovar_pagamento(usuario):
        raise BusinessError("Você não tem permissão para aprovar pagamentos.")
    titulo = _travar(titulo)
    _exigir_ativo(titulo)
    _exigir_a_pagar(titulo)
    _exigir_escrita_na_fazenda(titulo, usuario)
    if titulo.payment_status == PaymentStatus.A_PAGAR:
        raise BusinessError(
            f"O título {titulo.code} ainda não foi programado: programe o "
            "pagamento antes de aprovar."
        )
    if titulo.payment_status != PaymentStatus.PROGRAMADO:
        raise BusinessError(
            f"O título {titulo.code} está '{titulo.situacao_rotulo.lower()}' "
            "e não pode ser aprovado agora."
        )

    antes = snapshot(titulo)
    anterior = titulo.payment_status
    titulo.payment_status = PaymentStatus.APROVADO
    titulo.approved_by = usuario
    titulo.approved_at = timezone.now()
    titulo.updated_by = usuario
    titulo.version += 1
    titulo.save()
    _registrar_transicao(
        titulo,
        antes,
        action=AuditAction.APPROVE,
        usuario=usuario,
        titulo_do_evento="Pagamento aprovado",
        descricao=(
            f"{dinheiro_br(titulo.amount)} para {titulo.payee}, "
            f"programado para {titulo.scheduled_date:%d/%m/%Y}."
        ),
        situacao_anterior=anterior,
    )
    return titulo


@transaction.atomic
def desprogramar_titulo(titulo: Invoice, *, usuario, motivo: str = "") -> Invoice:
    """PROGRAMADO/APROVADO → A_PAGAR. Tirar uma aprovação exige motivo e é
    prerrogativa de quem aprova."""
    if not pode_gerenciar_titulos(usuario):
        raise BusinessError("Você não tem permissão para devolver títulos.")
    titulo = _travar(titulo)
    _exigir_ativo(titulo)
    _exigir_a_pagar(titulo)
    _exigir_escrita_na_fazenda(titulo, usuario)
    if titulo.payment_status not in (PaymentStatus.PROGRAMADO, PaymentStatus.APROVADO):
        raise BusinessError(f"O título {titulo.code} não está programado nem aprovado.")
    if titulo.payment_status == PaymentStatus.APROVADO:
        if not pode_aprovar_pagamento(usuario):
            raise BusinessError("Só quem pode aprovar pagamentos desfaz uma aprovação.")
        if not motivo.strip():
            raise BusinessError("Informe o motivo para tirar a aprovação do título.")

    antes = snapshot(titulo)
    anterior = titulo.payment_status
    _anular_programacao(titulo)
    titulo.payment_status = PaymentStatus.A_PAGAR
    titulo.updated_by = usuario
    titulo.version += 1
    titulo.save()
    _registrar_transicao(
        titulo,
        antes,
        action=AuditAction.UPDATE,
        usuario=usuario,
        titulo_do_evento="Título devolvido a 'a pagar'",
        descricao="A programação e a aprovação foram retiradas.",
        motivo=motivo,
        situacao_anterior=anterior,
    )
    return titulo


# --------------------------------------------------------------------------
# Baixa (F4-04) — idempotente
# --------------------------------------------------------------------------


def executores_alternativos(titulo: Invoice, usuario) -> list:
    """Outros usuários ativos que podem dar baixa neste título — os que
    justificam recusar que quem aprovou também pague."""
    # O superusuário (suporte) não conta: é oculto, não pode ser citado como
    # "peça a ele" nem justificar a recusa.
    candidatos = User.objects.filter(
        is_active=True, is_superuser=False, role__in=PAPEIS_QUE_EXECUTAM_PAGAMENTO
    ).exclude(pk=usuario.pk)
    return [u for u in candidatos if tem_acesso_de_escrita_a_fazenda(u, titulo.farm)]


def _exigir_separacao_de_funcoes(titulo: Invoice, usuario) -> bool:
    """Quem aprova não é quem executa (F4-03). Se quem aprovou tenta pagar e
    **há outra pessoa** que possa fazê-lo, recusa e diz quem. Se for o único
    usuário financeiro, deixa passar — o sistema não pode trancar a operação
    — e a baixa sai marcada na auditoria. Devolve `True` nesse caso."""
    if titulo.a_receber or titulo.approved_by_id != usuario.pk:
        return False
    outros = executores_alternativos(titulo, usuario)
    if outros:
        nomes = ", ".join(sorted(str(u) for u in outros)[:3])
        raise BusinessError(
            "Quem aprova não é quem paga: você aprovou este título. Peça a outro "
            f"usuário financeiro para dar a baixa ({nomes})."
        )
    return True


def situacoes_que_aceitam_baixa(titulo: Invoice) -> tuple:
    """Pagar exige aprovação; receber, não. `PARCIAL` aceita mais baixas."""
    if titulo.a_receber:
        return (PaymentStatus.A_PAGAR, PaymentStatus.PARCIAL)
    return (PaymentStatus.APROVADO, PaymentStatus.PARCIAL)


def _situacao_sem_baixa(titulo: Invoice) -> str:
    if titulo.a_receber:
        return PaymentStatus.A_PAGAR
    if titulo.approved_at is not None:
        return PaymentStatus.APROVADO
    if titulo.scheduled_date is not None:
        return PaymentStatus.PROGRAMADO
    return PaymentStatus.A_PAGAR


def _total_baixado(titulo_id, *, incluir=None, excluir=None) -> Decimal:
    ativas = Payment.objects.filter(invoice_id=titulo_id, status=Status.CONFIRMADA)
    if excluir is not None:
        ativas = ativas.exclude(pk=excluir.pk)
    total = ativas.aggregate(t=Sum("amount"))["t"] or Decimal("0")
    if incluir is not None and not ativas.filter(pk=incluir.pk).exists():
        total += incluir.amount
    return total


def recalcular_situacao(titulo_id, *, incluir=None, excluir=None) -> Invoice:
    """A situação do pagamento a partir das baixas — a única função que a
    muda por causa de uma baixa. `incluir`/`excluir` dizem qual baixa conta
    agora, porque ela é chamada **antes** de a baixa mudar de estado."""
    titulo = Invoice.objects.select_for_update().get(pk=titulo_id)
    total = _total_baixado(titulo_id, incluir=incluir, excluir=excluir)
    if total > titulo.amount:
        raise BusinessError(
            f"O valor baixado ({dinheiro_br(total)}) ultrapassa o valor do título "
            f"{titulo.code} ({dinheiro_br(titulo.amount)})."
        )
    if total == titulo.amount:
        nova = PaymentStatus.PAGO
    elif total > 0:
        nova = PaymentStatus.PARCIAL
    else:
        nova = _situacao_sem_baixa(titulo)
    if nova != titulo.payment_status:
        anterior = titulo.payment_status
        titulo.payment_status = nova
        titulo.save(update_fields=["payment_status", "updated_at"])
        registrar_operacao(
            entity=titulo,
            title=f"Situação: {titulo.situacao_rotulo}",
            description=f"{dinheiro_br(total)} de {dinheiro_br(titulo.amount)} baixados.",
            previous_status=anterior,
            new_status=nova,
            document=titulo.code,
        )
    return titulo


@transaction.atomic
def baixar_titulo(
    titulo: Invoice,
    *,
    usuario,
    date: datetime.date,
    amount,
    method: str,
    document: str,
    notes: str = "",
) -> Payment:
    """Registra o pagamento (ou o recebimento) do título, no todo ou em parte.

    Idempotente por `(título, documento)`: o clique duplo chega ao mesmo
    documento e a segunda baixa é recusada. A soma das baixas nunca passa do
    valor do título."""
    if not pode_executar_pagamento(usuario):
        raise BusinessError("Você não tem permissão para dar baixa em títulos.")
    titulo = _travar(titulo)
    _exigir_ativo(titulo)
    _exigir_escrita_na_fazenda(titulo, usuario)

    document = (document or "").strip()
    amount = Decimal(amount or 0)
    if not document:
        raise BusinessError(
            "Informe o documento do pagamento (nº da TED, ID do Pix, nº do cheque): "
            "é ele que impede a mesma baixa de ser registrada duas vezes."
        )
    if method not in PaymentMethod.values:
        raise BusinessError("Informe a forma de pagamento.")
    if amount <= 0:
        raise BusinessError("O valor da baixa deve ser maior que zero.")
    if date > datetime.date.today():
        raise BusinessError("A data do pagamento não pode estar no futuro.")

    verbo = "recebimento" if titulo.a_receber else "pagamento"
    permitidas = situacoes_que_aceitam_baixa(titulo)
    if titulo.payment_status == PaymentStatus.PAGO:
        raise BusinessError(f"O título {titulo.code} já está quitado.")
    if titulo.payment_status not in permitidas:
        raise BusinessError(
            f"O título {titulo.code} está '{titulo.situacao_rotulo.lower()}': o "
            f"{verbo} só pode ser registrado depois da aprovação."
        )
    mesma_pessoa = _exigir_separacao_de_funcoes(titulo, usuario)

    saldo = titulo.amount - titulo.paid_total
    if amount > saldo:
        raise BusinessError(
            f"O valor ({dinheiro_br(amount)}) ultrapassa o que falta no título "
            f"{titulo.code}: {dinheiro_br(saldo)}."
        )
    if (
        Payment.objects.filter(invoice=titulo, document=document)
        .exclude(status=Status.EXCLUIDA)
        .exists()
    ):
        raise BusinessError(
            f"Já existe uma baixa com o documento '{document}' neste título. "
            "Se o clique foi duplo, a primeira já valeu."
        )

    season = Season.objects.select_for_update().get(pk=titulo.season_id)
    baixa = Payment(
        invoice=titulo,
        date=date,
        amount=amount,
        method=method,
        document=document,
        notes=notes or "",
        created_by=usuario,
    )
    baixa.code = gerar_codigo_baixa(season, titulo.direction)
    try:
        with transaction.atomic():
            baixa.save()
    except IntegrityError as exc:
        raise BusinessError(
            f"Já existe uma baixa com o documento '{document}' neste título."
        ) from exc

    baixa = reversible.confirmar(baixa, usuario=usuario)
    registrar_operacao(
        entity=titulo,
        title=f"{baixa.verbo} registrado: {dinheiro_br(amount)}",
        description=f"{baixa.get_method_display()} · documento {document}.",
        new_status=Invoice.objects.get(pk=titulo.pk).payment_status,
        document=baixa.code,
        actor=usuario,
    )
    if mesma_pessoa:
        registrar_auditoria(
            action=AuditAction.UPDATE,
            entity=titulo,
            reason=(
                "Aprovação e baixa feitas pela mesma pessoa: não há outro usuário "
                "financeiro ativo que pudesse executar."
            ),
            actor=usuario,
        )
    return baixa


@transaction.atomic
def desfazer_baixa(pagamento: Payment, *, usuario, motivo: str) -> Payment:
    """A única exceção ao "tudo é editável": desfazer aqui não desfaz a
    transferência no banco. FINANCEIRO ou ADMIN, com motivo."""
    if not pode_desfazer_baixa(usuario):
        raise BusinessError(
            "Só o financeiro ou o administrador pode desfazer uma baixa."
        )
    titulo = pagamento.invoice
    if not tem_acesso_de_escrita_a_fazenda(usuario, titulo.farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {titulo.farm}.")
    return reversible.excluir(pagamento, usuario=usuario, motivo=motivo)


@transaction.atomic
def restaurar_baixa(pagamento: Payment, *, usuario) -> Payment:
    if not pode_desfazer_baixa(usuario):
        raise BusinessError(
            "Só o financeiro ou o administrador pode restaurar uma baixa."
        )
    pagamento = Payment.objects.select_for_update().get(pk=pagamento.pk)
    titulo = _travar(pagamento.invoice)
    _exigir_ativo(titulo)
    if pagamento.bloqueios():
        raise BlockingDependencyError(
            f"Não é possível restaurar: {pagamento.bloqueios()[0]}"
        )
    if Payment.objects.filter(
        invoice=titulo, document=pagamento.document, status=Status.CONFIRMADA
    ).exists():
        raise BusinessError(
            f"Já existe outra baixa com o documento '{pagamento.document}' neste título."
        )
    return reversible.restaurar(pagamento, usuario=usuario)


# --------------------------------------------------------------------------
# Dado bancário: quem consultou (LGPD)
# --------------------------------------------------------------------------


def registrar_consulta_a_dado_bancario(titulo: Invoice, *, usuario) -> None:
    """Auditar quem consultou dado bancário (seguranca/01#lgpd). Um evento por
    pessoa, título e dia: o suficiente para responder "quem viu", sem encher a
    trilha a cada recarregamento da tela."""
    from apps.audit.models import AuditEvent

    if titulo.bank_account_id is None:
        return
    entity_id = str(titulo.bank_account_id)
    hoje = timezone.localdate()
    ja_registrou = AuditEvent.objects.filter(
        action=AuditAction.VIEW,
        actor=usuario,
        entity_type="BankAccount",
        entity_id=entity_id,
        reason__contains=titulo.code,
        timestamp__date=hoje,
    ).exists()
    if not ja_registrou:
        registrar_auditoria(
            action=AuditAction.VIEW,
            entity_type="BankAccount",
            entity_id=entity_id,
            reason=f"Consultou os dados bancários no título {titulo.code}",
            actor=usuario,
        )
