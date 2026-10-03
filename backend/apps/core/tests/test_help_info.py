"""Botão de informação ("i") das telas: todo slug usado nos templates tem
texto, e o painel chega ao HTML com as três seções."""

import re
from pathlib import Path

import pytest
from django.template import Context, Template
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core.help_content import AJUDA, topico_de_ajuda

TEMPLATES = Path(__file__).resolve().parents[3] / "templates"
USO = re.compile(r"""\{%\s*info\s+["']([\w-]+)["']\s*%\}""")


def _slugs_usados() -> set[str]:
    achados = set()
    for arquivo in TEMPLATES.rglob("*.html"):
        if arquivo.name == "_info.html":  # o exemplo do comentário
            continue
        achados.update(USO.findall(arquivo.read_text(encoding="utf-8")))
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
