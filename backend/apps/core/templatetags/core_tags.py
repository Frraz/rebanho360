from decimal import Decimal

from django.template import Library
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse
from django.utils.html import escape, format_html

from apps.accounts.models import Role
from apps.core.formatting import dinheiro_br, numero_br
from apps.core.help_content import topico_de_ajuda

register = Library()


#: Menu lateral, no desenho do escopo funcional (docs/fontes/imagem.jpeg):
#: três blocos — Entrada, Movimentações, Relatórios e Análise — cada um com
#: cinco grupos. Mais um bloco "Sistema" para o que a imagem não prevê
#: (importação, auditoria, usuários). Bloco → grupo → item.
#:
#: Cada bloco é recolhível e só abre sozinho o que contém a tela atual: são
#: ~40 links, e todos abertos escondiam onde o usuário está. "Início" fica fora
#: dos blocos (MENU_TOPO), sempre à vista.
#:
#: O ícone é o nome de um símbolo em static/img/icons.svg; cada item tem o seu,
#: para o olho achar o link sem ler. `so` restringe quem vê o link — só esconde
#: o que o usuário receberia como 403; a barreira de verdade continua na view.
#: A rota é o nome da URL, ou `(nome, kwargs)` para apontar um relatório pelo
#: slug. O subtítulo do grupo só aparece quando o bloco tem mais de um grupo e
#: o grupo tem mais de um item.
MENU_TOPO = (
    ("dashboards:inicio", "Início", "house", None),
    ("dashboards:dashboard", "Dashboard", "chart-column", None),
)

