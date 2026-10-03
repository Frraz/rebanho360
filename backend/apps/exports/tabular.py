"""De um conjunto do catálogo para linhas e colunas.

Dois "modos" de leitura do mesmo dado:

- **técnico** (JSON): o dado como está no banco — vínculo é o `id`, escolha é o
  código (`CONFIRMADA`), `Decimal` é texto exato, data é ISO. Quem vai
  reimportar ou processar por programa quer isto.
- **legível** (CSV, planilha, PDF): vínculo é o nome (`Lote LT-SFR-014`),
  escolha é o rótulo (`Confirmada`), e, no CSV e na planilha, uma coluna com o
  `id` ao lado de cada vínculo para dar para religar as tabelas.

Nada é calculado aqui: só se lê o que está gravado (regra 6). Valor vazio
continua vazio — "—" é coisa de tela, e só o PDF o usa.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.core.formatting import numero_br
from apps.core.reversible import Status
from apps.reports.services import neutralizar_formula

TECNICO, LEGIVEL = "tecnico", "legivel"

TEXTO, INTEIRO, DECIMAL, DATA, DATAHORA, BOOLEANO, ESTRUTURA = (
    "texto",
    "inteiro",
    "decimal",
    "data",
    "datahora",
    "booleano",
    "estrutura",
)

#: Rede de segurança do catálogo: nome de campo que lembra segredo nunca entra
#: numa exportação, mesmo que alguém esqueça de pô-lo em `sem`.
CAMPO_PROIBIDO = re.compile(r"password|secret|totp|recovery|code_hash|token", re.I)

#: Campos de controle: ficam no CSV/XLSX/JSON, mas não ocupam o PDF.
TECNICOS_DO_PDF = {
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "version",
    "deleted_at",
    "deleted_by",
    "delete_reason",
    "removed_at",
    "removed_by",
    "notes",
}
MAXIMO_COLUNAS_NO_PDF = 9

#: Quem criou, quando mudou, versão, exclusão: importa, mas vai para o fim da
#: tabela. O que o produtor procura (código, data, valor) fica à esquerda.
CAMPOS_DE_CONTROLE = {
    "version",
    "deleted_at",
    "deleted_by",
    "delete_reason",
    "created_by",
    "created_at",
    "updated_by",
    "updated_at",
    "removed_at",
    "removed_by",
}


def _posicao(campo) -> int:
    if campo.name == "id":
        return 0
    if campo.name in CAMPOS_DE_CONTROLE:
        return 3
    return 2 if campo.name == "status" else 1


@dataclass(frozen=True)
class Filtros:
    """O que o usuário restringiu na tela. Tudo opcional."""

    fazenda: object | None = None
    safra: object | None = None
    de: date | None = None
    ate: date | None = None
    incluir_excluidos: bool = False


@dataclass(frozen=True)
class Coluna:
    chave: str
    rotulo: str
    tipo: str
    campo: str  # nome do atributo no modelo (para vínculo técnico, o `*_id`)
    origem: str = "valor"  # "valor" | "vinculo" | "escolha"
    casas: int | None = None
    escolhas: tuple = ()  # ((código, rótulo), ...)
    aponta_para: str = ""  # "app.Modelo" do vínculo, para o dicionário de dados

    def eh_numerica(self) -> bool:
        return self.tipo in (INTEIRO, DECIMAL)


class Rotulos:
    """Nome de cada registro vinculado, calculado uma vez só. Sem isto, um
    razão com 50 mil linhas pediria o nome do mesmo lote 50 mil vezes."""

    LIMITE = 100_000

    def __init__(self):
        self._cache: dict[tuple, str] = {}

    def de(self, registro) -> str:
        if registro is None:
            return ""
        chave = (type(registro), registro.pk)
        achado = self._cache.get(chave)
        if achado is None:
            if len(self._cache) >= self.LIMITE:
                self._cache.clear()
            achado = self._cache[chave] = str(registro)
        return achado


# --------------------------------------------------------------------------
# Colunas
# --------------------------------------------------------------------------


def _tipo_do_campo(campo) -> tuple[str, int | None]:
    interno = campo.get_internal_type()
    if interno == "DecimalField":
        return DECIMAL, campo.decimal_places
    if interno in (
        "AutoField",
        "BigAutoField",
        "IntegerField",
        "BigIntegerField",
        "SmallIntegerField",
        "PositiveIntegerField",
        "PositiveBigIntegerField",
        "PositiveSmallIntegerField",
    ):
        return INTEIRO, None
    if interno == "DateTimeField":
        return DATAHORA, None
    if interno == "DateField":
        return DATA, None
    if interno == "BooleanField":
        return BOOLEANO, None
    if interno == "JSONField":
        return ESTRUTURA, None
    return TEXTO, None


def _rotulo(campo) -> str:
    texto = str(campo.verbose_name)
    return texto[:1].upper() + texto[1:]


def campos_do_conjunto(conjunto, user) -> list:
    """Os campos concretos que este usuário pode exportar deste conjunto."""
    escolhidos = []
    for campo in conjunto.classe._meta.concrete_fields:
        if conjunto.campos and campo.name not in conjunto.campos:
            continue
        if campo.name in conjunto.sem or CAMPO_PROIBIDO.search(campo.name):
            continue
        restricao = conjunto.restritos.get(campo.name)
        if restricao is not None and not restricao(user):
            continue
        escolhidos.append(campo)
    return sorted(escolhidos, key=_posicao)


def colunas_do_conjunto(conjunto, user, modo: str, *, com_ids: bool = True):
    colunas: list[Coluna] = []
    for campo in campos_do_conjunto(conjunto, user):
        rotulo = _rotulo(campo)
        if campo.is_relation:
            alvo = campo.related_model._meta.label
            if modo == TECNICO:
                colunas.append(
                    Coluna(
                        campo.name,
                        rotulo,
                        INTEIRO,
                        campo.attname,
                        aponta_para=alvo,
                    )
                )
            else:
                colunas.append(
                    Coluna(
                        campo.name,
                        rotulo,
                        TEXTO,
                        campo.name,
                        origem="vinculo",
                        aponta_para=alvo,
                    )
                )
                if com_ids:
                    colunas.append(
                        Coluna(
                            f"{campo.name}_id",
                            f"{rotulo} (ID)",
                            INTEIRO,
                            campo.attname,
                            aponta_para=alvo,
                        )
                    )
            continue
        tipo, casas = _tipo_do_campo(campo)
        if modo == LEGIVEL and campo.choices:
            colunas.append(
                Coluna(
                    campo.name,
                    rotulo,
                    TEXTO,
                    campo.name,
                    origem="escolha",
                    escolhas=tuple((str(k), str(v)) for k, v in campo.flatchoices),
                )
            )
            continue
        colunas.append(Coluna(campo.name, rotulo, tipo, campo.name, casas=casas))
    return colunas


def colunas_do_pdf(conjunto, colunas_legiveis: list[Coluna]) -> list[Coluna]:
    """O PDF é para ler, não para guardar: as colunas principais. O resto
    está no CSV, na planilha e no JSON (o PDF diz isso no cabeçalho)."""
    por_chave = {c.chave: c for c in colunas_legiveis}
    if conjunto.pdf:
        return [por_chave[k] for k in conjunto.pdf if k in por_chave]
    candidatas = [
        c
        for c in colunas_legiveis
        if c.chave not in TECNICOS_DO_PDF
        and not c.chave.endswith("_id")
        and c.chave != "id"
        and c.tipo != ESTRUTURA
    ]
    return candidatas[:MAXIMO_COLUNAS_NO_PDF]


def vinculos_a_carregar(conjunto, user) -> list[str]:
    return [c.name for c in campos_do_conjunto(conjunto, user) if c.is_relation]


# --------------------------------------------------------------------------
# Consulta (escopo + filtros)
# --------------------------------------------------------------------------


def _ou(caminhos: tuple[str, ...], operador: str, valor) -> Q:
    consulta = Q()
    for caminho in caminhos:
        consulta |= Q(**{f"{caminho}{operador}": valor})
    return consulta


def _campo_do_caminho(modelo, caminho: str):
    campo = None
    for parte in caminho.split("__"):
        campo = modelo._meta.get_field(parte)
        modelo = campo.related_model
    return campo


def consulta(conjunto, user, filtros: Filtros):
    """O queryset do conjunto, **dentro do escopo do usuário** e com os
    filtros do pedido. É o único lugar que monta a leitura: escopo esquecido
    aqui seria vazamento em todos os formatos de uma vez."""
    modelo = conjunto.classe
    incluir = filtros.incluir_excluidos

    if conjunto.exclusao == "linhas" and incluir:
        # Linha retirada de um documento: o gerenciador padrão a esconde.
        base = modelo.all_objects.all()
    else:
        base = modelo._default_manager.all()

    # Escopo por fazenda (regra 4). `for_user` onde o modelo tem ScopedManager;
    # nos demais (vínculo indireto: linhas, viagens...), o caminho declarado.
    if conjunto.escopo:
        if hasattr(base, "for_user"):
            base = base.for_user(user)
        elif not user.has_broad_access:
            ids = list(user.farm_access.values_list("farm_id", flat=True))
            base = base.filter(_ou(conjunto.escopo, "__in", ids))
    if conjunto.limitar is not None:
        base = conjunto.limitar(base, user)

    if filtros.fazenda is not None and conjunto.escopo:
        base = base.filter(_ou(conjunto.escopo, "", filtros.fazenda.pk))
    if filtros.safra is not None and conjunto.safra:
        base = base.filter(**{conjunto.safra: filtros.safra})
    if conjunto.data and (filtros.de or filtros.ate):
        sufixo = (
            "__date"
            if _campo_do_caminho(modelo, conjunto.data).get_internal_type()
            == "DateTimeField"
            else ""
        )
        if filtros.de:
            base = base.filter(**{f"{conjunto.data}{sufixo}__gte": filtros.de})
        if filtros.ate:
            base = base.filter(**{f"{conjunto.data}{sufixo}__lte": filtros.ate})

    if not incluir:
        if conjunto.exclusao == "status":
            base = base.exclude(status=Status.EXCLUIDA)
        elif conjunto.exclusao == "usuario":
            base = base.filter(deleted_at__isnull=True)
        if conjunto.pai_excluido:
            base = base.exclude(**{conjunto.pai_excluido: Status.EXCLUIDA})

    if not base.ordered:
        base = base.order_by("pk")
    return base


def contar(conjunto, user, filtros: Filtros) -> int:
    return consulta(conjunto, user, filtros).count()


# --------------------------------------------------------------------------
# Valores
# --------------------------------------------------------------------------


def extrator(coluna: Coluna, rotulos: Rotulos):
    """Função `registro -> valor` já com o `getattr` resolvido: o laço de
    50 mil linhas não decide nada, só chama."""
    campo = coluna.campo
    if coluna.origem == "vinculo":
        return lambda r: rotulos.de(getattr(r, campo))
    if coluna.origem == "escolha":
        mapa = dict(coluna.escolhas)
        return lambda r: mapa.get(str(getattr(r, campo)), getattr(r, campo))
    return lambda r: getattr(r, campo)


def linhas_do_conjunto(registros, colunas: list[Coluna], rotulos: Rotulos) -> Iterator:
    funcoes = [extrator(c, rotulos) for c in colunas]
    for registro in registros:
        yield [f(registro) for f in funcoes]


def _local(valor: datetime) -> datetime:
    return timezone.localtime(valor) if timezone.is_aware(valor) else valor


def para_json(valor):
    """Valor pronto para `json.dumps`: `Decimal` como texto exato (nunca
    `float`), data e hora em ISO-8601, o resto como veio."""
    if isinstance(valor, Decimal):
        return format(valor, "f")
    if isinstance(valor, datetime):
        return _local(valor).isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, bool | int | str | list | dict) or valor is None:
        return valor
    return str(valor)  # UUID, IP...


def _texto_estrutura(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str, separators=(",", ":"))


def para_csv(valor, tipo: str, *, br: bool) -> str:
    """Texto de uma célula de CSV. `br`: separador decimal vírgula e data
    dd/mm/aaaa (o Excel brasileiro abre sem reclamar); senão, ponto e ISO."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, Decimal):
        texto = format(valor, "f")
        return texto.replace(".", ",") if br else texto
    if isinstance(valor, datetime):
        local = _local(valor)
        return local.strftime("%d/%m/%Y %H:%M") if br else local.isoformat()
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y") if br else valor.isoformat()
    if tipo == ESTRUTURA or isinstance(valor, list | dict):
        return neutralizar_formula(_texto_estrutura(valor))
    if isinstance(valor, int):
        return str(valor)
    return neutralizar_formula(str(valor))


def para_pdf(valor, tipo: str) -> str:
    """Texto de uma célula de PDF: formatação brasileira, "—" onde falta."""
    if valor is None or valor == "":
        return "—"
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, Decimal):
        casas = max(0, -valor.as_tuple().exponent)
        return numero_br(valor, casas)
    if isinstance(valor, datetime):
        return _local(valor).strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if tipo == ESTRUTURA or isinstance(valor, list | dict):
        texto = _texto_estrutura(valor)
        return texto if len(texto) <= 120 else texto[:117] + "…"
    if isinstance(valor, int):
        return numero_br(Decimal(valor), 0) if tipo == INTEIRO else str(valor)
    texto = str(valor)
    return texto if len(texto) <= 160 else texto[:157] + "…"
