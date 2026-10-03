"""Dados fixos do seed: quem são as fazendas, os parceiros, os preços-base.

Tudo fictício. Os nomes de pessoa e empresa foram inventados; qualquer
semelhança com cadastro real é coincidência. Nada aqui é lido do banco.
"""

from dataclasses import dataclass, field
from decimal import Decimal

D = Decimal

#: Marca todo parceiro criado pelo seed (`Partner.notes`). O desfazer apaga só
#: o que tem esta marca — nunca procura parceiro por nome, que não é único.
MARCADOR = "[seed-3safras]"

#: Prefixo do código das fazendas e das unidades do seed. É a âncora da purga:
#: tudo que o seed lança pertence a uma fazenda `S3-…`.
PREFIXO = "S3-"

#: Identificador fixo da execução, usado como `request_id` na auditoria. O
#: desfazer o usa para descobrir quais safras o seed criou (e quais já existiam).
SEED_UUID = "5e3d5a37-4b6e-5c4b-9a0e-3a5e5a7b0360"

# Perfis de fazenda
CRIA = "CRIA"
RECRIA = "RECRIA"
ENGORDA = "ENGORDA"
CONFINAMENTO = "CONFINAMENTO"


@dataclass(frozen=True)
class FazendaSeed:
    code: str
    name: str
    city: str
    state: str
    total_ha: int
    pasture_ha: int
    perfil: str
    unidade: str  # "N" ou "CO"
    #: matrizes, touros, desmamados machos, desmamados fêmeas, novilhas — só CRIA.
    #: Em RECRIA/ENGORDA: (cabeças de saldo inicial, categoria) — ver `estoque`.
    estoque: dict = field(default_factory=dict)
    #: peso relativo nas compras diretas
    peso_de_compra: int = 0


FAZENDAS = [
    # ---- cria ---------------------------------------------------------------
    FazendaSeed(
        "S3-SBA",
        "Santa Bárbara",
        "Araguaína",
        "TO",
        2600,
        2200,
        CRIA,
        "N",
        {"matrizes": 640, "touros": 28, "desm_m": 150, "desm_f": 140, "novilhas": 110},
    ),
    FazendaSeed(
        "S3-RDO",
        "Recanto do Ouro",
        "Colinas do Tocantins",
        "TO",
        1900,
        1600,
        CRIA,
        "N",
        {"matrizes": 480, "touros": 22, "desm_m": 110, "desm_f": 100, "novilhas": 80},
    ),
    FazendaSeed(
        "S3-CAB",
        "Cabeceira Alta",
        "Paranã",
        "TO",
        3100,
        2700,
        CRIA,
        "N",
        {"matrizes": 780, "touros": 34, "desm_m": 190, "desm_f": 175, "novilhas": 130},
    ),
    FazendaSeed(
        "S3-PAL",
        "Palmeiras",
        "Gurupi",
        "TO",
        1400,
        1150,
        CRIA,
        "N",
        {"matrizes": 340, "touros": 16, "desm_m": 80, "desm_f": 75, "novilhas": 60},
    ),
    # ---- recria -------------------------------------------------------------
    FazendaSeed(
        "S3-VPA",
        "Vale do Palmital",
        "Miranorte",
        "TO",
        1700,
        1450,
        RECRIA,
        "N",
        {"cabecas": 520},
        peso_de_compra=10,
    ),
    FazendaSeed(
        "S3-TRG",
        "Três Gamelas",
        "Porangatu",
        "GO",
        2100,
        1800,
        RECRIA,
        "CO",
        {"cabecas": 640},
        peso_de_compra=12,
    ),
    FazendaSeed(
        "S3-BAG",
        "Barra da Gameleira",
        "Barra do Garças",
        "MT",
        2400,
        2050,
        RECRIA,
        "CO",
        {"cabecas": 700},
        peso_de_compra=12,
    ),
    # ---- engorda a pasto ----------------------------------------------------
    FazendaSeed(
        "S3-IPE",
        "Ipê Amarelo",
        "Água Boa",
        "MT",
        3400,
        2900,
        ENGORDA,
        "CO",
        {"cabecas": 900},
        peso_de_compra=22,
    ),
    FazendaSeed(
        "S3-SJC",
        "São João da Chapada",
        "Cocalinho",
        "MT",
        2800,
        2400,
        ENGORDA,
        "CO",
        {"cabecas": 760},
        peso_de_compra=18,
    ),
    FazendaSeed(
        "S3-MTD",
        "Monte Dourado",
        "Nova Xavantina",
        "MT",
        2200,
        1900,
        ENGORDA,
        "CO",
        {"cabecas": 620},
        peso_de_compra=14,
    ),
    # ---- confinamento -------------------------------------------------------
    FazendaSeed(
        "S3-CNF",
        "Confinamento Boa Esperança",
        "Gurupi",
        "TO",
        380,
        120,
        CONFINAMENTO,
        "N",
        {"cabecas": 0},
        peso_de_compra=12,
    ),
    FazendaSeed(
        "S3-CNP",
        "Confinamento Pé de Serra",
        "Porangatu",
        "GO",
        260,
        90,
        CONFINAMENTO,
        "CO",
        {"cabecas": 0},
        peso_de_compra=8,
    ),
]