MENU = (
    (
        "Entrada",
        "database",
        (
            (
                "Empresa / Propriedades",
                (
                    ("organizations:empresa_lista", "Empresas", "building-2", None),
                    ("organizations:unidade_lista", "Unidades", "package", None),
                    ("organizations:safra_lista", "Safras", "calendar", None),
                    ("properties:fazenda_lista", "Fazendas", "map", None),
                    ("properties:pasto_lista", "Áreas / Pastos", "map-pin", None),
                    (
                        "infrastructure:estrutura_lista",
                        "Infraestrutura",
                        "maximize-2",
                        None,
                    ),
                    ("infrastructure:maquina_lista", "Máquinas", "settings", None),
                ),
            ),
            (
                "Parceiros",
                (("partners:lista", "Parceiros", "users", None),),
            ),
            (
                "Rebanho / Produtos / Lotes",
                (
                    ("livestock:categoria_lista", "Categorias", "list-checks", None),
                    ("livestock:raca_lista", "Raças", "grid-2x2", None),
                    ("livestock:lote_lista", "Lotes", "tag", None),
                ),
            ),
            (
                "Comercial",
                (
                    ("commercial:classe_lista", "Classes de carcaça", "beef", None),
                    (
                        "commercial:condicao_lista",
                        "Condições de pagamento",
                        "clock",
                        None,
                    ),
                    ("commercial:tributo_lista", "Tributos e taxas", "receipt", None),
                    (
                        "commercial:comissao_lista",
                        "Regras de comissão",
                        "percent",
                        None,
                    ),
                ),
            ),
            (
                "Custos / Centros de Custo",
                (("costs:centro_lista", "Centros de custo", "landmark", None),),
            ),
        ),
    ),
    (
        "Movimentações",
        "arrow-left-right",
        (
            (
                "Compra / Compromisso",
                (
                    ("purchases:lista", "Compras", "shopping-cart", None),
                    (
                        "procurement:compromisso_lista",
                        "Compromissos",
                        "file-text",
                        "ciclo",
                    ),
                ),
            ),
            (
                "Programação / Embarque",
                (
                    (
                        ("reports:relatorio", {"slug": "programacao-de-embarque"}),
                        "Programação de embarque",
                        "truck",
                        "ciclo",
                    ),
                ),
            ),
            (
                "Recebimento / Acerto",
                (
                    (
                        "procurement:acerto_lista",
                        "Acertos",
                        "clipboard-check",
                        "ciclo",
                    ),
                ),
            ),
            (
                "Rebanho / Manejo",
                (
                    ("herd:posicao", "Posição", "layers", None),
                    ("herd:movimento_lista", "Movimentações", "arrow-left-right", None),
                    ("herd:pesagem_lista", "Pesagens", "scale", None),
                    ("reproduction:lista", "Reprodução", "activity", None),
                    ("sales:lista", "Vendas e abates", "trending-up", None),
                    (
                        "herd:conciliacao_transferencias",
                        "Conciliação de transferências",
                        "git-compare",
                        None,
                    ),
                ),
            ),
            (
                "Financeiro / Fechamento",
                (
                    ("costs:lista", "Custos", "coins", None),
                    (
                        ("reports:relatorio", {"slug": "programacao-de-pagamentos"}),
                        "Programação de pagamentos",
                        "clock",
                        "financeiro",
                    ),
                    (
                        "finance:contas_a_pagar",
                        "Contas a pagar",
                        "banknote",
                        "financeiro",
                    ),
                    (
                        "finance:contas_a_receber",
                        "Contas a receber",
                        "circle-dollar-sign",
                        "financeiro",
                    ),
                    (
                        "finance:pagamento_lista",
                        "Pagamentos e recebimentos",
                        "wallet",
                        "financeiro",
                    ),
                ),
            ),
        ),
    ),
    (
        "Relatórios e Análise",
        "file-bar-chart",
        (
            (
                "Dashboard / Resultados",
                (
                    ("reports:indice", "Todos os relatórios", "layout-dashboard", None),
                    ("documents:lista", "Documentos gerados", "file-down", None),
                ),
            ),
            (
                "Compras / Histórico",
                (
                    (
                        ("reports:relatorio", {"slug": "compras-do-periodo"}),
                        "Compras do período",
                        "file-text",
                        None,
                    ),
                    (
                        ("reports:relatorio", {"slug": "historico-por-pecuarista"}),
                        "Histórico por pecuarista",
                        "history",
                        "ciclo",
                    ),
                    (
                        ("reports:relatorio", {"slug": "programado-x-realizado"}),
                        "Programado × realizado",
                        "git-compare",
                        "ciclo",
                    ),
                ),
            ),
            (
                "Programações / Logística",
                (
                    (
                        ("reports:relatorio", {"slug": "programacao-de-abate"}),
                        "Programação de abate",
                        "calendar",
                        "ciclo",
                    ),
                    (
                        ("reports:relatorio", {"slug": "fretes-e-quebra"}),
                        "Fretes e quebra de viagem",
                        "truck",
                        "ciclo",
                    ),
                ),
            ),
            (
                "Acertos / Financeiro",
                (
                    (
                        ("reports:relatorio", {"slug": "comissao-por-comprador"}),
                        "Comissão por comprador",
                        "percent",
                        "ciclo",
                    ),
                    (
                        "reports:relatorio_fluxo",
                        "Fluxo de caixa",
                        "trending-up",
                        "financeiro",
                    ),
                    (
                        "reports:relatorio_mapa",
                        "Mapa financeiro",
                        "layers",
                        "financeiro",
                    ),
                ),
            ),
            (
                "Rebanho / Fazenda",
                (
                    (
                        ("reports:relatorio", {"slug": "desempenho-do-lote"}),
                        "Desempenho do lote",
                        "file-bar-chart",
                        None,
                    ),
                    (
                        ("reports:relatorio", {"slug": "resultado-do-lote"}),
                        "Resultado do lote",
                        "file-text",
                        None,
                    ),
                ),
            ),
        ),
    ),
    (
        "Sistema",
        "settings",
        (
            (
                "Administração",
                (
                    ("imports:lista", "Importações", "upload", None),
                    ("exports:lista", "Exportações", "download", "exportar"),
                    ("audit:console", "Auditoria", "history", "auditoria"),
                    ("accounts:usuarios", "Usuários e acessos", "users", "usuarios"),
                ),
            ),
        ),
    ),
)


