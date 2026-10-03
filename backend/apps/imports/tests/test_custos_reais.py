"""F2-10 — importador de CUSTOS contra a planilha real: 235 lançamentos,
R$ 1.046.907,76, e as 106 linhas sem centro que viram pendência — nunca
adivinhação silenciosa."""

from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.costs.models import CostCenter, CostClass, CostEntry
from apps.imports import services
from apps.imports.importers.custos import ImportadorDeCustos, sugerir_centro
from apps.imports.models import ImportKind, RowStatus
from apps.imports.tests.conftest import precisa_da_planilha, upload_real
from apps.partners.models import Partner
from apps.properties.models import Farm

pytestmark = [pytest.mark.django_db, precisa_da_planilha]

D = Decimal


@pytest.fixture
def previa(usuario_escritorio):
    batch = services.criar_importacao(
        kind=ImportKind.CUSTOS, arquivo=upload_real(), usuario=usuario_escritorio
    )
    return services.salvar_opcoes(
        batch,
        {
            "farm_id": Farm.objects.get(code="SFR").pk,
            "default_cost_class_id": CostClass.objects.get(name="CUSTEIO").pk,
        },
        usuario=usuario_escritorio,
    )


class TestPrevia:
    def test_128_prontos_106_sem_centro_e_1_linha_de_valor_zero(self, previa):
        """A doc contava 129 prontos; a planilha real tem uma linha de
        COMISSÃO CORRETOR com valor R$ 0,00 (linha 17), que não é lançamento."""
        resumo = services.resumo_da_previa(previa)

        assert resumo["prontas"] == 128
        assert resumo["pendentes"] == 107
        assert resumo["erros"] == 0

    def test_os_106_sem_centro_somam_411_132_64(self, previa):
        from apps.imports import readers

        pendentes = [
            r
            for r in previa.rows.filter(status=RowStatus.PENDENTE)
            if any(m["campo"] == "cost_center" for m in r.pendencias)
        ]

        total = sum(readers.decimal_da_celula(r.raw["valor"]) for r in pendentes)

        assert len(pendentes) == 106
        assert total == D("411132.64")

    def test_valor_zero_pede_decisao_e_nao_vira_lancamento_de_zero_reais(self, previa):
        zero = previa.rows.get(row_number=17)

        assert zero.status == RowStatus.PENDENTE
        assert "R$ 0,00 não é importado" in zero.pendencias[0]["texto"]

    def test_96_sem_descricao_precisam_de_revisao_manual(self, previa):
        sem_descricao = [
            r
            for r in previa.rows.all()
            if any(m["campo"] == "description" for m in r.pendencias)
        ]

        assert len(sem_descricao) == 96

    def test_classe_assumida_aparece_como_aviso_e_nao_em_silencio(self, previa):
        avisos = ImportadorDeCustos().avisos_do_lote(previa)

        assert any(
            "sem classe na planilha serão importados como CUSTEIO" in a for a in avisos
        )

    def test_sem_classe_padrao_as_linhas_sem_classe_ficam_pendentes(
        self, usuario_escritorio
    ):
        batch = services.criar_importacao(
            kind=ImportKind.CUSTOS, arquivo=upload_real(), usuario=usuario_escritorio
        )
        batch = services.salvar_opcoes(
            batch,
            {"farm_id": Farm.objects.get(code="SFR").pk},
            usuario=usuario_escritorio,
        )

        resumo = services.resumo_da_previa(batch)

        assert (
            resumo["prontas"] == 78
        )  # só os que a planilha classificou (1 tem valor zero)
        assert resumo["pendentes"] == 157
        assert resumo["erros"] == 0

    def test_30_datas_com_ano_digitado_errado_viram_pendencia_com_sugestao(
        self, previa
    ):
        """Achado na planilha real: 30 lançamentos com data 03/01/2025 (fora
        de qualquer safra) e a coluna ANO dizendo 2026."""
        fora = [
            r
            for r in previa.rows.all()
            if any(m["campo"] == "date" for m in r.pendencias)
        ]

        assert len(fora) == 30
        sugestao = next(m for m in fora[0].pendencias if m["campo"] == "date")[
            "sugestao"
        ]
        assert sugestao["valor"] == "2026-01-03"
        assert "coluna ANO" in sugestao["rotulo"]
        assert all("date" not in r.resolution for r in fora)  # nada aplicado sozinho

    def test_aceitar_o_grupo_da_data_corrige_so_depois_da_confirmacao(
        self, previa, usuario_escritorio
    ):
        grupo = next(
            g
            for g in ImportadorDeCustos().grupos_de_sugestao(previa)
            if g.campo == "date"
        )
        assert grupo.linhas == 30

        depois = services.salvar_decisoes(
            previa, {}, [grupo.chave], usuario=usuario_escritorio
        )

        corrigidas = [
            r for r in depois.rows.all() if r.resolution.get("date") == "2026-01-03"
        ]
        assert len(corrigidas) == 30

    def test_sugestao_nunca_e_aplicada_sozinha(self, previa):
        grupos = ImportadorDeCustos().grupos_de_sugestao(previa)

        assert grupos, "deveria sugerir classificação por padrão de texto"
        assert all(
            "cost_center" not in r.resolution
            for r in previa.rows.filter(status=RowStatus.PENDENTE)
        )

    def test_padroes_de_texto_da_spec(self):
        assert sugerir_centro("SALÁRIO ALDEMAR")[0] == "FUNCIONARIO"
        assert sugerir_centro("POSTO TIGRAO")[0] == "PARQUE DE MÁQUINAS"
        assert sugerir_centro("COMISSÃO CORRETOR")[0] == "COMISSÃO"
        assert sugerir_centro("ALGO QUE NINGUÉM SABE") is None
        assert sugerir_centro("") is None


