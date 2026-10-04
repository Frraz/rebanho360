"""A aba Mortes: quando, de quê e onde, com o mesmo número do resto do sistema."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core import reversible
from apps.dashboards.bi import abas, mortes, rebanho, specs
from apps.dashboards.bi.escopo import Escopo
from apps.herd import services as herd
from apps.herd.models import DeathCause, MovementType
from apps.herd.mortality import taxa_de_mortalidade
from apps.livestock.models import AnimalCategory, Lot, Sex

pytestmark = pytest.mark.django_db

D = Decimal
HOJE = datetime.date(2025, 12, 1)


def escopo(user, season, **kw):
    return Escopo.criar(user, season=season, hoje=kw.pop("hoje", HOJE), **kw)


@pytest.fixture
def bezerros(sao_francisco, season, escritorio):
    """50 bezerros (faixa jovem) em outro lote da mesma fazenda."""
    categoria = AnimalCategory.objects.create(
        name="Bezerros", sex=Sex.MACHO, age_order=1, display_order=1
    )
    lote = Lot.objects.create(
        code="LT-SFR-020",
        farm=sao_francisco,
        season=season,
        entry_date=datetime.date(2025, 7, 10),
    )
    herd.registrar_movimento(
        type=MovementType.COMPRA,
        date=datetime.date(2025, 7, 10),
        quantity=50,
        usuario=escritorio,
        destination_farm=sao_francisco,
        destination_lot=lote,
        destination_category=categoria,
    )
    return lote, categoria


@pytest.fixture
def lancar(escritorio, sao_francisco):
    def _lancar(lote, categoria, dia, quantidade, *, causa="", peso=None):
        return herd.registrar_movimento(
            type=MovementType.MORTE,
            date=dia,
            quantity=quantidade,
            usuario=escritorio,
            origin_farm=sao_francisco,
            origin_lot=lote,
            origin_category=categoria,
            reason="Encontrada morta",
            death_cause=causa,
            total_weight_kg=peso,
        )

    return _lancar


@pytest.fixture
def varias_mortes(lote_gordo, categoria_25_36, bezerros, lancar):
    lote_b, cat_b = bezerros
    return {
        "adulto_jul": lancar(
            lote_gordo,
            categoria_25_36,
            datetime.date(2025, 7, 25),
            3,
            causa=DeathCause.ONCA,
            peso=D("1500"),
        ),
        "jovem_ago": lancar(
            lote_b, cat_b, datetime.date(2025, 8, 12), 2, causa=DeathCause.DOENCA
        ),
        "jovem_sem_causa": lancar(lote_b, cat_b, datetime.date(2025, 8, 20), 1),
    }


class TestAbaMortes:
    def test_esta_registrada_depois_do_rebanho_e_todos_a_veem(self):
        slugs = [a.slug for a in abas.ABAS]
        assert slugs.index("mortes") == slugs.index("rebanho") + 1
        assert abas.aba_por_slug("mortes").visivel(object.__new__(_Autenticado))

    def test_abre_para_o_gestor_e_para_o_campo(
        self, client, gestor, campo_baixao, season, varias_mortes
    ):
        url = reverse("dashboards:dashboard_aba", args=["mortes"])
        for user in (gestor, campo_baixao):
            client.force_login(user)
            assert client.get(url).status_code == 200

    def test_sem_morte_diz_que_nao_ha_o_que_mostrar(self, gestor, season):
        painel = mortes.montar(escopo(gestor, season)).finalizar()
        assert painel.kpis and painel.vazio
        assert painel.json_dos_graficos() == {}

    def test_totais_por_mes_causa_categoria_e_fazenda_fecham(
        self, gestor, season, varias_mortes
    ):
        e = escopo(gestor, season)
        assert mortes.total(e) == 6
        for agrupado in (
            mortes.por_causa(e),
            mortes.por_categoria(e),
            mortes.por_fazenda(e),
        ):
            assert sum(n for _, n in agrupado) == 6
        jovens, adultos = mortes._por_mes_e_faixa(e)
        assert sum(jovens) == 3 and sum(adultos) == 3
        # julho: 3 adultos; agosto: 3 jovens
        assert (adultos[0], jovens[1]) == (3, 3)

    def test_causa_vazia_vira_nao_informada_e_conta_como_falta_de_dado(
        self, gestor, season, varias_mortes
    ):
        e = escopo(gestor, season)
        causas = dict(mortes.por_causa(e))
        assert causas["Não informada"] == 1
        assert causas["Doença"] == 2 and causas["Ataque de onça / predador"] == 3
        assert mortes.sem_causa(e) == 1
        kpi = {k.rotulo: k for k in mortes.kpis(e)}["Mortes sem causa informada"]
        assert kpi.estado == "atencao" and kpi.estado_texto == "Falta dado"

    def test_total_e_o_mesmo_do_servico_de_mortalidade(
        self, gestor, season, sao_francisco, varias_mortes
    ):
        e = escopo(gestor, season)
        servico = taxa_de_mortalidade(farm=sao_francisco, start=e.inicio, end=e.fim)
        assert mortes.total(e) == servico.mortes == rebanho.mortalidade(e).mortes
        # o KPI de mortalidade é o do painel inicial (um número só)
        kpi = {k.rotulo: k for k in mortes.kpis(e)}["Mortalidade na safra"]
        assert kpi.valor == specs.formatar(servico.taxa, "pct")

    def test_mortalidade_do_mes_e_mortes_sobre_saldo_medio_ou_travessao(
        self, gestor, season, varias_mortes
    ):
        e = escopo(gestor, season)
        taxas = mortes.mortalidade_por_mes(e)
        assert len(taxas) == len(e.meses)
        assert all(t is None or t >= 0 for t in taxas)
        assert taxas[0] is not None and taxas[0] > 0  # julho teve morte e rebanho

    def test_taxa_por_faixa_usa_estoque_do_fim_do_mes(
        self, gestor, season, varias_mortes
    ):
        e = escopo(gestor, season)
        jovens, adultos = mortes.mortalidade_por_faixa(e)
        estoque_j, _ = mortes._estoque_por_faixa(e)
        # agosto: 3 jovens mortos ÷ 47 no fim do mês (50 − 3)
        assert estoque_j[1] == 47
        assert jovens[1] == D(3) / D(47) * 100
        # julho: jovens em estoque e nenhum morto é 0%, não falta de dado
        assert jovens[0] == 0

    def test_faixa_sem_estoque_e_none_nunca_zero_nem_erro(
        self, gestor, season, lote_gordo, categoria_25_36, lancar
    ):
        """A planilha mostrava #DIV/0! quando não havia animal jovem; aqui, "—"."""
        lancar(lote_gordo, categoria_25_36, datetime.date(2025, 8, 1), 2)
        e = escopo(gestor, season)
        jovens, adultos = mortes.mortalidade_por_faixa(e)
        assert all(t is None for t in jovens)
        assert adultos[1] == D(2) / D(98) * 100
        grafico = mortes.grafico_mortalidade_por_faixa(e)
        linhas = [linha for linha in grafico.tabela.linhas]
        assert all(linha[1] == specs.TRAVESSAO for linha in linhas)

    def test_morte_desfeita_sai_de_todos_os_totais(self, gestor, season, varias_mortes):
        reversible.excluir(
            varias_mortes["adulto_jul"], usuario=gestor, motivo="Lançada em duplicidade"
        )
        e = escopo(gestor, season)
        assert mortes.total(e) == 3
        assert "Ataque de onça / predador" not in dict(mortes.por_causa(e))
        assert sum(mortes._por_mes_e_faixa(e)[1]) == 0

    def test_peso_so_vale_quando_informado(self, gestor, season, varias_mortes):
        e = escopo(gestor, season)
        kpi = {k.rotulo: k for k in mortes.kpis(e)}["Peso das cabeças mortas"]
        assert kpi.valor == "1.500 kg"

    def test_sem_peso_nenhum_o_kpi_e_travessao(
        self, gestor, season, lote_gordo, categoria_25_36, lancar
    ):
        lancar(lote_gordo, categoria_25_36, datetime.date(2025, 8, 1), 1)
        kpi = {k.rotulo: k for k in mortes.kpis(escopo(gestor, season))}[
            "Peso das cabeças mortas"
        ]
        assert kpi.valor == "—"

    def test_so_a_fazenda_do_escopo_aparece(
        self, gestor, campo_baixao, season, varias_mortes
    ):
        """O campo do Baixão não enxerga mortes de São Francisco."""
        assert mortes.total(escopo(campo_baixao, season)) == 0
        assert mortes.total(escopo(gestor, season)) == 6

    def test_nao_ha_alerta_nem_julgamento_de_mortalidade(
        self, gestor, season, varias_mortes
    ):
        painel = mortes.montar(escopo(gestor, season)).finalizar()
        assert painel.insights == []
        notas = " ".join(g.nota for g in painel.graficos())
        assert "não julga" in notas
        assert not any(k.estado == "ruim" for k in painel.kpis)

    def test_ids_dos_graficos_sao_unicos_e_so_ha_json_do_que_tem_dado(
        self, gestor, season, varias_mortes
    ):
        painel = mortes.montar(escopo(gestor, season)).finalizar()
        ids = [g.id for g in painel.graficos()]
        assert len(ids) == len(set(ids)) == 7
        assert set(painel.json_dos_graficos()) <= set(ids)

    def test_tabela_de_lotes_leva_ao_lote(
        self, gestor, season, varias_mortes, bezerros
    ):
        lote_b, _ = bezerros
        tabela = mortes.tabela_de_lotes(escopo(gestor, season))
        codigos = [linha[0] for linha in tabela.linhas]
        assert lote_b.code in codigos
        i = codigos.index(lote_b.code)
        assert tabela.links[i] == reverse("livestock:lote_detalhe", args=[lote_b.pk])
        assert codigos == sorted(codigos)  # empate de 3 × 3: pelo código


class _Autenticado:
    is_authenticated = True
