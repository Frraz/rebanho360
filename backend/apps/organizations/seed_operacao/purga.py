"""Desfaz o seed: apaga **de verdade** o que ele criou e mais nada.

Como o seed é reconhecido (sem coluna de marca nos modelos):
- fazenda com código `S3-…` e tudo que pertence a ela (lote, movimento, razão,
  pesagem, compra, venda, custo, título, baixa, operação de compra, ciclo
  reprodutivo, estrutura, máquina, pasto);
- unidade `S3-…`;
- parceiro com o marcador `[seed-3safras]` em `notes` (e suas contas, papéis e
  regras de comissão);
- safra, raça ou categoria que o seed criou — descobertas pela auditoria
  (`request_id` fixo, ação CREATE) — e que ficaram sem nenhuma referência.

Por que apagar pelo SQL e não pelos serviços de exclusão: o razão do rebanho é
append-only (trigger de banco) e as chaves estrangeiras são `PROTECT`; a
exclusão lógica deixaria fazendas, lotes e parceiros de demonstração no banco.

A rede de segurança é o próprio banco: as chaves estrangeiras do Django são
`DEFERRABLE INITIALLY DEFERRED`, então a ordem dos `DELETE` não importa, e
`SET CONSTRAINTS ALL IMMEDIATE` no fim verifica tudo. Se algo que **não** é do
seed ainda apontar para o que seria apagado, a transação inteira é desfeita e
nada é removido.

A auditoria **nunca** é tocada: os eventos de criação continuam lá. No fim o
desfazer grava mais um evento, dizendo quem apagou o quê.
"""

import uuid

from django.db import IntegrityError, connection, transaction
from django.db.models import Q

from apps.accounts.models import UserFarmAccess
from apps.audit.models import AuditAction, AuditEvent, OperationEvent
from apps.audit.services import registrar_auditoria
from apps.commercial.models import CommissionRule
from apps.costs.models import CostEntry
from apps.finance.models import Invoice, Payment
from apps.herd.models import HerdLedgerEntry, HerdMovement, Weighing, WeighingAnimal
from apps.infrastructure.models import FarmStructure, Machine, MachineLog
from apps.livestock.models import AnimalCategory, Breed, Lot
from apps.organizations.models import BusinessUnit, Season
from apps.partners.models import BankAccount, Partner, PartnerRole
from apps.procurement.models import (
    Commission,
    Commitment,
    CommitmentItem,
    FiscalNote,
    GradingLine,
    Receiving,
    ReceivingLine,
    Settlement,
    SettlementAllocation,
    SettlementLine,
    Trip,
    TripLoad,
)
from apps.properties.models import Farm, Paddock
from apps.purchases.models import Purchase
from apps.reproduction.models import BreedingCycle
from apps.sales.models import Sale

from . import catalogo as cat

TRIGGER_DO_RAZAO = "herdledgerentry_immutable_trigger"


