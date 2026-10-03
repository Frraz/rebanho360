"""Botão de informação ("i") das telas: todo slug usado nos templates tem
texto, e o painel chega ao HTML com as três seções."""

import re
from pathlib import Path

import pytest
from django.template import Context, Template
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core.help_content import AJUDA, topico_de_ajuda

RAIZ = Path(__file__).resolve().parents[3]
TEMPLATES = RAIZ / "templates"
USO = re.compile(r"""\{%\s*info\s+["']([\w-]+)["']\s*%\}""")
# Telas de cadastro que passam o slug pelo `_form_page.html` (ajuda="...") ou
# pela view (ajuda = "..." / "ajuda": "...").
USO_PARAMETRO = re.compile(r"""\bajuda=["']([\w-]+)["']""")
USO_NA_VIEW = re.compile(
    r"""\bajuda\s*=\s*["']([\w-]+)["']|["']ajuda["']\s*:\s*["']([\w-]+)["']"""
)


def _slugs_usados() -> set[str]:
    achados = set()
    for arquivo in TEMPLATES.rglob("*.html"):
        if arquivo.name == "_info.html":  # o exemplo do comentário
            continue
        texto = arquivo.read_text(encoding="utf-8")
        achados.update(USO.findall(texto))
        achados.update(USO_PARAMETRO.findall(texto))
    for arquivo in (RAIZ / "apps").rglob("views.py"):
        for a, b in USO_NA_VIEW.findall(arquivo.read_text(encoding="utf-8")):
            achados.add(a or b)
    return achados


def test_todo_slug_usado_nos_templates_tem_texto():
    usados = _slugs_usados()
    assert usados, "nenhum {% info %} encontrado: o padrão de busca quebrou?"
    faltando = usados - set(AJUDA)
    assert not faltando, f"slugs sem texto em help_content.py: {sorted(faltando)}"


def test_todo_texto_cadastrado_e_usado_em_alguma_tela():
    # Texto órfão apodrece: ninguém o lê, então ninguém o corrige.
    sobrando = set(AJUDA) - _slugs_usados()
    assert not sobrando, f"textos sem tela: {sorted(sobrando)}"


@pytest.mark.parametrize("slug", sorted(AJUDA))
def test_topico_bem_formado(slug):
    topico = topico_de_ajuda(slug)
    assert topico["titulo"] and topico["resumo"]
    for pergunta, resposta in topico["perguntas"]:
        assert pergunta.endswith("?")
        assert resposta and all(isinstance(p, str) for p in resposta)
    for nome, texto in topico["relacoes"]:
        assert nome and texto


def test_slug_desconhecido_nao_quebra_a_pagina():
    html = Template('{% load core_tags %}[{% info "nao-existe" %}]').render(Context())
    assert "".join(html.split()) == "[]"


def test_painel_traz_as_secoes_e_o_texto_escapado():
    html = Template('{% load core_tags %}{% info "safra" %}').render(Context())
    assert "Para que serve" in html
    assert "Como se liga ao resto do sistema" in html
    assert "Dúvidas comuns" in html
    assert "Corrente" in html


@pytest.mark.django_db
def test_tela_de_safras_tem_o_botao_e_nao_a_descricao_antiga(client):
    admin = User.objects.create_user(username="adm", password="x", role=Role.ADMIN)
    client.force_login(admin)
    resposta = client.get(reverse("organizations:safra_lista"))
    html = resposta.content.decode()
    assert 'class="info-btn"' in html
    assert "O que acontece quando a safra acaba?" in html
    assert "A safra corrente é a que o sistema abre por padrão" not in html


# ------------------------------------------------------------ cobertura das telas

#: Telas que mostram a página inteira (título + conteúdo) mas **não** levam o
#: botão "i", e por quê. Tela nova entra aqui só com motivo; sem motivo, ganha
#: tópico em help_content.py.
ISENTAS = {
    # passo de confirmação de uma ação: o contexto é o da tela de origem
    "accounts/solicitacoes/aprovar.html": "passo de confirmação",
    "accounts/solicitacoes/recusar.html": "passo de confirmação",
    "accounts/usuarios/acao.html": "passo de confirmação",
    "accounts/usuarios/senha.html": "passo de confirmação",
    "procurement/acerto_aprovar.html": "passo de confirmação",
    "procurement/compromisso_aprovar.html": "passo de confirmação",
    "sales/sale_confirm.html": "passo de confirmação",
    "purchases/purchase_confirm.html": "passo de confirmação",
    "finance/titulo_aprovar.html": "passo de confirmação",
    "finance/titulo_programar.html": "passo de confirmação",
    "finance/motivo_form.html": "passo de confirmação (motivo)",
    "finance/sem_titulo.html": "aviso de que não há título",
    "core/impacto_exclusao.html": "análise de impacto: já explica o que será desfeito",
    # fora do menu de trabalho
    "registration/password_change_form.html": "troca de senha, na Conta",
}
#: Templates genéricos cujo slug vem da view (testado abaixo).
DA_VIEW = {
    "commercial/cadastro_form.html",
    "infrastructure/cadastro_form.html",
    "procurement/comissao_form.html",
}
E_TELA = re.compile(r"""class="page-title|partials/_form_page\.html""")


def _paginas_sem_botao() -> list[str]:
    faltando = []
    for arquivo in sorted(TEMPLATES.rglob("*.html")):
        rel = arquivo.relative_to(TEMPLATES).as_posix()
        texto = arquivo.read_text(encoding="utf-8")
        if 'extends "base.html"' not in texto and "{% extends" not in texto:
            continue
        if not E_TELA.search(texto) or rel.startswith("partials/"):
            continue
        if rel in ISENTAS or rel in DA_VIEW:
            continue
        if (
            USO.search(texto)
            or USO_PARAMETRO.search(texto)
            or "{% info ajuda %}" in texto
        ):
            continue
        faltando.append(rel)
    return faltando


def test_toda_tela_tem_o_como_funciona_ou_uma_isencao_com_motivo():
    faltando = _paginas_sem_botao()
    assert not faltando, (
        'telas sem o botão "i" (adicione {% info "slug" %} e o tópico em '
        f"help_content.py, ou justifique em ISENTAS): {faltando}"
    )


def test_isencoes_apontam_para_telas_que_existem():
    for rel in ISENTAS | dict.fromkeys(DA_VIEW, ""):
        assert (TEMPLATES / rel).exists(), f"isenção órfã: {rel}"


def test_views_de_cadastro_genericas_informam_o_slug():
    from apps.commercial import views as comercial
    from apps.infrastructure import views as infra

    for modulo in (comercial, infra):
        for nome in dir(modulo):
            classe = getattr(modulo, nome)
            if (
                isinstance(classe, type)
                and nome.endswith(("CreateView", "UpdateView"))
                and issubclass(classe, modulo._CadastroMixin)
            ):
                assert classe.ajuda in AJUDA, f"{modulo.__name__}.{nome} sem ajuda"
