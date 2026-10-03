"""F3-08 — importador de VENDAS contra a planilha real: 3 abates, 354
cabeças, R$ 2.298.586,23.

O ponto que a spec não previu: a aba `SÃO FRANCISCO` já registra os 3 abates,
e o importador de movimentações os importa como saída. Importar `VENDAS` por
cima não pode debitar as 354 cabeças de novo.
"""

from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.core.money import quantize_arroba, quantize_money
from apps.core.reversible import Status
from apps.herd import services as herd
from apps.herd.models import HerdMovement, MovementType
from apps.imports import services
from apps.imports.importers.vendas import ImportadorDeVendas
from apps.imports.models import ImportKind, RowStatus
from apps.imports.tests.conftest import precisa_da_planilha, upload_real
from apps.livestock.models import AnimalCategory
from apps.organizations.models import Season
from apps.partners.models import Partner, PartnerRoleChoice
from apps.sales import carcass
from apps.sales.models import Sale
from apps.sales.services import alertas_da_venda

pytestmark = [pytest.mark.django_db, precisa_da_planilha]

D = Decimal


@pytest.fixture
def historico(usuario_escritorio):
    """Compras e movimentações já importadas, como na carga histórica real."""
    compras = services.criar_importacao(
        kind=ImportKind.COMPRAS, arquivo=upload_real(), usuario=usuario_escritorio
    )
    compras = services.salvar_opcoes(
        compras,
        {
            "category_map": {
                "bezerros": AnimalCategory.objects.get(name="Machos Desm. até 12m").pk
            }
        },
        usuario=usuario_escritorio,
    )
    services.importar(compras, usuario=usuario_escritorio)

    movs = services.criar_importacao(
        kind=ImportKind.MOVIMENTACOES, arquivo=upload_real(), usuario=usuario_escritorio
    )
    movs = services.salvar_opcoes(
        movs,
        {"season_id": Season.objects.get(name="2025/2026").pk},
        usuario=usuario_escritorio,
    )
    services.importar(movs, usuario=usuario_escritorio)


@pytest.fixture
def previa(historico, usuario_escritorio):
    return services.criar_importacao(
        kind=ImportKind.VENDAS, arquivo=upload_real(), usuario=usuario_escritorio
    )


def opcoes_completas():
    return {
        "category_map": {
            "machos 25 - 36": AnimalCategory.objects.get(name="Machos 25 a 36 meses").pk
        },
        "buyer_map": {"coperfrigu": {"partner_id": None, "role": "FRIGORIFICO"}},
    }


@pytest.fixture
def com_opcoes(previa, usuario_escritorio):
    return services.salvar_opcoes(
        previa, opcoes_completas(), usuario=usuario_escritorio
    )


@pytest.fixture
def vinculada(com_opcoes, usuario_escritorio):
    """As opções salvas e o vínculo com as saídas aceito pelo usuário."""
    grupos = [g.chave for g in ImportadorDeVendas().grupos_de_sugestao(com_opcoes)]
    return services.salvar_decisoes(com_opcoes, {}, grupos, usuario=usuario_escritorio)


def saldo_sfr():
    from apps.properties.models import Farm

    return herd.saldo(farm=Farm.objects.get(code="SFR"))["head_count"]


class TestPrevia:
    def test_le_as_3_vendas_e_descarta_as_linhas_de_formula(self, previa):
        assert previa.read_stats["vendas"] == 3
        assert previa.rows.count() == 3
        # A aba tem dezenas de linhas só com #DIV/0! nos derivados.
        assert previa.read_stats["em_branco"] > 0

    def test_nenhum_dos_sete_derivados_vira_campo_da_venda(self, previa):
        from apps.sales.models import Sale

        nomes = {f.name for f in Sale._meta.get_fields()}
        assert "soma_rendimento" not in nomes and "rendimento" not in nomes

    def test_sem_opcoes_as_linhas_pedem_categoria_e_comprador(self, previa):
        resumo = services.resumo_da_previa(previa)

        assert resumo["prontas"] == 0 and resumo["pendentes"] == 3
        campos = {m["campo"] for r in previa.rows.all() for m in r.pendencias}
        assert {"category", "buyer"} <= campos

    def test_com_as_opcoes_cada_venda_acha_a_saida_que_a_aba_da_fazenda_ja_tem(
        self, com_opcoes
    ):
        """O coração da tarefa: 354 cabeças que já estão no razão."""
        for row in com_opcoes.rows.all():
            pendencia = next(m for m in row.pendencias if m["campo"] == "movement")
            assert pendencia["sugestao"]["valor"]
            assert "já registrou" in pendencia["texto"]
        assert services.resumo_da_previa(com_opcoes)["prontas"] == 0  # ninguém decidiu

    def test_vinculo_so_vale_depois_de_o_usuario_marcar(self, com_opcoes):
        # A sugestão existe, mas nenhuma decisão foi gravada em silêncio.
        assert all("movement" not in r.resolution for r in com_opcoes.rows.all())

    def test_aceitar_o_grupo_deixa_as_3_prontas(self, vinculada):
        resumo = services.resumo_da_previa(vinculada)
        assert (resumo["prontas"], resumo["pendentes"], resumo["erros"]) == (3, 0, 0)

    def test_o_relatorio_de_divergencia_mostra_o_soma_rendimento(self, vinculada):
        """Foi assim que a pendência #7 apareceu."""
        avisos = ImportadorDeVendas().avisos_do_lote(vinculada)

        assert len(avisos) == 1
        assert "SOMA RENDIMENTO" in avisos[0]
        assert "43,12" in avisos[0] and "pendência #7" in avisos[0]

    def test_os_derivados_da_planilha_batem_com_o_calculo_menos_o_soma_rendimento(
        self, vinculada
    ):
        # Peso médio, carcaça média, rendimento %, valor/cabeça e valor/@ das
        # 3 vendas coincidem: a única divergência é a SOMA RENDIMENTO.
        divergentes = [
            m["texto"]
            for r in vinculada.rows.all()
            for m in r.messages
            if m.get("divergencia")
        ]
        assert len(divergentes) == 1 and "SOMA RENDIMENTO" in divergentes[0]

    def test_diferenca_de_peso_e_de_data_com_o_razao_vira_aviso(self, vinculada):
        """Pendência #12: nem corrige em silêncio, nem escolhe lado."""
        textos = [m["texto"] for r in vinculada.rows.all() for m in r.avisos]
        assert any("pendência #12" in t for t in textos)
        assert any("O razão mantém a data da saída" in t for t in textos)