UNIDADES = {
    "N": ("S3-N", "Unidade Norte (Tocantins)"),
    "CO": ("S3-CO", "Unidade Centro-Oeste (Goiás e Mato Grosso)"),
}

# ---------------------------------------------------------------------------
# Parceiros: (nome, papéis, cidade, UF)
# ---------------------------------------------------------------------------

PRODUTORES = [
    ("Agropecuária Boa Vista Ltda", ["PRODUTOR", "FORNECEDOR"], "Araguaína", "TO", 26),
    ("Waldemar Secchi Neto", ["PRODUTOR"], "Colinas do Tocantins", "TO", 14),
    (
        "Fazenda Santa Luzia Pecuária",
        ["PRODUTOR", "FORNECEDOR"],
        "Paraíso do Tocantins",
        "TO",
        12,
    ),
    ("José Carlos Tavares", ["PRODUTOR"], "Miracema do Tocantins", "TO", 9),
    ("Pecuária Três Irmãos S/A", ["PRODUTOR", "PECUARISTA"], "Redenção", "PA", 9),
    ("Agro Cerrado do Norte", ["PRODUTOR", "FORNECEDOR"], "Gurupi", "TO", 8),
    ("Marcos Oliveira Andrade", ["PRODUTOR"], "Porangatu", "GO", 6),
    ("Fazenda Barra Grande", ["PRODUTOR"], "Alto Araguaia", "MT", 6),
    ("Pedro Henrique Lima", ["PRODUTOR"], "Água Boa", "MT", 5),
    ("Rancho Dois Córregos", ["PRODUTOR", "FORNECEDOR"], "Canarana", "MT", 5),
    ("Espólio de Antônio Figueiredo", ["PRODUTOR"], "Goianésia", "GO", 4),
    (
        "Cia. Agropastoril Vale Verde",
        ["PRODUTOR", "FORNECEDOR"],
        "Barra do Garças",
        "MT",
        4,
    ),
    ("Luciana Prado Mendes", ["PRODUTOR"], "Nova Xavantina", "MT", 3),
    ("Fazenda Ribeirão Claro", ["PRODUTOR"], "Xambioá", "TO", 3),
    ("Sebastião Rocha Filho", ["PRODUTOR"], "Pium", "TO", 3),
    ("Grupo Pecuário Horizonte", ["PRODUTOR", "PECUARISTA"], "Campinorte", "GO", 2),
]

COMPRADORES = [
    ("Frigorífico Vale do Tocantins S/A", ["FRIGORIFICO"], "Araguaína", "TO", 30),
    ("Marfrig Araguaína Unidade 2", ["FRIGORIFICO"], "Araguaína", "TO", 22),
    ("Frigorífico Cerrado Central", ["FRIGORIFICO"], "Porangatu", "GO", 16),
    ("Frigorífico Xingu Carnes", ["FRIGORIFICO"], "Água Boa", "MT", 14),
    ("Coperfrigu Cooperativa", ["FRIGORIFICO", "COMPRADOR"], "Gurupi", "TO", 10),
    ("Açougue e Distribuidora Real", ["COMPRADOR"], "Palmas", "TO", 4),
    (
        "Pecuária Bom Pastor (recria)",
        ["COMPRADOR", "PRODUTOR"],
        "Colinas do Tocantins",
        "TO",
        3,
    ),
    ("Leilões Rural Norte", ["COMPRADOR"], "Araguaína", "TO", 1),
]

