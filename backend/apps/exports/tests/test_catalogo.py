"""O catálogo é a barreira de segurança da exportação: estes testes impedem
que um modelo novo entre sem escopo, ou que um segredo saia por esquecimento."""

import pytest
from django.apps import apps as django_apps

from apps.accounts.models import Role, User
from apps.exports import catalog, tabular
from apps.exports.tabular import LEGIVEL, TECNICO, Filtros

pytestmark = pytest.mark.django_db

APPS_DO_SISTEMA = {
    "accounts",
    "audit",
    "organizations",
    "properties",
    "partners",
    "livestock",
    "herd",
    "costs",
    "purchases",
    "sales",
    "finance",
    "commercial",
    "procurement",
    "imports",
    "documents",
    "exports",
}


def test_todo_modelo_do_sistema_esta_no_catalogo_ou_tem_motivo_para_nao_estar():
    no_catalogo = {c.modelo for c in catalog.CONJUNTOS}
    esquecidos = []
    for modelo in django_apps.get_models():
        if modelo._meta.app_label not in APPS_DO_SISTEMA:
            continue
        if modelo._meta.label not in no_catalogo | set(catalog.NAO_EXPORTAVEIS):
            esquecidos.append(modelo._meta.label)
    assert not esquecidos, (
        f"Modelos fora da exportação, sem decisão: {esquecidos}. Ponha em "
        "catalog.CONJUNTOS (com escopo e permissão) ou em NAO_EXPORTAVEIS, com o motivo."
    )


def test_o_catalogo_nao_aponta_para_modelo_que_nao_existe():
    for conjunto in catalog.CONJUNTOS:
        assert conjunto.classe is not None, conjunto.chave
    for rotulo in catalog.NAO_EXPORTAVEIS:
        assert django_apps.get_model(rotulo)


def test_chaves_do_catalogo_sao_unicas_e_ascii():
    chaves = [c.chave for c in catalog.CONJUNTOS]
    assert len(chaves) == len(set(chaves))
    assert all(c.isascii() and c == c.lower() and " " not in c for c in chaves)


def test_modelo_com_fazenda_declara_escopo():
    """Todo modelo que liga direto a uma fazenda tem `escopo`; o que liga
    por um documento pai declara o caminho até a fazenda."""
    sem_escopo = []
    for conjunto in catalog.CONJUNTOS:
        liga_direto = any(
            f.is_relation and f.related_model._meta.label == "properties.Farm"
            for f in conjunto.classe._meta.concrete_fields
        )
        if liga_direto and not conjunto.escopo:
            sem_escopo.append(conjunto.chave)
    assert not sem_escopo, f"liga a Farm mas sem escopo: {sem_escopo}"


def test_os_caminhos_declarados_existem_e_chegam_onde_dizem():
    for conjunto in catalog.CONJUNTOS:
        modelo = conjunto.classe
        for caminho in conjunto.escopo:
            if caminho == "pk":
                assert modelo._meta.label == "properties.Farm"
                continue
            campo = tabular._campo_do_caminho(modelo, caminho)
            assert campo.related_model._meta.label == "properties.Farm", (
                conjunto.chave,
                caminho,
            )
        if conjunto.safra:
            campo = tabular._campo_do_caminho(modelo, conjunto.safra)
            assert campo.related_model._meta.label == "organizations.Season"
        if conjunto.data:
            campo = tabular._campo_do_caminho(modelo, conjunto.data)
            assert campo.get_internal_type() in ("DateField", "DateTimeField")
        if conjunto.pai_excluido:
            tabular._campo_do_caminho(modelo, conjunto.pai_excluido.rsplit("__", 1)[0])


@pytest.mark.parametrize("papel", list(Role))
def test_nenhuma_coluna_de_nenhum_conjunto_e_segredo(papel):
    user = User(username="x", role=papel, is_superuser=True)
    for conjunto in catalog.CONJUNTOS:
        for modo in (TECNICO, LEGIVEL):
            for coluna in tabular.colunas_do_conjunto(conjunto, user, modo):
                assert not tabular.CAMPO_PROIBIDO.search(coluna.chave), (
                    conjunto.chave,
                    coluna.chave,
                )


def test_senha_e_segundo_fator_nunca_saem():
    admin = User(username="a", role=Role.ADMIN)
    usuarios = catalog.conjunto_por_chave("usuarios")
    chaves = {c.chave for c in tabular.colunas_do_conjunto(usuarios, admin, TECNICO)}
    assert "password" not in chaves
    assert {"username", "email", "role"} <= chaves
    assert "accounts.TOTPDevice" in catalog.NAO_EXPORTAVEIS
    assert "accounts.RecoveryCode" in catalog.NAO_EXPORTAVEIS
    assert not [c for c in catalog.CONJUNTOS if c.modelo.startswith("accounts.TOTP")]


@pytest.mark.parametrize(
    "papel,visiveis,invisiveis",
    [
        (Role.ADMIN, {"usuarios", "auditoria", "titulos", "contas-bancarias"}, set()),
        (
            Role.GESTOR,
            {"titulos", "contas-bancarias", "compromissos", "importacoes"},
            {"usuarios", "auditoria"},
        ),
        (
            Role.ESCRITORIO,
            {"titulos", "compromissos", "importacoes", "lotes"},
            {"usuarios", "auditoria", "contas-bancarias"},
        ),
        (
            Role.FINANCEIRO,
            {"titulos", "contas-bancarias", "compromissos", "lotes"},
            {"usuarios", "auditoria", "importacoes"},
        ),
        (
            Role.CONSULTA,
            {"titulos", "compromissos", "lotes"},
            {"usuarios", "auditoria", "contas-bancarias", "importacoes"},
        ),
        (
            Role.CAMPO,
            {"lotes", "pesagens", "razao-do-rebanho"},
            {"titulos", "compromissos", "usuarios", "contas-bancarias", "auditoria"},
        ),
    ],
)
def test_cada_papel_so_ve_o_que_a_tela_dele_ja_mostra(papel, visiveis, invisiveis):
    user = User(username="x", role=papel)
    chaves = {c.chave for c in catalog.conjuntos_para(user)}
    assert visiveis <= chaves
    assert not (invisiveis & chaves)


def test_a_conta_bancaria_do_titulo_so_sai_para_quem_ve_dado_bancario():
    titulos = catalog.conjunto_por_chave("titulos")
    escritorio = User(username="e", role=Role.ESCRITORIO)
    financeiro = User(username="f", role=Role.FINANCEIRO)
    do_escritorio = {
        c.chave for c in tabular.colunas_do_conjunto(titulos, escritorio, LEGIVEL)
    }
    do_financeiro = {
        c.chave for c in tabular.colunas_do_conjunto(titulos, financeiro, LEGIVEL)
    }
    assert (
        "bank_account" not in do_escritorio and "bank_account_id" not in do_escritorio
    )
    assert "bank_account" in do_financeiro


def test_modelo_com_scoped_manager_usa_for_user(escritorio_baixao, operacao):
    """Onde o modelo já tem `for_user` (regra 4), a exportação devolve
    exatamente o que ele devolve."""
    comparados = 0
    for conjunto in catalog.CONJUNTOS:
        manager = conjunto.classe._default_manager
        if not hasattr(manager, "for_user"):
            continue
        esperado = set(manager.for_user(escritorio_baixao).values_list("pk", flat=True))
        obtido = set(
            tabular.consulta(
                conjunto, escritorio_baixao, Filtros(incluir_excluidos=True)
            ).values_list("pk", flat=True)
        )
        assert obtido == esperado, conjunto.chave
        comparados += 1
    assert comparados >= 8
