"""F3-07 — importador de PESAGENS E CONFERENCIA contra a planilha real: o
desempilhamento dos blocos paralelos, sem perder um brinco e sem criar
entidade `Animal` (ADR 0004)."""

import datetime
from collections import Counter
from decimal import Decimal

import pytest
from django.apps import apps
from django.db.models import Sum

from apps.herd.models import Weighing, WeighingAnimal, WeighingReason
from apps.imports import services
from apps.imports.importers.pesagens import ImportadorDePesagens
from apps.imports.models import ImportKind, RowStatus
from apps.imports.tests.conftest import precisa_da_planilha, upload_real
from apps.livestock.models import Lot

pytestmark = [pytest.mark.django_db, precisa_da_planilha]

D = Decimal

#: Os 9 grupos (data, motivo) da planilha real → animais.
GRUPOS_REAIS = {
    (datetime.date(2025, 8, 3), "ABATE"): 84,
    (datetime.date(2025, 9, 12), "COMPRA GOIANO"): 133,
    (datetime.date(2025, 10, 23), "COMPRA"): 42,
    (datetime.date(2025, 11, 28), "COMPRA"): 190,
    (datetime.date(2025, 12, 15), "VACINA COFERENCIA"): 211,
    (datetime.date(2025, 12, 16), "VACINA COFERENCIA"): 1562,
    (datetime.date(2026, 4, 23), "ABATE"): 81,
    (datetime.date(2026, 4, 27), ""): 268,
    (datetime.date(2026, 5, 26), "CONFERENCIA"): 1487,
}


@pytest.fixture
def previa(demo, usuario_escritorio):
    return services.criar_importacao(
        kind=ImportKind.PESAGENS, arquivo=upload_real(), usuario=usuario_escritorio
    )


@pytest.fixture
def lote(demo):
    """A planilha não diz de qual lote é cada pesagem: o usuário escolhe."""
    from apps.organizations.models import Season
    from apps.properties.models import Farm

    return Lot.objects.create(
        code="LT-SFR-900",
        farm=Farm.objects.get(code="SFR"),
        season=Season.objects.get(name="2025/2026"),
        entry_date=datetime.date(2025, 7, 1),
    )


def escolher_lote_e_motivo(previa, usuario, lote):
    importador = ImportadorDePesagens()
    grupos = {}
    for g in importador.grupos(previa):
        sugestao = importador.sugestao_do_grupo(g)
        grupos[g["chave"]] = {
            "lot_id": lote.pk,
            "reason": sugestao["motivo"] or WeighingReason.CONFERENCIA,
        }
    return services.salvar_opcoes(previa, {"grupos": grupos}, usuario=usuario)


class TestDesempilhamento:
    def test_os_blocos_viram_uma_tabela_so(self, previa):
        # A doc dizia 8 blocos. A planilha real tem 9.
        assert previa.read_stats["blocos"] == 9
        assert previa.read_stats["lidas"] == 4058
        assert previa.rows.count() == 4058

    def test_agrupa_por_data_e_motivo(self, previa):
        grupos = ImportadorDePesagens().grupos(previa)

        assert {
            (g["date"], g["motivo_texto"]): g["animais"] for g in grupos
        } == GRUPOS_REAIS
        assert sum(g["animais"] for g in grupos) == 4058

    def test_sb_e_sem_brinco_nao_e_brinco_repetido(self, previa):
        # 133 + 190 + 268 sem coluna de brinco, mais os 'SB' (16 + 2).
        brincos = [
            ImportadorDePesagens._brinco(r.raw["brinco"]) for r in previa.rows.all()
        ]
        assert brincos.count("") == 133 + 190 + 268 + 16 + 2
        assert "SB" not in brincos

    def test_o_peso_e_a_data_chegam_corretos_a_linha_crua(self, previa):
        r = previa.rows.filter(sheet__endswith="bloco G").order_by("row_number").first()
        assert r.raw["peso"] == 528 and r.raw["movimentacao"] == "ABATE"


class TestOpcoes:
    def test_sem_escolher_o_lote_nao_importa(self, previa):
        problemas = ImportadorDePesagens().problemas_de_configuracao(previa)

        assert len(problemas) == 9
        assert all("Escolha o lote e o motivo" in p for p in problemas)

    def test_sugere_o_motivo_pelo_texto_da_planilha(self, previa):
        importador = ImportadorDePesagens()
        por_texto = {
            g["motivo_texto"]: importador.sugestao_do_grupo(g)["motivo"]
            for g in importador.grupos(previa)
        }
        assert por_texto["VACINA COFERENCIA"] == WeighingReason.VACINA  # sic
        assert por_texto["COMPRA GOIANO"] == WeighingReason.COMPRA
        assert por_texto["ABATE"] == WeighingReason.ABATE
        assert por_texto["CONFERENCIA"] == WeighingReason.CONFERENCIA

    def test_sugestao_nao_vale_sem_o_usuario_salvar(self, previa):
        assert previa.options.get("grupos") is None
        assert len(ImportadorDePesagens().problemas_de_configuracao(previa)) == 9