class TestImportacao:
    def test_importa_3_abates_354_cabecas_2_298_586_23(
        self, vinculada, usuario_escritorio
    ):
        resultado = services.importar(vinculada, usuario=usuario_escritorio)

        assert resultado["importadas"] == 3
        assert resultado["cabecas"] == 354
        assert resultado["total"] == D("2298586.23")
        agregado = Sale.objects.filter(status=Status.CONFIRMADA).aggregate(
            cb=Sum("head_count"), v=Sum("total_value")
        )
        assert agregado == {"cb": 354, "v": D("2298586.23")}

    def test_nao_debita_as_354_cabecas_de_novo(self, vinculada, usuario_escritorio):
        antes = saldo_sfr()
        saidas_antes = HerdMovement.objects.filter(type=MovementType.ABATE).count()

        resultado = services.importar(vinculada, usuario=usuario_escritorio)

        assert resultado["vinculadas"] == 3
        assert saldo_sfr() == antes  # o saldo NÃO cai 354
        assert (
            HerdMovement.objects.filter(type=MovementType.ABATE).count() == saidas_antes
        )
        assert HerdMovement.objects.filter(origin_sale__isnull=False).count() == 3

    def test_os_6_numeros_de_agosto_batem_com_a_planilha(
        self, vinculada, usuario_escritorio
    ):
        services.importar(vinculada, usuario=usuario_escritorio)

        venda = Sale.objects.get(date="2025-08-03")
        ind = carcass.indicadores_da_venda(venda)

        assert venda.head_count == 84
        assert quantize_money(ind.peso_medio_vivo) == D("518.33")
        assert quantize_money(ind.carcaca_media) == D("266.08")
        assert quantize_money(ind.rendimento) == D("51.33")
        assert quantize_arroba(ind.arrobas_carcaca) == D("1490.03")
        assert quantize_money(ind.valor_por_cabeca) == D("4779.79")
        assert quantize_money(ind.valor_por_arroba) == D("269.46")

    def test_rendimento_das_tres_bate_com_a_coluna_da_planilha(
        self, vinculada, usuario_escritorio
    ):
        services.importar(vinculada, usuario=usuario_escritorio)

        rendimentos = [
            quantize_money(carcass.indicadores_da_venda(v).rendimento)
            for v in Sale.objects.order_by("date")
        ]
        assert rendimentos == [D("51.33"), D("56.45"), D("56.79")]

    def test_o_comprador_ganha_o_papel_de_frigorifico(
        self, vinculada, usuario_escritorio
    ):
        services.importar(vinculada, usuario=usuario_escritorio)

        coperfrigu = Partner.objects.get(name="COPERFRIGU")
        assert coperfrigu.roles.filter(role=PartnerRoleChoice.FRIGORIFICO).exists()
        assert Sale.objects.filter(buyer=coperfrigu).count() == 3

    def test_o_peso_do_movimento_nao_e_corrigido_em_silencio(
        self, vinculada, usuario_escritorio
    ):
        antes = {
            m.pk: m.total_weight_kg
            for m in HerdMovement.objects.filter(type=MovementType.ABATE)
        }
        services.importar(vinculada, usuario=usuario_escritorio)

        for movimento in HerdMovement.objects.filter(origin_sale__isnull=False):
            assert movimento.total_weight_kg == antes[movimento.pk]
        assert any(
            "pendência #12" in a
            for v in Sale.objects.all()
            for a in alertas_da_venda(v)
        )

    def test_importar_o_mesmo_arquivo_duas_vezes_e_detectado(
        self, vinculada, usuario_escritorio
    ):
        services.importar(vinculada, usuario=usuario_escritorio)

        with pytest.raises(services.ImportacaoDuplicada):
            services.criar_importacao(
                kind=ImportKind.VENDAS,
                arquivo=upload_real(),
                usuario=usuario_escritorio,
            )

    def test_as_vendas_importadas_sao_editaveis_e_excluiveis(
        self, vinculada, usuario_escritorio, usuario_gestor
    ):
        from apps.sales import services as vendas

        services.importar(vinculada, usuario=usuario_escritorio)
        venda = Sale.objects.get(date="2025-08-03")
        antes = saldo_sfr()

        vendas.excluir_venda(venda, usuario=usuario_gestor, motivo="Importada errada")

        venda.refresh_from_db()
        assert venda.status == Status.EXCLUIDA
        assert saldo_sfr() == antes + 84  # as 84 cabeças voltam ao saldo

    def test_cada_linha_guarda_qual_venda_criou(self, vinculada, usuario_escritorio):
        services.importar(vinculada, usuario=usuario_escritorio)

        for row in vinculada.rows.all():
            assert row.status == RowStatus.IMPORTADA
            assert isinstance(row.target, Sale)
