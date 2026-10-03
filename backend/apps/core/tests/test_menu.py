"""O menu segue o desenho do escopo funcional (docs/fontes/imagem.jpeg):
três blocos, cada um com cinco grupos — recolhíveis, com "Início" fixo no topo."""

import pytest
from django.test import RequestFactory

from apps.accounts.models import Role, User
from apps.core.templatetags.core_tags import MENU, nav_menu

pytestmark = pytest.mark.django_db


def _menu(user, path="/"):
    request = RequestFactory().get(path)
    request.user = user
    return nav_menu({"request": request})


def _grupos(resolvido, bloco):
    return [g["titulo"] for b in resolvido if b["titulo"] == bloco for g in b["grupos"]]


def _abertos(resolvido):
    return [b["titulo"] for b in resolvido if b["aberto"] and b["titulo"]]


def test_tres_blocos_da_imagem_com_cinco_grupos_cada():
    nomes = [bloco for bloco, _icone, _grupos in MENU]
    assert nomes[:3] == ["Entrada", "Movimentações", "Relatórios e Análise"]
    for bloco, _icone, grupos in MENU[:3]:
        assert len(grupos) == 5, bloco


def test_gestor_ve_todos_os_grupos_da_imagem():
    gestor = User.objects.create_user(username="g", password="x", role=Role.GESTOR)
    menu = _menu(gestor)

    assert _grupos(menu, "Entrada") == [
        "Empresa / Propriedades",
        "Parceiros",
        "Rebanho / Produtos / Lotes",
        "Comercial",
        "Custos / Centros de Custo",
    ]
    assert "Programação / Embarque" in _grupos(menu, "Movimentações")
    assert "Recebimento / Acerto" in _grupos(menu, "Movimentações")


def test_campo_nao_ve_o_ciclo_de_compra():
    # Preço, comissão e frete são dado comercial (regras-negocio/08).
    campo = User.objects.create_user(username="c", password="x", role=Role.CAMPO)
    menu = _menu(campo)

    movimentacoes = _grupos(menu, "Movimentações")
    assert "Programação / Embarque" not in movimentacoes
    assert "Recebimento / Acerto" not in movimentacoes
    assert "Compra / Compromisso" in movimentacoes  # Compras diretas continuam


def test_relatorio_do_menu_aponta_o_slug_e_acende_so_um_item():
    gestor = User.objects.create_user(username="g", password="x", role=Role.GESTOR)
    menu = _menu(gestor, "/relatorios/fretes-e-quebra/")

    ativos = [
        i["rotulo"] for b in menu for g in b["grupos"] for i in g["itens"] if i["ativo"]
    ]
    assert ativos == ["Fretes e quebra de viagem"]


def test_inicio_fica_fixo_no_topo_fora_dos_blocos():
    gestor = User.objects.create_user(username="g", password="x", role=Role.GESTOR)
    menu = _menu(gestor, "/compras/")

    assert menu[0]["titulo"] is None
    assert [i["rotulo"] for i in menu[0]["grupos"][0]["itens"]] == ["Início"]


def test_so_o_bloco_da_tela_atual_abre():
    gestor = User.objects.create_user(username="g", password="x", role=Role.GESTOR)

    assert _abertos(_menu(gestor, "/compras/")) == ["Movimentações"]
    assert _abertos(_menu(gestor, "/relatorios/fretes-e-quebra/")) == [
        "Relatórios e Análise"
    ]
    assert _abertos(_menu(gestor, "/")) == []  # Início não abre bloco nenhum


def test_item_do_menu_nao_repete_icone_dentro_do_mesmo_bloco_de_operacao():
    # Ícone repetido faz dois links parecerem o mesmo; relatórios são a exceção
    # (todos são "documento").
    nomes = {}
    for bloco, _icone, grupos in MENU[:2] + MENU[3:]:
        for _grupo, itens in grupos:
            for _rota, rotulo, icone, _so in itens:
                nomes.setdefault((bloco, icone), []).append(rotulo)
    repetidos = {k: v for k, v in nomes.items() if len(v) > 1}
    assert repetidos == {}