def _pode_ver(user, restricao) -> bool:
    if restricao is None:
        return True
    if restricao == "staff":
        return bool(getattr(user, "is_staff", False))
    if restricao == "usuarios":
        # O gestor decide pedidos de acesso, então também vê a entrada; a
        # lista de usuários em si segue do administrador.
        from apps.accounts.permissions import pode_aprovar_acessos

        return pode_aprovar_acessos(user)
    if restricao == "financeiro":
        from apps.finance.permissions import pode_ver_titulos

        return pode_ver_titulos(user)
    if restricao == "exportar":
        from apps.exports.permissions import pode_exportar

        return pode_exportar(user)
    if restricao == "ciclo":
        from apps.procurement.permissions import pode_ver_o_ciclo

        return pode_ver_o_ciclo(user)
    if restricao == "auditoria":
        from django.conf import settings

        papeis = {Role.ADMIN}
        if getattr(settings, "AUDIT_CONSOLE_INCLUDE_GESTOR", False):
            papeis.add(Role.GESTOR)
        return getattr(user, "role", None) in papeis
    return True


def _linhas(user, itens):
    linhas = []
    for rota, rotulo, icone, restricao in itens:
        if user is not None and not _pode_ver(user, restricao):
            continue
        nome, kwargs = rota if isinstance(rota, tuple) else (rota, {})
        try:
            url = reverse(nome, kwargs=kwargs)
        except NoReverseMatch:
            url = "#"
        linha = {"url": url, "rotulo": rotulo, "icone": icone, "ativo": False}
        if nome == "accounts:usuarios":
            from apps.accounts.permissions import pode_gerenciar_usuarios

            if user is not None and not pode_gerenciar_usuarios(user):
                linha["url"] = reverse("accounts:solicitacoes")
            # Pedidos de acesso esperando decisão: o administrador vê no menu.
            from apps.accounts.selectors import contar_solicitacoes_pendentes

            linha["contagem"] = contar_solicitacoes_pendentes()
        linhas.append(linha)
    return linhas


@register.simple_tag(takes_context=True)
def nav_menu(context):
    """Menu pronto para o template: o topo fixo (bloco sem título) e depois
    blocos → grupos → itens, com o item ativo marcado e o bloco dele aberto.

    Ativo = a rota mais específica que é prefixo do caminho atual, para que
    `/compras/12/` acenda "Compras" e `/rebanho/movimentacoes/posicao/` acenda
    "Posição" — e não também "Movimentações". Rota que ainda não existe vira
    `#` em vez de quebrar a página (permite montar o menu antes das telas).
    Grupo ou bloco sem nenhum item visível some."""
    request = context.get("request")
    user = getattr(request, "user", None)
    path = getattr(request, "path", "")

    resolvidos = []
    topo = _linhas(user, MENU_TOPO)
    if topo:
        resolvidos.append(
            {
                "titulo": None,
                "icone": None,
                "aberto": True,
                "grupos": [{"titulo": None, "mostrar_titulo": False, "itens": topo}],
            }
        )
    for bloco, icone, grupos in MENU:
        grupos_resolvidos = []
        for grupo, itens in grupos:
            linhas = _linhas(user, itens)
            if linhas:
                grupos_resolvidos.append(
                    {"titulo": grupo, "mostrar_titulo": False, "itens": linhas}
                )
        for grupo in grupos_resolvidos:
            # Subtítulo só onde ajuda a separar: com um grupo só, ou um item só,
            # ele repetiria o título do bloco ou o próprio link.
            grupo["mostrar_titulo"] = (
                len(grupos_resolvidos) > 1 and len(grupo["itens"]) > 1
            )
        if grupos_resolvidos:
            resolvidos.append(
                {
                    "titulo": bloco,
                    "icone": icone,
                    "aberto": False,
                    "grupos": grupos_resolvidos,
                }
            )

    melhor = None
    dono = None
    for bloco in resolvidos:
        for grupo in bloco["grupos"]:
            for item in grupo["itens"]:
                url = item["url"]
                if url == "#":
                    continue
                casa = path == url or (url != "/" and path.startswith(url))
                if casa and (melhor is None or len(url) > len(melhor["url"])):
                    melhor, dono = item, bloco
    if melhor is not None:
        melhor["ativo"] = True
        dono["aberto"] = True
    return resolvidos