def _alvos(farms, parceiros):
    """(rótulo, modelo, filtro) em ordem de folha para raiz — a ordem é só
    para leitura humana; o banco confere tudo no fim."""
    cadeia = "trip__commitment__destination_farm__in"
    return [
        ("Baixas", Payment, Q(invoice__farm__in=farms)),
        ("Títulos", Invoice, Q(farm__in=farms)),
        (
            "Distribuição do acerto",
            SettlementAllocation,
            Q(settlement__commitment__destination_farm__in=farms),
        ),
        (
            "Notas fiscais",
            FiscalNote,
            Q(settlement__commitment__destination_farm__in=farms),
        ),
        (
            "Tributos e descontos do acerto",
            SettlementLine,
            Q(settlement__commitment__destination_farm__in=farms),
        ),
        ("Acertos", Settlement, Q(commitment__destination_farm__in=farms)),
        ("Linhas de recebimento", ReceivingLine, Q(**{f"receiving__{cadeia}": farms})),
        ("Recebimentos", Receiving, Q(**{cadeia: farms})),
        ("Cargas", TripLoad, Q(**{cadeia: farms})),
        ("Viagens", Trip, Q(commitment__destination_farm__in=farms)),
        ("Romaneio", GradingLine, Q(item__commitment__destination_farm__in=farms)),
        (
            "Comissões da operação",
            Commission,
            Q(commitment__destination_farm__in=farms),
        ),
        (
            "Itens das operações",
            CommitmentItem,
            Q(commitment__destination_farm__in=farms),
        ),
        ("Operações de compra", Commitment, Q(destination_farm__in=farms)),
        (
            "Linhas do razão",
            HerdLedgerEntry,
            Q(farm__in=farms)
            | Q(movement__origin_farm__in=farms)
            | Q(movement__destination_farm__in=farms),
        ),
        ("Pesagens individuais", WeighingAnimal, Q(weighing__farm__in=farms)),
        ("Pesagens", Weighing, Q(farm__in=farms)),
        (
            "Movimentos do rebanho",
            HerdMovement,
            Q(origin_farm__in=farms) | Q(destination_farm__in=farms),
        ),
        ("Custos", CostEntry, Q(farm__in=farms)),
        ("Vendas e abates", Sale, Q(farm__in=farms)),
        ("Compras", Purchase, Q(destination_farm__in=farms)),
        ("Lotes", Lot, Q(farm__in=farms)),
        ("Uso de máquinas", MachineLog, Q(machine__farm__in=farms)),
        ("Máquinas", Machine, Q(farm__in=farms)),
        ("Estruturas", FarmStructure, Q(farm__in=farms)),
        ("Ciclos reprodutivos", BreedingCycle, Q(farm__in=farms)),
        ("Pastos", Paddock, Q(farm__in=farms)),
        ("Acessos às fazendas do seed", UserFarmAccess, Q(farm__in=farms)),
        ("Regras de comissão", CommissionRule, Q(commissioned__in=parceiros)),
        ("Contas bancárias", BankAccount, Q(partner__in=parceiros)),
        ("Papéis de parceiros", PartnerRole, Q(partner__in=parceiros)),
        ("Parceiros", Partner, Q(pk__in=parceiros)),
        ("Fazendas", Farm, Q(pk__in=farms)),
        ("Unidades", BusinessUnit, Q(code__startswith=cat.PREFIXO)),
    ]


def criados_pelo_seed(modelo) -> list[int]:
    """Ids do `modelo` que o seed criou, pela auditoria (ação CREATE sob o
    `request_id` fixo do seed). Cadastro que já existia não aparece aqui."""
    ids = AuditEvent.objects.filter(
        request_id=uuid.UUID(cat.SEED_UUID),
        action=AuditAction.CREATE,
        entity_type=modelo.__name__,
    ).values_list("entity_id", flat=True)
    return [int(i) for i in ids if str(i).isdigit()]


def _sem_referencia(objeto) -> bool:
    """Nenhuma tabela aponta mais para o objeto (inclusive por `related_name='+'`)."""
    modelo = type(objeto)
    for relacao in modelo._meta.get_fields(include_hidden=True):
        if not (relacao.auto_created and not relacao.concrete):
            continue
        if not (relacao.one_to_many or relacao.one_to_one):
            continue
        if relacao.related_model._base_manager.filter(
            **{relacao.field.name: objeto}
        ).exists():
            return False
    return True


def existe_seed() -> bool:
    return (
        Farm.objects.filter(code__startswith=cat.PREFIXO).exists()
        or Partner.objects.filter(notes__startswith=cat.MARCADOR).exists()
    )