class TestImportacao:
    def test_nenhum_brinco_se_perdeu(self, previa, usuario_escritorio, lote):
        previa = escolher_lote_e_motivo(previa, usuario_escritorio, lote)

        resultado = services.importar(previa, usuario=usuario_escritorio)

        assert resultado["pesagens"] == 9
        assert resultado["animais"] == 4058
        assert WeighingAnimal.objects.count() == 4058
        assert previa.rows.filter(status=RowStatus.IMPORTADA).count() == 4058

    def test_nenhuma_entidade_animal_foi_criada(self):
        """ADR 0004: lote agregado antes de brinco."""
        modelos = {m.__name__ for m in apps.get_models()}
        assert "Animal" not in modelos

    def test_uma_pesagem_por_grupo_com_a_soma_dos_pesos(
        self, previa, usuario_escritorio, lote
    ):
        previa = escolher_lote_e_motivo(previa, usuario_escritorio, lote)
        services.importar(previa, usuario=usuario_escritorio)

        assert Weighing.objects.count() == 9
        agosto = Weighing.objects.get(date=datetime.date(2025, 8, 3))
        # Os 84 animais abatidos em agosto somam os 43.540 kg da venda.
        assert agosto.head_count == 84
        assert agosto.total_weight_kg == D("43540")
        assert agosto.reason == WeighingReason.ABATE
        # O peso médio é calculado, nunca digitado.
        assert round(agosto.average_weight_kg, 2) == D("518.33")

    def test_a_soma_do_importado_fecha_com_a_planilha(
        self, previa, usuario_escritorio, lote
    ):
        previa = escolher_lote_e_motivo(previa, usuario_escritorio, lote)
        services.importar(previa, usuario=usuario_escritorio)

        por_pesagem = {p.date: p.total_weight_kg for p in Weighing.objects.all()}
        assert por_pesagem[datetime.date(2025, 9, 12)] == D(
            "27668"
        )  # a compra do Goiano
        assert por_pesagem[datetime.date(2026, 4, 23)] == D("47878")
        assert WeighingAnimal.objects.aggregate(t=Sum("weight_kg"))["t"] == sum(
            por_pesagem.values()
        )

    def test_brincos_repetidos_sao_importados_todos(
        self, previa, usuario_escritorio, lote
    ):
        previa = escolher_lote_e_motivo(previa, usuario_escritorio, lote)
        services.importar(previa, usuario=usuario_escritorio)

        dezembro = WeighingAnimal.objects.filter(
            weighing__date=datetime.date(2025, 12, 16)
        )
        assert dezembro.count() == 1562
        assert Counter(dezembro.values_list("ear_tag", flat=True))["1759"] == 3

    def test_os_avisos_dizem_o_que_a_planilha_tem(self, previa):
        avisos = ImportadorDePesagens().avisos_do_lote(previa)

        assert any("sem brinco" in a and "SB" in a for a in avisos)
        assert any(
            "16/12/2025" in a and "brinco(s) repetido(s)" in a and "1759" in a
            for a in avisos
        )

    def test_importar_o_mesmo_arquivo_duas_vezes_e_detectado(
        self, previa, usuario_escritorio, lote
    ):
        previa = escolher_lote_e_motivo(previa, usuario_escritorio, lote)
        services.importar(previa, usuario=usuario_escritorio)
        with pytest.raises(services.ImportacaoDuplicada):
            services.criar_importacao(
                kind=ImportKind.PESAGENS,
                arquivo=upload_real(),
                usuario=usuario_escritorio,
            )

    def test_pesagem_importada_e_editavel_e_excluivel(
        self, previa, usuario_escritorio, usuario_gestor, lote
    ):
        from apps.core import reversible

        previa = escolher_lote_e_motivo(previa, usuario_escritorio, lote)
        services.importar(previa, usuario=usuario_escritorio)
        pesagem = Weighing.objects.get(date=datetime.date(2025, 8, 3))

        reversible.excluir(pesagem, usuario=usuario_gestor, motivo="Lote errado")

        pesagem.refresh_from_db()
        assert pesagem.status == "EXCLUIDA"