TRANSPORTADORAS = [
    ("Transportes Tocantins Ltda", ["TRANSPORTADOR"], "Araguaína", "TO"),
    ("Frota Araguaia Boiadeiros", ["TRANSPORTADOR"], "Barra do Garças", "MT"),
    ("Boiadeiro Express", ["TRANSPORTADOR"], "Gurupi", "TO"),
    ("Rodoboi Transportes", ["TRANSPORTADOR"], "Porangatu", "GO"),
    ("Cavalcante & Filhos Cargas", ["TRANSPORTADOR", "FORNECEDOR"], "Palmas", "TO"),
]

COMISSIONADOS = [
    ("Cláudia Ferreira Dias", ["COMISSIONADO"], "Araguaína", "TO"),
    ("Edson Barbosa Compra de Gado", ["COMISSIONADO"], "Gurupi", "TO"),
    (
        "Márcio Tavares Intermediação",
        ["COMISSIONADO", "PECUARISTA"],
        "Barra do Garças",
        "MT",
    ),
]

#: Quem recebe tributo e taxa: o acerto exige favorecido e vencimento informados.
FAVORECIDOS_DE_TRIBUTO = [
    ("Receita Federal — Funrural", ["FAVORECIDO"], "Brasília", "DF"),
    ("Fundepec — Fundo de Desenvolvimento da Pecuária", ["FAVORECIDO"], "Palmas", "TO"),
    ("Agência de Defesa Agropecuária — GTA e taxas", ["FAVORECIDO"], "Palmas", "TO"),
    ("Secretaria da Fazenda — ICMS", ["FAVORECIDO"], "Goiânia", "GO"),
]

# Bancos fictícios para as contas dos parceiros.
BANCOS = [
    ("001", "Banco do Brasil"),
    ("104", "Caixa Econômica Federal"),
    ("756", "Sicoob"),
    ("748", "Sicredi"),
    ("237", "Bradesco"),
]

# ---------------------------------------------------------------------------
# Gado: peso de entrada (kg) e R$/kg vivo na @ de R$ 250
# ---------------------------------------------------------------------------

CAT_BEZ_M = "Bezerros Mamando"
CAT_BEZ_F = "Bezerras Mamando"
CAT_DESM_M = "Machos Desm. até 12m"
CAT_DESM_F = "Fêmeas Desm. até 12m"
CAT_M13 = "Machos 13 a 24 meses"
CAT_F13 = "Fêmeas 13 a 24 meses"
CAT_M25 = "Machos 25 a 36 meses"
CAT_F25 = "Fêmeas 25 a 36 meses"
CAT_TOURO = "Touros"
CAT_MATRIZ = "Fêmeas + 36 meses"

#: nome → (sexo, ordem de idade). Só usado se a categoria não existir no banco.
CATEGORIAS_PADRAO = {
    CAT_BEZ_M: ("M", 1),
    CAT_BEZ_F: ("F", 1),
    CAT_DESM_M: ("M", 2),
    CAT_DESM_F: ("F", 2),
    CAT_M13: ("M", 3),
    CAT_F13: ("F", 3),
    CAT_M25: ("M", 4),
    CAT_F25: ("F", 4),
    CAT_TOURO: ("M", 5),
    CAT_MATRIZ: ("F", 5),
    "Tropa": ("-", None),
}

RACAS = ["Nelore", "Nelore PO", "Angus x Nelore", "Tabapuã", "Brahman"]

#: peso médio na entrada (kg), R$/kg vivo (a @ de R$ 250) e peso de abate-alvo.
PRECOS = {
    CAT_DESM_M: (D("205"), D("14.40")),
    CAT_DESM_F: (D("190"), D("12.90")),
    CAT_M13: (D("305"), D("12.30")),
    CAT_F13: (D("272"), D("10.90")),
    CAT_M25: (D("425"), D("11.50")),
    CAT_F25: (D("360"), D("10.40")),
    CAT_TOURO: (D("760"), D("17.50")),
    CAT_MATRIZ: (D("450"), D("10.60")),
}

#: Categoria seguinte na linha de idade (a EVOLUÇÃO).
PROXIMA = {
    CAT_BEZ_M: CAT_DESM_M,
    CAT_BEZ_F: CAT_DESM_F,
    CAT_DESM_M: CAT_M13,
    CAT_DESM_F: CAT_F13,
    CAT_M13: CAT_M25,
    CAT_F13: CAT_F25,
    CAT_M25: None,
    CAT_F25: CAT_MATRIZ,
}