@register.simple_tag
def icon(name: str, css: str = ""):
    """Ícone do sprite (static/img/icons.svg). Decorativo: o texto ao lado
    (ou o `aria-label` do botão) é quem fala com o leitor de tela."""
    classes = f"icon {css}".strip()
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="{}#{}"/></svg>',
        classes,
        static("img/icons.svg"),
        name,
    )


@register.inclusion_tag("partials/_info.html")
def info(slug: str):
    """Botão "i" que abre o painel de ajuda da tela (apps/core/help_content.py).
    Slug desconhecido não renderiza nada em vez de quebrar a página — um teste
    garante que todo slug usado nos templates existe."""
    return {"slug": slug, "topico": topico_de_ajuda(slug)}


@register.filter
def iniciais(user):
    """Duas letras para o avatar: nome + sobrenome, ou o começo do login."""
    nome = (user.get_full_name() or "").split()
    if len(nome) >= 2:
        return (nome[0][0] + nome[-1][0]).upper()
    return (user.get_username() or "?")[:2].upper()


@register.filter
def sem_marca(value):
    """Tira o ✓/✗/⚠ que as mensagens do servidor trazem na frente: o toast
    mostra um ícone no lugar, então o símbolo textual seria duplicado."""
    texto = str(value)
    for marca in ("✓", "✗", "⚠"):
        if texto.startswith(marca):
            return texto[len(marca) :].lstrip()
    return texto


@register.filter
def get_item(mapping, key):
    """Acesso a dict por chave variável — o template nativo só aceita chave
    literal (`dict.chave`), e `before`/`after` de auditoria vêm como JSON."""
    if not mapping:
        return None
    return mapping.get(key)


@register.simple_tag
def status_badge(status: str, label: str | None = None):
    classe = {
        "RASCUNHO": "badge-rascunho",
        "CONFIRMADA": "badge-confirmada",
        "EXCLUIDA": "badge-excluida",
    }.get(status, "badge-rascunho")
    texto = label or status.capitalize()
    return format_html('<span class="{}">{}</span>', classe, escape(texto))


@register.filter
def brl(value):
    """`Decimal` → "R$ 1.234,56". `None` → "—": dado faltando nunca vira
    `R$ 0,00` (regra 3 do CLAUDE.md)."""
    return dinheiro_br(value)


@register.filter
def numero(value, casas=2):
    """`Decimal` → número em formato brasileiro. `None` → "—"."""
    if value is None or value == "":
        return "—"
    return numero_br(Decimal(value), int(casas))


@register.simple_tag(takes_context=True)
def url_pagina(context, numero_pagina):
    """Querystring atual com `page` trocado — mantém os filtros ao paginar."""
    params = context["request"].GET.copy()
    params["page"] = numero_pagina
    return "?" + params.urlencode()


@register.filter
def pct(value, casas=2):
    """Percentual já em % (51,33). `None` → "—", nunca "—%"."""
    if value is None or value == "":
        return "—"
    return numero_br(Decimal(value), int(casas)) + "%"


@register.filter
def kg(value, casas=0):
    """Peso em kg. `None` → "—", nunca "— kg"."""
    if value is None or value == "":
        return "—"
    return numero_br(Decimal(value), int(casas)) + " kg"


@register.filter
def arroba(value, casas=2):
    """Arrobas. `None` → "—"."""
    if value is None or value == "":
        return "—"
    return numero_br(Decimal(value), int(casas)) + " @"
