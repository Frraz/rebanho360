"""O que dá para exportar: um catálogo explícito de conjuntos de dados.

Cada conjunto é uma tabela do sistema (um modelo) com **quatro decisões
tomadas por escrito**, porque exportar é o jeito mais fácil de vazar dado:

- `escopo` — por onde o registro chega a uma fazenda. Quem não enxerga tudo só
  exporta o que o escopo dele alcança (regra 4). Vazio = cadastro geral, igual
  ao que as telas já mostram a qualquer usuário.
- `permitido` — quem pode exportar (financeiro, ciclo de compra, usuários e
  auditoria seguem a regra da própria tela).
- `sem` / `campos` — o que **nunca** sai. Senha, segredo do 2FA e códigos de
  recuperação não estão no catálogo de propósito (ver `NAO_EXPORTAVEIS`).
- `restritos` — campo que só alguns papéis veem (a conta bancária no título).

Um teste obriga todo modelo novo do sistema a entrar aqui ou em
`NAO_EXPORTAVEIS`, com o motivo: tabela nova não fica de fora da exportação por
esquecimento — nem entra nela sem passar por estas quatro decisões.

O que é **derivado** (peso médio, custo/@, margem) não está aqui: é calculado
por um serviço só, e quem quer os números prontos exporta o **relatório**
(`relatorios_para`), que usa o mesmo serviço da tela (regra 6).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from django.apps import apps as django_apps

from apps.accounts.permissions import pode_gerenciar_usuarios
from apps.audit.permissions import pode_ver_auditoria
from apps.finance.permissions import pode_ver_dado_bancario, pode_ver_titulos
from apps.imports.permissions import pode_importar
from apps.procurement.permissions import pode_ver_o_ciclo


def _qualquer(user) -> bool:
    return True


@dataclass(frozen=True)
class Conjunto:
    chave: str
    modelo: str  # "app.Modelo" — resolvido na hora, sem importar o modelo aqui
    grupo: str
    rotulo: str = ""
    nota: str = ""
    # Caminhos de FK até `properties.Farm`; vale um OU entre eles (a
    # movimentação tem origem e destino). Vazio = cadastro geral.
    escopo: tuple[str, ...] = ()
    data: str = ""  # caminho do campo de data, para o filtro de período
    safra: str = ""  # caminho até `organizations.Season`
    # "status" (ReversibleModel: EXCLUIDA) · "linhas" (LineModel: removed_at)
    # · "usuario" (deleted_at). Vazio = nada a esconder.
    exclusao: str = ""
    pai_excluido: str = ""  # caminho de `status` do documento pai
    permitido: Callable = _qualquer
    campos: tuple[str, ...] = ()  # lista branca (vazio = todos os campos)
    sem: tuple[str, ...] = ()
    restritos: dict[str, Callable] = field(default_factory=dict)
    pdf: tuple[str, ...] = ()  # colunas do PDF; vazio = as principais
    limitar: Callable | None = None  # (queryset, user) -> queryset

    @property
    def classe(self):
        return django_apps.get_model(self.modelo)

    @property
    def titulo(self) -> str:
        return self.rotulo or str(self.classe._meta.verbose_name_plural).capitalize()


def so_os_proprios(qs, user):
    """Documento gerado: o dono e quem enxerga tudo (mesma regra da tela)."""
    return qs if user.has_broad_access else qs.filter(generated_by=user)


def sem_o_superusuario(qs, user):
    """O superusuário (suporte) é oculto: não sai na exportação de ninguém,
    a não ser na dele mesmo."""
    return qs if user.is_superuser else qs.filter(is_superuser=False)


def sem_acessos_do_superusuario(qs, user):
    return qs if user.is_superuser else qs.filter(user__is_superuser=False)


EMPRESA = "Empresa e propriedades"
PARCEIROS = "Parceiros"
REBANHO = "Rebanho e lotes"
COMERCIAL = "Comercial"
CUSTOS = "Custos"
COMPRAS_VENDAS = "Compras e vendas"
MOVIMENTACAO = "Movimentação do rebanho"
CICLO = "Ciclo de compra"
FINANCEIRO = "Financeiro"
SISTEMA = "Sistema e auditoria"

GRUPOS = (
    EMPRESA,
    PARCEIROS,
    REBANHO,
    COMERCIAL,
    CUSTOS,
    COMPRAS_VENDAS,
    MOVIMENTACAO,
    CICLO,
    FINANCEIRO,
    SISTEMA,
)

# Do compromisso até a fazenda de destino: o escopo de tudo que pende dele.
_ACERTO = "commitment__destination_farm"

CONJUNTOS: tuple[Conjunto, ...] = (
    # ------------------------------------------------------------ Empresa
    Conjunto("empresas", "organizations.Company", EMPRESA),
    Conjunto("unidades", "organizations.BusinessUnit", EMPRESA),
    Conjunto("safras", "organizations.Season", EMPRESA),
    Conjunto("fazendas", "properties.Farm", EMPRESA, escopo=("pk",)),
    Conjunto("pastos", "properties.Paddock", EMPRESA, escopo=("farm",)),
    # ----------------------------------------------------------- Parceiros
    Conjunto("parceiros", "partners.Partner", PARCEIROS),
    Conjunto("papeis-dos-parceiros", "partners.PartnerRole", PARCEIROS),
    Conjunto(
        "contas-bancarias",
        "partners.BankAccount",
        PARCEIROS,
        nota="Dado bancário: só quem já vê conta e Pix na tela.",
        permitido=pode_ver_dado_bancario,
    ),
    # ------------------------------------------------------------- Rebanho
    Conjunto("categorias", "livestock.AnimalCategory", REBANHO),
    Conjunto("racas", "livestock.Breed", REBANHO),
    Conjunto(
        "lotes",
        "livestock.Lot",
        REBANHO,
        escopo=("farm",),
        data="entry_date",
        safra="season",
        pdf=(
            "code",
            "farm",
            "origin_partner",
            "entry_date",
            "exit_date",
            "breed",
            "season",
            "status",
        ),
    ),
    # ----------------------------------------------------------- Comercial
    Conjunto("classes-de-carcaca", "commercial.CarcassClass", COMERCIAL),
    Conjunto("condicoes-de-pagamento", "commercial.PaymentCondition", COMERCIAL),
    Conjunto("tributos", "commercial.TaxType", COMERCIAL),
    Conjunto("regras-de-comissao", "commercial.CommissionRule", COMERCIAL),
    # -------------------------------------------------------------- Custos
    Conjunto("classes-de-custo", "costs.CostClass", CUSTOS),
    Conjunto("centros-de-custo", "costs.CostCenter", CUSTOS),
    Conjunto(
        "lancamentos-de-custo",
        "costs.CostEntry",
        CUSTOS,
        escopo=("farm",),
        data="date",
        safra="season",
        exclusao="status",
        pdf=(
            "date",
            "farm",
            "cost_center",
            "cost_class",
            "amount",
            "description",
            "lot",
            "status",
        ),
    ),
    # ----------------------------------------------------- Compras e vendas
    Conjunto(
        "compras",
        "purchases.Purchase",
        COMPRAS_VENDAS,
        escopo=("destination_farm",),
        data="date",
        safra="season",
        exclusao="status",
        pdf=(
            "code",
            "date",
            "seller",
            "destination_farm",
            "category",
            "head_count",
            "total_weight_kg",
            "animal_value",
            "freight_value",
            "lot",
            "status",
        ),
    ),
    Conjunto(
        "vendas",
        "sales.Sale",
        COMPRAS_VENDAS,
        rotulo="Vendas e abates",
        escopo=("farm",),
        data="date",
        safra="season",
        exclusao="status",
        pdf=(
            "code",
            "date",
            "type",
            "buyer",
            "farm",
            "lot",
            "head_count",
            "total_weight_kg",
            "carcass_weight_kg",
            "total_value",
            "status",
        ),
    ),
    # ------------------------------------------------ Movimentação do rebanho
    Conjunto(
        "movimentacoes",
        "herd.HerdMovement",
        MOVIMENTACAO,
        rotulo="Movimentações do rebanho",
        nota="O evento. As linhas com sinal estão em Razão do rebanho.",
        escopo=("origin_farm", "destination_farm"),
        data="date",
        safra="season",
        exclusao="status",
        pdf=(
            "code",
            "date",
            "type",
            "status",
            "quantity",
            "total_weight_kg",
            "origin_farm",
            "origin_lot",
            "origin_category",
            "destination_farm",
            "destination_lot",
            "destination_category",
        ),
    ),
    Conjunto(
        "razao-do-rebanho",
        "herd.HerdLedgerEntry",
        MOVIMENTACAO,
        rotulo="Razão do rebanho (linhas)",
        nota="O saldo é a soma da quantidade. Linhas de correção aparecem com a data do fato original.",
        escopo=("farm",),
        data="date",
        safra="season",
        pai_excluido="movement__status",
        pdf=("date", "movement", "farm", "lot", "category", "quantity", "weight_kg"),
    ),
    Conjunto(
        "pesagens",
        "herd.Weighing",
        MOVIMENTACAO,
        escopo=("farm",),
        data="date",
        exclusao="status",
        pdf=(
            "date",
            "farm",
            "lot",
            "reason",
            "head_count",
            "total_weight_kg",
            "status",
        ),
    ),
    Conjunto(
        "pesagens-individuais",
        "herd.WeighingAnimal",
        MOVIMENTACAO,
        escopo=("weighing__farm",),
        data="weighing__date",
        pai_excluido="weighing__status",
    ),
    Conjunto(
        "estruturas-da-fazenda",
        "infrastructure.FarmStructure",
        REBANHO,
        escopo=("farm",),
    ),
    Conjunto(
        "maquinas",
        "infrastructure.Machine",
        REBANHO,
        escopo=("farm",),
    ),
    Conjunto(
        "uso-das-maquinas",
        "infrastructure.MachineLog",
        MOVIMENTACAO,
        escopo=("machine__farm",),
        data="date",
        exclusao="status",
    ),
    Conjunto(
        "ciclos-reprodutivos",
        "reproduction.BreedingCycle",
        MOVIMENTACAO,
        escopo=("farm",),
        safra="season",
        exclusao="status",
    ),
    # ------------------------------------------------------- Ciclo de compra
    Conjunto(
        "compromissos",
        "procurement.Commitment",
        CICLO,
        escopo=("destination_farm",),
        data="date",
        safra="season",
        exclusao="status",
        permitido=pode_ver_o_ciclo,
        pdf=(
            "code",
            "date",
            "seller",
            "destination_farm",
            "pickup_date",
            "slaughter_date",
            "status",
        ),
    ),
    Conjunto(
        "itens-dos-compromissos",
        "procurement.CommitmentItem",
        CICLO,
        escopo=(_ACERTO,),
        data="commitment__date",
        safra="commitment__season",
        exclusao="linhas",
        pai_excluido="commitment__status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "comissoes",
        "procurement.Commission",
        CICLO,
        rotulo="Comissões dos compromissos",
        escopo=(_ACERTO,),
        data="commitment__date",
        safra="commitment__season",
        pai_excluido="commitment__status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "viagens",
        "procurement.Trip",
        CICLO,
        escopo=(_ACERTO,),
        data="pickup_date",
        safra="commitment__season",
        exclusao="status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "cargas-das-viagens",
        "procurement.TripLoad",
        CICLO,
        escopo=("trip__commitment__destination_farm",),
        data="trip__pickup_date",
        safra="trip__commitment__season",
        exclusao="linhas",
        pai_excluido="trip__status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "recebimentos",
        "procurement.Receiving",
        CICLO,
        escopo=("trip__commitment__destination_farm",),
        data="date",
        safra="trip__commitment__season",
        exclusao="status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "linhas-dos-recebimentos",
        "procurement.ReceivingLine",
        CICLO,
        escopo=("receiving__trip__commitment__destination_farm",),
        data="receiving__date",
        safra="receiving__trip__commitment__season",
        exclusao="linhas",
        pai_excluido="receiving__status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "romaneios",
        "procurement.GradingLine",
        CICLO,
        escopo=("item__commitment__destination_farm",),
        data="item__commitment__date",
        safra="item__commitment__season",
        exclusao="linhas",
        pai_excluido="item__commitment__status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "acertos",
        "procurement.Settlement",
        CICLO,
        escopo=(_ACERTO,),
        data="date",
        safra="commitment__season",
        exclusao="status",
        permitido=pode_ver_o_ciclo,
        pdf=("code", "commitment", "date", "status", "approved_by", "approved_at"),
    ),
    Conjunto(
        "linhas-dos-acertos",
        "procurement.SettlementLine",
        CICLO,
        escopo=("settlement__commitment__destination_farm",),
        data="settlement__date",
        safra="settlement__commitment__season",
        exclusao="linhas",
        pai_excluido="settlement__status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "distribuicao-dos-acertos",
        "procurement.SettlementAllocation",
        CICLO,
        rotulo="Distribuição do acerto por item",
        escopo=("settlement__commitment__destination_farm",),
        data="settlement__date",
        safra="settlement__commitment__season",
        pai_excluido="settlement__status",
        permitido=pode_ver_o_ciclo,
    ),
    Conjunto(
        "notas-fiscais",
        "procurement.FiscalNote",
        CICLO,
        escopo=("settlement__commitment__destination_farm",),
        data="issue_date",
        safra="settlement__commitment__season",
        exclusao="linhas",
        pai_excluido="settlement__status",
        permitido=pode_ver_o_ciclo,
    ),
    # ----------------------------------------------------------- Financeiro
    Conjunto(
        "titulos",
        "finance.Invoice",
        FINANCEIRO,
        escopo=("farm",),
        data="issue_date",
        safra="season",
        exclusao="status",
        permitido=pode_ver_titulos,
        restritos={"bank_account": pode_ver_dado_bancario},
        pdf=(
            "code",
            "direction",
            "payee",
            "issue_date",
            "due_date",
            "amount",
            "payment_status",
            "status",
        ),
    ),
    Conjunto(
        "pagamentos",
        "finance.Payment",
        FINANCEIRO,
        rotulo="Pagamentos e recebimentos (baixas)",
        escopo=("invoice__farm",),
        data="date",
        safra="invoice__season",
        exclusao="status",
        permitido=pode_ver_titulos,
        pdf=("code", "invoice", "date", "amount", "method", "status"),
    ),
    # --------------------------------------------------- Sistema e auditoria
    Conjunto(
        "usuarios",
        "accounts.User",
        SISTEMA,
        nota="Sem senha e sem segundo fator: isso nunca sai do sistema.",
        exclusao="usuario",
        limitar=sem_o_superusuario,
        permitido=pode_gerenciar_usuarios,
        campos=(
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "phone",
            "is_active",
            "must_change_password",
            "last_login",
            "date_joined",
            "deleted_at",
        ),
    ),
    Conjunto(
        "acessos-por-fazenda",
        "accounts.UserFarmAccess",
        SISTEMA,
        escopo=("farm",),
        limitar=sem_acessos_do_superusuario,
        permitido=pode_gerenciar_usuarios,
    ),
    Conjunto(
        "pedidos-de-acesso",
        "accounts.AccessRequest",
        SISTEMA,
        data="created_at",
        permitido=pode_gerenciar_usuarios,
    ),
    Conjunto(
        "auditoria",
        "audit.AuditEvent",
        SISTEMA,
        rotulo="Trilha de auditoria",
        nota="Quem fez o quê e quando. Só leitura: a trilha nunca é alterada.",
        data="timestamp",
        permitido=pode_ver_auditoria,
        pdf=("timestamp", "actor", "action", "entity_type", "entity_id", "reason"),
    ),
    Conjunto(
        "linha-do-tempo",
        "audit.OperationEvent",
        SISTEMA,
        rotulo="Linha do tempo das operações",
        data="timestamp",
        permitido=pode_ver_auditoria,
    ),
    Conjunto(
        "importacoes",
        "imports.ImportBatch",
        SISTEMA,
        data="created_at",
        sem=("file",),
        permitido=pode_importar,
    ),
    Conjunto(
        "linhas-importadas",
        "imports.ImportRow",
        SISTEMA,
        nota="Cada linha crua das planilhas e o registro que ela criou.",
        permitido=pode_importar,
    ),
    Conjunto(
        "documentos-gerados",
        "documents.GeneratedDocument",
        SISTEMA,
        data="generated_at",
        sem=("file",),
        limitar=so_os_proprios,
    ),
)

#: Modelos que **não** se exportam, e por quê. O teste de cobertura exige que
#: todo modelo do sistema esteja no catálogo ou aqui.
NAO_EXPORTAVEIS = {
    "accounts.TOTPDevice": "segredo do segundo fator: nunca sai do sistema",
    "accounts.RecoveryCode": "códigos de recuperação do segundo fator: nunca saem do sistema",
    "accounts.TrustedDevice": "dispositivos confiáveis do segundo fator: só o dono vê os seus, na página Conta",
    "exports.ExportJob": "é a própria exportação (o pedido fica na tela de exportações)",
}

_POR_CHAVE = {c.chave: c for c in CONJUNTOS}


def conjunto_por_chave(chave: str) -> Conjunto | None:
    return _POR_CHAVE.get(chave)


def conjuntos_para(user) -> list[Conjunto]:
    """O que este usuário pode pedir, na ordem dos grupos."""
    return [c for c in CONJUNTOS if c.permitido(user)]


def grupos_para(user) -> list[tuple[str, list[Conjunto]]]:
    visiveis = conjuntos_para(user)
    return [
        (grupo, [c for c in visiveis if c.grupo == grupo])
        for grupo in GRUPOS
        if any(c.grupo == grupo for c in visiveis)
    ]


# --------------------------------------------------------------------------
# Relatórios prontos — o mesmo serviço da tela (regra 6)
# --------------------------------------------------------------------------


def relatorios_para(user) -> list[tuple[str, str, str]]:
    """(slug, título, descrição) dos relatórios que o papel pode abrir. Fora o
    que precisa de um registro escolhido (a conferência de **um** acerto) e o que
    não é tabela (o contrato de compra, que é um PDF por compromisso)."""
    from apps.reports import services

    return [
        item
        for item in services.catalogo_para(user)
        if "acerto" not in services.PARAMETROS.get(item[0], ())
        and item[0] in services.RELATORIOS
    ]