# ---------------------------------------------------------------------------
# Custos mensais: centro → (R$ por mês por 1.000 cabeças, classe, descrição)
# ---------------------------------------------------------------------------

CENTROS = {
    "FUNCIONARIO": (D("11000"), "CUSTEIO", "Folha e encargos do pessoal de campo"),
    "PARQUE DE MÁQUINAS": (
        D("6800"),
        "CUSTEIO",
        "Diesel, peças e manutenção das máquinas",
    ),
    "NUTRIÇÃO": (D("9700"), "CUSTEIO", "Sal mineral, proteinado e ração"),
    "PASTAGEM": (D("8100"), "CUSTEIO", "Adubação, roçada e reforma de pasto"),
    "SANIDADE": (D("2100"), "CUSTEIO", "Vacinas, vermífugos e veterinário"),
    "INFRAESTRUTURA": (
        D("2900"),
        "INVESTIMENTO",
        "Cercas, currais, bebedouros e cochos",
    ),
    "IMPOSTO E TAXAS": (D("800"), "CUSTEIO", "ITR, taxas e licenças"),
    "OUTROS": (D("850"), "CUSTEIO", "Despesas diversas da fazenda"),
    "DESPESA GADO": (D("1700"), "CUSTEIO", "Despesas gerais com o gado"),
}

#: Custo direto no lote: (centro, R$ por cabeça, descrição)
CUSTOS_DE_ENTRADA = [
    ("SANIDADE", D("24"), "Vacinas e vermífugo de entrada"),
    ("DESPESA GADO", D("6"), "Brinco e manejo de entrada"),
]

ESTRUTURAS_POR_PERFIL = {
    CRIA: [
        ("CURRAL", "Curral de manejo principal", 1800, None, None, 600),
        ("CURRAL", "Curral de apartação", 900, None, None, 300),
        ("COCHO", "Cocho coberto de sal", None, 240, None, 600),
        ("BEBEDOURO", "Bebedouros do Piquete 1 ao 6", None, None, 12, 650),
        ("BARRACAO", "Barracão de insumos", 480, None, None, None),
    ],
    RECRIA: [
        ("CURRAL", "Curral de manejo", 1500, None, None, 700),
        ("COCHO", "Cochos de proteinado", None, 300, None, 700),
        ("BEBEDOURO", "Bebedouros dos piquetes", None, None, 14, 700),
        ("BARRACAO", "Galpão de máquinas", 600, None, None, None),
    ],
    ENGORDA: [
        ("CURRAL", "Curral de embarque", 2200, None, None, 900),
        ("COCHO", "Cochos de suplementação", None, 420, None, 900),
        ("BEBEDOURO", "Bebedouros dos piquetes", None, None, 18, 900),
        ("BARRACAO", "Galpão de máquinas", 700, None, None, None),
    ],
    CONFINAMENTO: [
        ("CURRAL", "Baias de confinamento 1 a 8", 9000, None, None, 450),
        ("COCHO", "Cochos de trato", None, 520, None, 450),
        ("BEBEDOURO", "Bebedouros das baias", None, None, 16, 450),
        ("BARRACAO", "Fábrica de ração", 900, None, None, None),
    ],
}

MAQUINAS_POR_PERFIL = {
    CRIA: [
        ("Trator John Deere 5090", "TRATOR", 380000),
        ("Caminhonete Hilux", "UTILITARIO", 260000),
    ],
    RECRIA: [
        ("Trator New Holland TL75", "TRATOR", 310000),
        ("Caminhonete Ranger", "UTILITARIO", 240000),
    ],
    ENGORDA: [
        ("Trator Valtra A950", "TRATOR", 340000),
        ("Caminhão Volkswagen Delivery", "CAMINHAO", 290000),
        ("Roçadeira hidráulica", "IMPLEMENTO", 58000),
    ],
    CONFINAMENTO: [
        ("Pá-carregadeira Case W20", "OUTRO", 520000),
        ("Vagão misturador 12 m³", "IMPLEMENTO", 210000),
        ("Trator Massey 4275", "TRATOR", 330000),
    ],
}

TIPOS_DE_PASTO = [
    "PASTAGEM",
    "PASTAGEM",
    "PASTAGEM",
    "PASTAGEM",
    "SILAGEM",
    "RESERVA_APP",
    "BENFEITORIA",
]
