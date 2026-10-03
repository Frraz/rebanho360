"""F5-09 — classificação de carcaça e romaneio valorizado."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditAction, AuditEvent
from apps.commercial.models import CarcassClass
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.procurement import grading
from apps.procurement.models import GradingLine
from apps.procurement.tests.conftest import D, dados_item

pytestmark = pytest.mark.django_db


def linha(classe, **extra):
    return {
        "carcass_class": classe,
        "band": 4,
        "head_count": 10,
        "carcass_weight_kg": D("2400"),
    } | extra


class TestValorizar:
    def test_conta_da_linha(self, romaneio, item):
        v = grading.romaneio_do_item(item).linhas[0]
        assert v.arrobas == D("160")  # 2.400 ÷ 15
        assert v.media_arrobas == D("16")  # 160 ÷ 10 cabeças
        assert v.valor_bruto == D("43200.00")  # 160 @ × R$ 270,00
        assert v.valor_por_kg == D("18")  # 270 ÷ 15
        assert v.desconto == D("0.00") and v.liquido == D("43200.00")

    def test_desconto_percentual(self, item, classe, escritorio, recebimento):
        grading.registrar_romaneio(
            item, [linha(classe, discount_percent=D("2.5"))], usuario=escritorio
        )
        v = grading.romaneio_do_item(item).linhas[0]
        assert v.valor_bruto == D("43200.00")
        assert v.liquido == D("42120.00")  # 43.200 × 0,975
        assert v.desconto == D("1080.00")

    def test_arredonda_uma_vez_no_fim_meio_centavo_para_cima(
        self, item, classe, escritorio, recebimento
    ):
        # 0,015 kg ÷ 15 × 5,00 = 0,005 → 0,01 (ROUND_HALF_UP)
        grading.registrar_romaneio(
            item,
            [
                linha(
                    classe,
                    head_count=1,
                    carcass_weight_kg=D("0.015"),
                    price_per_arroba=D("5"),
                )
            ],
            usuario=escritorio,
        )
        assert grading.romaneio_do_item(item).linhas[0].liquido == D("0.01")

    def test_sem_carcaca_nao_ha_media_nem_preco_medio(self, item):
        r = grading.romaneio_do_item(item)
        assert r.linhas == [] and r.cabecas == 0
        assert r.media_arrobas is None and r.preco_medio_por_arroba is None

    def test_o_valor_nao_e_campo(self):
        nomes = {f.name for f in GradingLine._meta.get_fields()}
        assert not nomes & {"gross_value", "net_value", "value", "average_arrobas"}


class TestRomaneioDoLegado:
    """`04_Conferencia_do_Acerto`: 111 cabeças, 24.071,50 kg, R$ 498.055,49.

    O legado imprime o preço da @ arredondado (310,36) e arredonda por conta
    própria: cada linha dele difere da nossa em até R$ 0,11 (a soma, em R$ 0,12).
    Cabeças, peso e média @ conferem em todas as linhas, exatos; o valor, dentro
    dessa tolerância — não é erro nosso, é o papel dele.
    """

    TOLERANCIA = D("0.15")
    LINHAS = [
        # classe, faixa, cabeças, kg, média @ e valor líquido do legado
        ("MAGRO", 5, 1, "216.00", "14.40", "4469.18"),
        ("ESCASSA", 4, 2, "342.50", "11.42", "7086.45"),
        ("ESCASSA", 4, 4, "847.00", "14.12", "17525.10"),
        ("MEDIANA", 4, 6, "1053.50", "11.71", "21797.51"),
        ("MEDIANA", 5, 55, "12167.00", "14.75", "251743.24"),
        ("UNIFORME", 5, 39, "8698.00", "14.87", "179967.52"),
        ("LESAO", 3, 1, "161.50", "10.77", "3341.65"),
        ("LESAO", 4, 1, "179.50", "11.97", "3714.08"),
        ("LESAO", 5, 2, "406.50", "13.55", "8410.76"),
    ]

    @pytest.fixture
    def romaneio_legado(self, item, escritorio, recebimento):
        entradas = [
            {
                "carcass_class": CarcassClass.objects.get(code=codigo),
                "band": faixa,
                "head_count": cabecas,
                "carcass_weight_kg": D(kg),
                "price_per_arroba": D("310.36"),
            }
            for codigo, faixa, cabecas, kg, *_ in self.LINHAS
        ]
        grading.registrar_romaneio(item, entradas, usuario=escritorio)
        return grading.romaneio_do_item(item)

    def test_totais_de_cabecas_e_peso(self, romaneio_legado):
        assert romaneio_legado.cabecas == 111
        assert romaneio_legado.peso_kg == D("24071.50")

    def test_media_em_arrobas_de_cada_linha(self, romaneio_legado):
        for valorizada, (*_, media, _liquido) in zip(
            romaneio_legado.linhas, self.LINHAS
        ):
            assert valorizada.media_arrobas.quantize(D("0.01"), "ROUND_HALF_UP") == D(
                media
            ), valorizada.linha

    def test_valor_de_cada_linha_confere_dentro_da_tolerancia(self, romaneio_legado):
        for valorizada, (*_, liquido) in zip(romaneio_legado.linhas, self.LINHAS):
            assert (
                abs(valorizada.liquido - D(liquido)) <= self.TOLERANCIA
            ), valorizada.linha

    def test_o_liquido_total_e_a_soma_das_linhas(self, romaneio_legado):
        assert romaneio_legado.liquido == sum(
            (v.liquido for v in romaneio_legado.linhas), Decimal("0")
        )
        assert abs(romaneio_legado.liquido - D("498055.49")) <= self.TOLERANCIA


class TestRegistrar:
    def test_copia_o_preco_da_faixa_do_contrato(
        self, item, classe, escritorio, recebimento
    ):
        grading.registrar_romaneio(item, [linha(classe, band=2)], usuario=escritorio)
        assert item.gradings.get().price_per_arroba == D("237.60")

    def test_preco_informado_prevalece_sobre_o_do_contrato(
        self, item, classe, escritorio, recebimento
    ):
        grading.registrar_romaneio(
            item, [linha(classe, price_per_arroba=D("300"))], usuario=escritorio
        )
        assert item.gradings.get().price_per_arroba == D("300")

    def test_faixa_sem_preco_no_contrato_pede_o_preco(
        self, escritorio, compromisso, classe, categoria_desmamados, recebimento
    ):
        from apps.procurement import commitments

        item = compromisso.items.get()
        commitments.editar_compromisso(
            compromisso,
            {},
            [{"id": item.pk} | dados_item(categoria_desmamados, price_band_5=None)],
            usuario=escritorio,
            motivo="Sem faixa 5",
        )
        item.refresh_from_db()
        with pytest.raises(BusinessError, match="não tem preço para a Faixa 5"):
            grading.registrar_romaneio(
                item, [linha(classe, band=5)], usuario=escritorio
            )

    def test_faixa_fora_de_1_a_5(self, item, classe, escritorio):
        with pytest.raises(BusinessError, match="1 a 5"):
            grading.registrar_romaneio(
                item, [linha(classe, band=6)], usuario=escritorio
            )

    def test_peso_e_cabecas_obrigatorios(self, item, classe, escritorio):
        with pytest.raises(BusinessError, match="peso de carcaça"):
            grading.registrar_romaneio(
                item, [linha(classe, carcass_weight_kg=D("0"))], usuario=escritorio
            )
        with pytest.raises(BusinessError, match="cabeças"):
            grading.registrar_romaneio(
                item, [linha(classe, head_count=0)], usuario=escritorio
            )

    def test_desconto_de_0_a_100(self, item, classe, escritorio):
        with pytest.raises(BusinessError, match="0% a 100%"):
            grading.registrar_romaneio(
                item, [linha(classe, discount_percent=D("101"))], usuario=escritorio
            )

    def test_classe_inativa_e_recusada(self, item, classe, escritorio):
        classe.is_active = False
        classe.save()
        with pytest.raises(BusinessError, match="inativa"):
            grading.registrar_romaneio(item, [linha(classe)], usuario=escritorio)

    def test_item_por_cabeca_nao_tem_romaneio(
        self, escritorio, criar_compromisso, categoria_desmamados, classe
    ):
        from apps.procurement import commitments

        c = commitments.aprovar_compromisso(
            criar_compromisso(
                itens=[
                    dados_item(
                        categoria_desmamados,
                        price_basis="CABECA",
                        unit_price=D("3000"),
                        expected_band=None,
                    )
                ]
            ),
            usuario=escritorio,
        )
        with pytest.raises(BusinessError, match="por cabeça"):
            grading.registrar_romaneio(
                c.items.get(), [linha(classe)], usuario=escritorio
            )

    def test_so_depois_de_aprovar_o_compromisso(self, rascunho, classe, escritorio):
        with pytest.raises(BusinessError, match="depois da aprovação"):
            grading.registrar_romaneio(
                rascunho.items.get(), [linha(classe)], usuario=escritorio
            )

    def test_classificacao_vem_do_cadastro_nao_do_codigo(
        self, item, escritorio, recebimento
    ):
        nova = CarcassClass.objects.create(
            code="NOVA", name="Classe do outro frigorífico"
        )
        grading.registrar_romaneio(item, [linha(nova)], usuario=escritorio)
        assert item.gradings.get().carcass_class.name == "Classe do outro frigorífico"

    def test_sugere_a_faixa_da_classificacao_sem_impor(self, classe):
        assert grading.faixa_sugerida(classe) is None
        classe.default_band = 3
        assert grading.faixa_sugerida(classe) == 3


class TestCorrigirERetirar:
    def test_corrigir_exige_motivo(self, romaneio, item, classe, escritorio):
        existente = item.gradings.get()
        with pytest.raises(BusinessError, match="motivo"):
            grading.registrar_romaneio(
                item,
                [{"id": existente.pk} | linha(classe, carcass_weight_kg=D("2500"))],
                usuario=escritorio,
            )

    def test_corrigir_audita_a_linha(self, romaneio, item, classe, escritorio):
        existente = item.gradings.get()
        grading.registrar_romaneio(
            item,
            [{"id": existente.pk} | linha(classe, carcass_weight_kg=D("2500"))],
            usuario=escritorio,
            motivo="Romaneio corrigido pelo frigorífico",
        )
        evento = AuditEvent.objects.get(
            entity_type="GradingLine", action=AuditAction.UPDATE
        )
        assert evento.reason == "Romaneio corrigido pelo frigorífico"
        assert evento.changed_fields == ["carcass_weight_kg"]

    def test_retirar_linha_nao_apaga_do_banco(self, romaneio, item, classe, escritorio):
        existente = item.gradings.get()
        grading.registrar_romaneio(item, [], usuario=escritorio, motivo="Refazer")
        assert item.gradings.count() == 0
        assert GradingLine.all_objects.get(pk=existente.pk).removed_at is not None

    def test_acrescentar_linha_nao_pede_motivo(
        self, romaneio, item, classe, classe_escassa, escritorio
    ):
        existente = item.gradings.get()
        grading.registrar_romaneio(
            item,
            [
                {"id": existente.pk} | linha(classe),
                linha(classe_escassa, head_count=2, carcass_weight_kg=D("480")),
            ],
            usuario=escritorio,
        )
        assert item.gradings.count() == 2

    def test_acerto_aprovado_trava_o_romaneio(
        self, acerto_aprovado, item, classe, escritorio
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            grading.registrar_romaneio(
                item, [linha(classe, head_count=9)], usuario=escritorio, motivo="x"
            )