def desfazer(*, admin, simular: bool = False) -> dict[str, int]:
    """Apaga o seed. Com `simular=True` faz tudo e desfaz a transação no fim:
    os números e a verificação das chaves estrangeiras são os da execução real."""
    apagados: dict[str, int] = {}
    try:
        with transaction.atomic():
            farms = Farm.objects.filter(code__startswith=cat.PREFIXO)
            parceiros = Partner.objects.filter(notes__startswith=cat.MARCADOR)
            farm_ids = list(farms.values_list("pk", flat=True))
            parceiro_ids = list(parceiros.values_list("pk", flat=True))
            cadastros_do_seed = [
                (m, criados_pelo_seed(m)) for m in (Season, Breed, AnimalCategory)
            ]

            # Os eventos de operação (linha do tempo do usuário) dos registros
            # apagados também saem; a auditoria técnica, não.
            ids_por_tipo = {}
            for rotulo, modelo, filtro in _alvos(farm_ids, parceiro_ids):
                if modelo in (
                    Payment,
                    Invoice,
                    HerdMovement,
                    Weighing,
                    CostEntry,
                    Sale,
                    Purchase,
                    Commitment,
                    Trip,
                    Receiving,
                    Settlement,
                    Lot,
                    MachineLog,
                    BreedingCycle,
                ):
                    ids_por_tipo[modelo.__name__] = list(
                        modelo._base_manager.filter(filtro).values_list("pk", flat=True)
                    )

            with connection.cursor() as cursor:
                # O ALTER TABLE recusa tabela com evento de gatilho pendente
                # (acontece quando o seed e o desfazer rodam na mesma transação,
                # como nos testes). Confere o que está pendente antes de mexer.
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                # ...e volta a diferir: a ordem dos DELETE só não importa com as
                # chaves estrangeiras conferidas no fim, não a cada comando.
                cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                cursor.execute(
                    f"ALTER TABLE {HerdLedgerEntry._meta.db_table} "
                    f"DISABLE TRIGGER {TRIGGER_DO_RAZAO}"
                )
                for rotulo, modelo, filtro in _alvos(farm_ids, parceiro_ids):
                    n = modelo._base_manager.filter(filtro)._raw_delete(using="default")
                    if n:
                        apagados[rotulo] = n

                # Safra, raça e categoria que o seed criou e que ficaram sem uso.
                # O que já existia antes do seed nunca aparece na lista.
                for modelo, ids in cadastros_do_seed:
                    removidos = 0
                    for pk in ids:
                        objeto = modelo.objects.filter(pk=pk).first()
                        if objeto is not None and _sem_referencia(objeto):
                            modelo._base_manager.filter(pk=pk)._raw_delete(
                                using="default"
                            )
                            removidos += 1
                    if removidos:
                        apagados[
                            f"{modelo._meta.verbose_name_plural} criadas(os) pelo seed"
                        ] = removidos

                for tipo, ids in ids_por_tipo.items():
                    total = 0
                    for i in range(0, len(ids), 5000):
                        lote = [str(x) for x in ids[i : i + 5000]]
                        total += OperationEvent.objects.filter(
                            entity_type=tipo, entity_id__in=lote
                        )._raw_delete(using="default")
                    if total:
                        apagados["Linha do tempo de " + tipo] = total

                # Confere as chaves estrangeiras agora; se algo de fora do seed
                # ainda aponta para o que foi apagado, falha aqui e desfaz tudo.
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                # Devolve o modo padrão (diferido) à transação: quem rodar mais
                # alguma coisa nela não deve herdar a conferência imediata.
                cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                cursor.execute(
                    f"ALTER TABLE {HerdLedgerEntry._meta.db_table} "
                    f"ENABLE TRIGGER {TRIGGER_DO_RAZAO}"
                )

            if apagados and not simular:
                registrar_auditoria(
                    action=AuditAction.DELETE,
                    entity_type="SeedOperacaoGrande",
                    entity_id="",
                    after={"registros_apagados": apagados},
                    reason="Seed de demonstração desfeito (desfazer_seed_operacao_grande).",
                    actor=admin,
                )
            if simular:
                transaction.set_rollback(True)
    except IntegrityError as exc:
        raise ValueError(
            "Há dado que NÃO é do seed apontando para o que seria apagado "
            "(por exemplo, uma compra sua com um parceiro ou fazenda do seed). "
            "Nada foi apagado. Detalhe do banco: " + str(exc).splitlines()[0]
        ) from exc
    return apagados
