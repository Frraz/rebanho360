"""F2-14 — `conferir_importacao`: roda em um comando e qualquer
divergência salta aos olhos. Aqui, contra a planilha real importada de
ponta a ponta."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.costs.models import CostCenter, CostClass
from apps.imports import services
from apps.imports.conferencia import conferir
from apps.imports.importers.custos import ImportadorDeCustos
from apps.imports.models import ImportKind, RowStatus
from apps.imports.tests.conftest import precisa_da_planilha, upload_real
from apps.livestock.models import AnimalCategory
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db


def rodar():
    saida = StringIO()
    try:
        call_command("conferir_importacao", stdout=saida)
        erro = None
    except CommandError as exc:
        erro = str(exc)
    return saida.getvalue(), erro


def por_nome(verificacoes):
    return {v.nome.split(" (")[0]: v for v in verificacoes}


def test_banco_vazio_diverge_em_tudo_e_o_comando_falha(demo):
    saida, erro = rodar()

    assert "✗ DIVERGE" in saida
    assert erro and "divergem da planilha" in erro


@precisa_da_planilha
class TestImportacaoCompleta:
    @pytest.fixture
    def tudo_importado(self, usuario_escritorio):
        # 1) custos, com tudo resolvido como o usuário faria
        custos = services.criar_importacao(
            kind=ImportKind.CUSTOS, arquivo=upload_real(), usuario=usuario_escritorio
        )
        custos = services.salvar_opcoes(
            custos,
            {
                "farm_id": Farm.objects.get(code="SFR").pk,
                "default_cost_class_id": CostClass.objects.get(name="CUSTEIO").pk,
            },
            usuario=usuario_escritorio,
        )
        grupos = [g.chave for g in ImportadorDeCustos().grupos_de_sugestao(custos)]
        custos = services.salvar_decisoes(
            custos, {}, grupos, usuario=usuario_escritorio
        )
        outros = CostCenter.objects.get(name="OUTROS").pk
        decisoes = {}
        for r in custos.rows.filter(status=RowStatus.PENDENTE):
            d = {}
            for m in r.pendencias:
                if m["campo"] == "cost_center":
                    d["cost_center"] = outros
                if m["campo"] == "description":
                    d["description"] = "Sem descrição na planilha"
                if m["campo"] == "amount":
                    d["acao"] = "IGNORAR"
            decisoes[r.pk] = d
        custos = services.salvar_decisoes(
            custos, decisoes, [], usuario=usuario_escritorio
        )
        services.importar(custos, usuario=usuario_escritorio)

        # 2) compras
        compras = services.criar_importacao(
            kind=ImportKind.COMPRAS, arquivo=upload_real(), usuario=usuario_escritorio
        )
        compras = services.salvar_opcoes(
            compras,
            {
                "category_map": {
                    "bezerros": AnimalCategory.objects.get(
                        name="Machos Desm. até 12m"
                    ).pk
                }
            },
            usuario=usuario_escritorio,
        )
        services.importar(compras, usuario=usuario_escritorio)

        # 3) movimentações (os 140 órfãos ficam pendentes: nunca em silêncio)
        from apps.organizations.models import Season

        movs = services.criar_importacao(
            kind=ImportKind.MOVIMENTACOES,
            arquivo=upload_real(),
            usuario=usuario_escritorio,
        )
        movs = services.salvar_opcoes(
            movs,
            {"season_id": Season.objects.get(name="2025/2026").pk},
            usuario=usuario_escritorio,
        )
        services.importar(movs, usuario=usuario_escritorio)

        # 4) vendas: adotam as saídas que a aba da fazenda já registrou
        from apps.imports.importers.vendas import ImportadorDeVendas

        vendas = services.criar_importacao(
            kind=ImportKind.VENDAS, arquivo=upload_real(), usuario=usuario_escritorio
        )
        vendas = services.salvar_opcoes(
            vendas,
            {
                "category_map": {
                    "machos 25 - 36": AnimalCategory.objects.get(
                        name="Machos 25 a 36 meses"
                    ).pk
                },
                "buyer_map": {
                    "coperfrigu": {"partner_id": None, "role": "FRIGORIFICO"}
                },
            },
            usuario=usuario_escritorio,
        )
        grupos = [g.chave for g in ImportadorDeVendas().grupos_de_sugestao(vendas)]
        vendas = services.salvar_decisoes(
            vendas, {}, grupos, usuario=usuario_escritorio
        )
        services.importar(vendas, usuario=usuario_escritorio)

        # 5) pesagens: o usuário escolhe o lote (a planilha não diz)
        from apps.imports.importers.pesagens import ImportadorDePesagens
        from apps.livestock.models import Lot

        pesagens = services.criar_importacao(
            kind=ImportKind.PESAGENS, arquivo=upload_real(), usuario=usuario_escritorio
        )
        lote = Lot.objects.filter(farm__code="SFR").order_by("id").first()
        importador = ImportadorDePesagens()
        escolhas = {
            g["chave"]: {
                "lot_id": lote.pk,
                "reason": importador.sugestao_do_grupo(g)["motivo"] or "CONFERENCIA",
            }
            for g in importador.grupos(pesagens)
        }
        pesagens = services.salvar_opcoes(
            pesagens, {"grupos": escolhas}, usuario=usuario_escritorio
        )
        services.importar(pesagens, usuario=usuario_escritorio)

    def test_o_que_bate_com_a_planilha(self, tudo_importado):
        v = por_nome(conferir())

        assert v[
            "Lançamentos de custo"
        ].ok  # 234 lançados + 1 de R$ 0,00 ignorada = 235
        assert v["Total de custos da safra"].ok
        assert v["Total de custos da safra"].sistema == Decimal("1046907.76")
        assert v["Centros de custo com lançamento"].ok
        assert v["Compras confirmadas"].ok
        assert v["Cabeças compradas"].ok
        assert v["Valor das compras"].ok
        assert v["Custos gerados pelas compras"].ok
        assert v["Cabeças abatidas"].ok  # 354, não 708: as vendas adotaram a saída
        assert v["Vendas e abates confirmados"].ok
        assert v["Cabeças vendidas"].ok
        assert v["Valor das vendas"].ok
        assert v["Valor das vendas"].sistema == Decimal("2298586.23")
        assert v["Animais pesados"].ok
        assert v["Categorias animais"].ok

    def test_as_duas_divergencias_reais_aparecem_e_sao_explicadas(self, tudo_importado):
        v = por_nome(conferir())

        saldo = v["Saldo São Francisco"]
        assert not saldo.ok
        assert (
            saldo.sistema == 2080
        )  # 126 a mais: a compra de 27/04 não está na aba da fazenda
        assert "+126" in saldo.nota

        orfas = v["Transferências não pareadas"]
        assert not orfas.ok
        assert orfas.sistema == 2  # as duas saídas de Goiano (95 + 45 = os −140)

    def test_o_comando_imprime_a_tabela_e_falha_enquanto_houver_divergencia(
        self, tudo_importado
    ):
        saida, erro = rodar()

        assert "Saldo São Francisco" in saida and "2080" in saida
        assert "✗ DIVERGE" in saida
        assert "2 de 16 verificações divergem" in erro