class TestImportacaoCompleta:
    def _resolver_tudo(self, previa, usuario):
        """O que o usuário faz na tela: aceita os grupos sugeridos e
        classifica o resto à mão, com descrição onde faltava."""
        grupos = [g.chave for g in ImportadorDeCustos().grupos_de_sugestao(previa)]
        previa = services.salvar_decisoes(previa, {}, grupos, usuario=usuario)
        outros = CostCenter.objects.get(name="OUTROS")
        decisoes = {}
        for row in previa.rows.filter(status=RowStatus.PENDENTE):
            decisao = {}
            for m in row.pendencias:
                if m["campo"] == "cost_center":
                    decisao["cost_center"] = outros.pk
                if m["campo"] == "description":
                    decisao["description"] = "Lançamento sem descrição na planilha"
                if m["campo"] == "amount":
                    decisao["acao"] = "IGNORAR"  # R$ 0,00 não é lançamento
            decisoes[row.pk] = decisao
        return services.salvar_decisoes(previa, decisoes, [], usuario=usuario)

    def test_aceitar_grupos_resolve_so_o_que_tem_sugestao(
        self, previa, usuario_escritorio
    ):
        antes = services.resumo_da_previa(previa)["pendentes"]
        grupos = [g.chave for g in ImportadorDeCustos().grupos_de_sugestao(previa)]

        depois = services.salvar_decisoes(
            previa, {}, grupos, usuario=usuario_escritorio
        )

        resumo = services.resumo_da_previa(depois)
        assert resumo["pendentes"] < antes
        assert (
            resumo["pendentes"] > 0
        )  # o que não tem padrão continua esperando decisão humana

    def test_importa_234_lancamentos_somando_1_046_907_76(
        self, previa, usuario_escritorio
    ):
        """235 linhas reais = 234 lançamentos + 1 de R$ 0,00 ignorada. O
        total é exatamente o da planilha: a linha ignorada vale zero."""
        previa = self._resolver_tudo(previa, usuario_escritorio)
        assert services.resumo_da_previa(previa)["pendentes"] == 0

        resultado = services.importar(previa, usuario=usuario_escritorio)

        assert resultado["importadas"] == 234
        assert previa.rows.filter(status=RowStatus.IGNORADA).count() == 1
        custos = CostEntry.objects.all()
        assert custos.count() == 234
        assert custos.aggregate(t=Sum("amount"))["t"] == D("1046907.76")

    def test_os_11_centros_somam_o_mesmo_total(self, previa, usuario_escritorio):
        previa = self._resolver_tudo(previa, usuario_escritorio)
        services.importar(previa, usuario=usuario_escritorio)

        por_centro = (
            CostEntry.objects.values("cost_center__name")
            .annotate(t=Sum("amount"))
            .order_by()
        )

        assert sum(linha["t"] for linha in por_centro) == D("1046907.76")
        assert len(por_centro) <= 11

    def test_centros_que_a_planilha_ja_classificava_batem_com_o_dash_financeiro(
        self, previa, usuario_escritorio
    ):
        """Valores da aba DASH FINANCEIRO (docs/regras-negocio/05) para os
        centros que já vinham classificados na planilha."""
        previa = self._resolver_tudo(previa, usuario_escritorio)
        services.importar(previa, usuario=usuario_escritorio)
        # Só linhas que a planilha já trazia com centro (nenhuma decisão do usuário).
        ja_classificadas = [
            r.target_id for r in previa.rows.all() if "cost_center" not in r.resolution
        ]
        por_centro = {
            linha["cost_center__name"]: linha["t"]
            for linha in CostEntry.objects.filter(pk__in=ja_classificadas)
            .values("cost_center__name")
            .annotate(t=Sum("amount"))
        }

        assert por_centro["FUNCIONARIO"] == D("172593.34")
        assert por_centro["PASTAGEM"] == D("142323.00")
        assert por_centro["NUTRIÇÃO"] == D("136099.99")
        assert por_centro["PARQUE DE MÁQUINAS"] == D("109794.93")
        assert por_centro["INFRAESTRUTURA"] == D("27740.19")
        assert por_centro["DESPESA GADO"] == D("20776.50")
        assert por_centro["SANIDADE"] == D("11348.90")
        assert por_centro["IMPOSTO E TAXAS"] == D("6330.77")
        assert por_centro["OUTROS"] == D("5262.00")
        assert por_centro["COMISSÃO"] == D("2866.50")
        assert por_centro["FERPAM"] == D("639.00")

    def test_importar_so_os_prontos_deixa_o_resto_pendente_no_lote(
        self, previa, usuario_escritorio
    ):
        resultado = services.importar(previa, usuario=usuario_escritorio)

        assert resultado["importadas"] == 128
        assert resultado["pendentes_restantes"] == 107
        assert CostEntry.objects.count() == 128

    def test_pagador_onoda_vira_parceiro_unico_sem_papel(
        self, previa, usuario_escritorio
    ):
        previa = self._resolver_tudo(previa, usuario_escritorio)
        services.importar(previa, usuario=usuario_escritorio)

        onoda = Partner.objects.filter(name="ONODA")

        assert onoda.count() == 1
        assert not onoda.get().roles.exists()  # pendência #6: papel indefinido
        assert CostEntry.objects.filter(payer=onoda.get()).count() == 234

    def test_todos_os_lancamentos_vao_para_a_fazenda_escolhida(
        self, previa, usuario_escritorio
    ):
        previa = self._resolver_tudo(previa, usuario_escritorio)
        services.importar(previa, usuario=usuario_escritorio)

        assert set(CostEntry.objects.values_list("farm__code", flat=True)) == {"SFR"}

    def test_a_classe_que_a_planilha_trazia_e_respeitada(
        self, previa, usuario_escritorio
    ):
        previa = self._resolver_tudo(previa, usuario_escritorio)
        services.importar(previa, usuario=usuario_escritorio)

        investimentos = CostEntry.objects.filter(cost_class__name="INVESTIMENTO")

        assert investimentos.count() == 1  # a câmera de monitoramento
        assert investimentos.get().amount == D("24275.19")
