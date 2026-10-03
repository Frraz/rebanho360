"""F5-10 e F5-11 — o acerto: previsto × realizado, o consolidado até o
líquido e o efeito de cada natureza de linha (derivado, nunca gravado)."""

import datetime

import pytest

from apps.audit.models import AuditAction, AuditEvent
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.reversible import Status
from apps.procurement import closing, commitments
from apps.procurement.models import FiscalNote, Settlement, SettlementLine
from apps.procurement.settlement import (
    calcular_acerto,
    sugerir_distribuicao,
)
from apps.procurement.tests.conftest import DATA_ACERTO, D, tipo

pytestmark = pytest.mark.django_db


def com_comissao(compromisso, usuario, *, tipo_="PERCENTUAL", base="BRUTO", valor="1"):
    return commitments.definir_comissao(
        compromisso,
        tipo=tipo_,
        base=base,
        valor=D(valor),
        favorecido=compromisso.commissioned,
        usuario=usuario,
    )


def linha(nome, valor, **extra):
    return {"tax_type": tipo(nome), "amount": D(valor)} | extra


class TestCriarAcerto:
    def test_cria_em_andamento(self, acerto):
        assert acerto.status == Status.RASCUNHO
        assert acerto.code == "OP-000001/AC1"  # o número único da operação

    def test_so_depois_de_aprovar_o_compromisso(self, escritorio, criar_compromisso):
        with pytest.raises(BusinessError, match="depois da aprovação"):
            closing.criar_acerto(
                usuario=escritorio, compromisso=criar_compromisso(), date=DATA_ACERTO
            )

    def test_um_acerto_por_compromisso(self, acerto, escritorio, compromisso):
        with pytest.raises(BusinessError, match="já tem o acerto"):
            closing.criar_acerto(
                usuario=escritorio, compromisso=compromisso, date=DATA_ACERTO
            )

    def test_so_um_acerto_ativo_no_banco(self, acerto, compromisso, escritorio):
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            Settlement.objects.create(
                code="AC-X",
                commitment=compromisso,
                date=DATA_ACERTO,
                created_by=escritorio,
            )

    def test_data_futura_e_recusada(self, escritorio, compromisso):
        with pytest.raises(BusinessError, match="futura"):
            closing.criar_acerto(
                usuario=escritorio,
                compromisso=compromisso,
                date=datetime.date.today() + datetime.timedelta(days=1),
            )

    def test_campo_nao_lanca_acerto(self, campo_baixao, compromisso):
        with pytest.raises(BusinessError, match="permissão"):
            closing.criar_acerto(
                usuario=campo_baixao, compromisso=compromisso, date=DATA_ACERTO
            )

    def test_editar_data_do_acerto_em_andamento(self, acerto, escritorio):
        closing.editar_acerto(
            acerto, {"date": datetime.date(2025, 9, 21)}, usuario=escritorio
        )
        acerto.refresh_from_db()
        assert acerto.date == datetime.date(2025, 9, 21) and acerto.version == 2

    def test_editar_o_aprovado_manda_reabrir(self, acerto_aprovado, escritorio):
        with pytest.raises(BusinessError, match="reabra"):
            closing.editar_acerto(acerto_aprovado, {"notes": "x"}, usuario=escritorio)


class TestNadaEGravado:
    def test_o_acerto_nao_tem_total_gravado(self):
        nomes = {f.name for f in Settlement._meta.get_fields()}
        proibidos = {
            "total",
            "net_value",
            "cost",
            "commission_value",
            "freight_value",
            "animal_value",
            "tax_value",
            "net_to_seller",
        }
        assert not nomes & proibidos

    def test_o_calculo_acompanha_a_realidade_sem_recalcular_nada(
        self, acerto, compromisso, escritorio
    ):
        antes = calcular_acerto(compromisso).valor_dos_animais
        closing.registrar_linhas(acerto, [linha("Desconto", "200")], usuario=escritorio)
        assert calcular_acerto(compromisso).valor_dos_animais == antes - 200


class TestPendencias:
    def test_sem_recebimento_nao_aprova(self, compromisso):
        calculo = calcular_acerto(compromisso)
        assert not calculo.aprovavel
        assert any("nenhum animal foi recebido" in p for p in calculo.pendencias)

    def test_item_por_arroba_sem_romaneio_diz_o_porque(self, compromisso, recebimento):
        calculo = calcular_acerto(compromisso)
        assert any("não tem romaneio" in p for p in calculo.pendencias)
        assert calculo.itens[0].valor_do_item is None  # "—", não 0

    def test_com_romaneio_nao_ha_pendencia(self, compromisso, romaneio):
        assert calcular_acerto(compromisso).pendencias == []

    def test_compromisso_nao_aprovado(self, rascunho):
        assert any(
            "ainda não foi aprovado" in p for p in calcular_acerto(rascunho).pendencias
        )

    def test_desconto_maior_que_os_animais(self, acerto, compromisso, escritorio):
        closing.registrar_linhas(
            acerto, [linha("Desconto", "50000")], usuario=escritorio
        )
        assert any(
            "descontos passam" in p for p in calcular_acerto(compromisso).pendencias
        )

    def test_adiantamento_maior_que_os_animais(self, acerto, compromisso, escritorio):
        closing.registrar_linhas(
            acerto, [linha("Adiantamento", "50000")], usuario=escritorio
        )
        assert any(
            "adiantamentos e créditos passam" in p
            for p in calcular_acerto(compromisso).pendencias
        )

    def test_nao_aprova_com_pendencia(
        self, escritorio, gestor, compromisso, recebimento
    ):
        acerto = closing.criar_acerto(
            usuario=escritorio, compromisso=compromisso, date=DATA_ACERTO
        )
        with pytest.raises(BusinessError, match="não tem romaneio"):
            closing.aprovar_acerto(acerto, usuario=gestor)
        acerto.refresh_from_db()
        assert acerto.status == Status.RASCUNHO


class TestAvisos:
    def test_frete_sem_realizado_diz_que_usou_o_previsto(self, compromisso, romaneio):
        avisos = calcular_acerto(compromisso).avisos
        assert any("frete realizado não informado" in a for a in avisos)

    def test_programado_e_nada_recebido(self, compromisso, viagem):
        avisos = calcular_acerto(compromisso).avisos
        assert any("nada foi recebido" in a for a in avisos)

    def test_romaneio_com_outro_numero_de_cabecas(
        self, compromisso, recebimento, item, classe, escritorio
    ):
        from apps.procurement import grading

        grading.registrar_romaneio(
            item,
            [
                {
                    "carcass_class": classe,
                    "band": 4,
                    "head_count": 9,
                    "carcass_weight_kg": D("2400"),
                }
            ],
            usuario=escritorio,
        )
        assert any(
            "romaneio tem 9 cabeças e foram recebidas 10" in a
            for a in calcular_acerto(compromisso).avisos
        )

    def test_categoria_diferente_da_prevista(
        self,
        escritorio,
        compromisso,
        viagem,
        categoria_13_24,
        romaneio_sem_recebimento=None,
    ):
        from apps.procurement import receivings

        receivings.criar_recebimento(
            usuario=escritorio,
            viagem=viagem,
            date=datetime.date(2025, 9, 4),
            linhas=[
                {
                    "load": viagem.loads.get(),
                    "received_qty": 10,
                    "received_category": categoria_13_24,
                }
            ],
        )
        avisos = calcular_acerto(compromisso).avisos
        assert any("categoria diferente da prevista" in a for a in avisos)

    def test_recebeu_mais_que_o_compromisso(self, escritorio, compromisso, viagem):
        from apps.procurement import receivings

        receivings.criar_recebimento(
            usuario=escritorio,
            viagem=viagem,
            date=datetime.date(2025, 9, 4),
            linhas=[{"load": viagem.loads.get(), "received_qty": 12}],
        )
        assert any("acima das 10" in a for a in calcular_acerto(compromisso).avisos)

    def test_sem_regra_de_comissao_avisa(self, compromisso, romaneio):
        assert any("Sem comissão" in a for a in calcular_acerto(compromisso).avisos)

    def test_dois_transportadores_deixam_o_frete_sem_favorecido(
        self, compromisso_duplo, escritorio, outro_transportador, item_do_duplo=None
    ):
        from apps.procurement import trips

        primeiro = compromisso_duplo.items.get(number=1)
        trips.criar_viagem(
            usuario=escritorio,
            compromisso=compromisso_duplo,
            pickup_date=datetime.date(2025, 9, 3),
            carrier=outro_transportador,
            freight_criterion="POR_VIAGEM",
            freight_rate=D("500"),
            cargas=[{"item": primeiro, "planned_qty": 1}],
        )
        calculo = calcular_acerto(compromisso_duplo)
        # um título de frete **por viagem**, a cada transportador (cliente, 2026-10-03)
        assert calculo.transportador is None
        assert len(calculo.fretes) == 2
        assert {f.favorecido for f in calculo.fretes} == {
            compromisso_duplo.trips.first().carrier,
            outro_transportador,
        }


class TestPrevistoXRealizado:
    def test_comparacoes(self, compromisso, romaneio, recebimento, viagem, escritorio):
        calculo = calcular_acerto(compromisso)
        por_rotulo = {c.rotulo: c for c in calculo.comparacoes}

        assert (por_rotulo["Cabeças"].previsto, por_rotulo["Cabeças"].realizado) == (
            10,
            10,
        )
        peso = por_rotulo["Peso (kg)"]
        assert (peso.previsto, peso.realizado) == (D("4800"), D("4900"))
        valor = por_rotulo["Valor dos animais"]
        # previsto: 10 cb × 17 @ × R$ 270 (faixa 4 esperada); realizado: romaneio
        assert (valor.previsto, valor.realizado) == (D("45900.00"), D("43200.00"))
        frete = por_rotulo["Frete"]
        assert (frete.previsto, frete.realizado) == (D("500.00"), None)
        assert por_rotulo["Categoria"].realizado == "Conforme o previsto"
        retirada = por_rotulo["Data da retirada"]
        assert retirada.previsto == retirada.realizado == datetime.date(2025, 9, 3)

    def test_sem_dado_o_comparativo_fica_none_nao_zero(self, compromisso):
        por_rotulo = {c.rotulo: c for c in calcular_acerto(compromisso).comparacoes}
        assert por_rotulo["Cabeças"].realizado is None
        assert por_rotulo["Valor dos animais"].realizado is None
        assert por_rotulo["Frete"].previsto is None

    def test_item_por_arroba_sem_media_prevista_nao_inventa_valor_previsto(
        self, gestor, criar_compromisso, categoria_desmamados
    ):
        c = commitments.aprovar_compromisso(
            criar_compromisso(
                itens=[
                    __import__(
                        "apps.procurement.tests.conftest", fromlist=["dados_item"]
                    ).dados_item(categoria_desmamados, expected_arrobas=None)
                ]
            ),
            usuario=gestor,
        )
        assert calcular_acerto(c).itens[0].valor_previsto is None


class TestConsolidado:
    def test_do_bruto_ao_liquido(self, acerto, compromisso, escritorio):
        com_comissao(compromisso, escritorio, valor="2")  # 2% de R$ 43.200 = 864
        closing.registrar_linhas(
            acerto,
            [
                linha("Funrural", "300"),
                linha("GTA", "50"),
                linha("Desconto", "200"),
                linha("Adiantamento", "5000"),
                linha("Crédito GR-3", "100"),
            ],
            usuario=escritorio,
        )
        c = calcular_acerto(compromisso)

        assert c.valor_dos_itens == D("43200.00")
        assert c.descontos == D("200")
        assert c.valor_dos_animais == D("43000.00")
        assert c.frete == D("500.00")
        assert c.tributos == D("350")
        assert c.comissao_calculada == D("860.00")  # 2% de 43.000
        # custo de aquisição: animais + frete + tributos + comissão
        assert c.custo_aquisicao == D("43000") + 500 + 350 + D("860")
        # líquido ao produtor: animais − adiantamento − crédito (custo não muda)
        assert c.adiantamentos == D("5000") and c.creditos == D("100")
        assert c.liquido_ao_produtor == D("37900.00")

    def test_tributo_e_taxa_somam_ao_custo(self, acerto, compromisso, escritorio):
        antes = calcular_acerto(compromisso).custo_aquisicao
        closing.registrar_linhas(
            acerto,
            [linha("Funrural", "100"), linha("Fundepec", "25")],
            usuario=escritorio,
        )
        c = calcular_acerto(compromisso)
        assert c.custo_aquisicao == antes + 125
        assert c.liquido_ao_produtor == c.valor_dos_animais  # não reduz o pagamento

    def test_desconto_reduz_os_animais_e_portanto_o_custo(
        self, acerto, compromisso, escritorio
    ):
        antes = calcular_acerto(compromisso)
        closing.registrar_linhas(
            acerto, [linha("Desconto", "1000")], usuario=escritorio
        )
        c = calcular_acerto(compromisso)
        assert c.valor_dos_animais == antes.valor_dos_animais - 1000
        assert c.custo_aquisicao == antes.custo_aquisicao - 1000

    def test_adiantamento_e_credito_nao_mudam_o_custo(
        self, acerto, compromisso, escritorio
    ):
        antes = calcular_acerto(compromisso)
        closing.registrar_linhas(
            acerto,
            [linha("Adiantamento", "3000"), linha("Incentivo Precoce", "400")],
            usuario=escritorio,
        )
        c = calcular_acerto(compromisso)
        assert c.custo_aquisicao == antes.custo_aquisicao
        assert c.liquido_ao_produtor == antes.liquido_ao_produtor - 3400


class TestComissaoNoAcerto:
    def test_percentual_sobre_o_bruto(self, acerto, compromisso, escritorio):
        com_comissao(compromisso, escritorio, valor="1.5")  # 43.200 × 1,5%
        assert calcular_acerto(compromisso).comissao_calculada == D("648.00")

    def test_percentual_sobre_o_liquido_tira_frete_e_tributos(
        self, acerto, compromisso, escritorio
    ):
        com_comissao(compromisso, escritorio, base="LIQUIDO", valor="1.5")
        closing.registrar_linhas(acerto, [linha("Funrural", "700")], usuario=escritorio)
        # base: 43.200 − 500 (frete) − 700 (tributo) = 42.000 → 1,5% = 630
        assert calcular_acerto(compromisso).comissao_calculada == D("630.00")

    def test_por_cabeca(self, acerto, compromisso, escritorio):
        com_comissao(compromisso, escritorio, tipo_="POR_CABECA", valor="12.50")
        assert calcular_acerto(compromisso).comissao_calculada == D("125.00")

    def test_comissao_extra_soma(self, acerto, compromisso, escritorio):
        commitments.definir_comissao(
            compromisso,
            tipo="PERCENTUAL",
            base="BRUTO",
            valor=D("1"),
            extra=D("150"),
            favorecido=compromisso.commissioned,
            usuario=escritorio,
        )
        c = calcular_acerto(compromisso)
        assert c.comissao_calculada == D("432.00")
        assert c.comissao_total == D("582.00")


class TestSugestaoDeDistribuicao:
    """O sistema **não rateia sozinho** (cliente, 2026-10-03). O que sobrou do
    antigo rateio é só a sugestão que pré-preenche a tela: por cabeça e por
    valor, sem centavo perdido."""

    def _itens(self, cabecas, valores):
        class Falso:
            def __init__(self, pk, cb, valor):
                self.item = type("I", (), {"pk": pk})()
                self.cabecas_recebidas = cb
                self.valor_do_item = valor

        return [Falso(i, cb, v) for i, (cb, v) in enumerate(zip(cabecas, valores), 1)]

    def test_soma_dos_pedacos_e_exatamente_o_total_sem_centavo_perdido(self):
        itens = self._itens([1, 1, 1], [D("100"), D("100"), D("100")])
        r = sugerir_distribuicao(
            itens,
            frete=D("100.00"),
            comissao=D("0.01"),
            tributos=D("10.00"),
            descontos=D("0"),
            abatimentos=D("0"),
        )
        assert sum(x["freight_value"] for x in r.values()) == D("100.00")
        assert sum(x["commission_value"] for x in r.values()) == D("0.01")
        assert sorted(x["freight_value"] for x in r.values()) == [
            D("33.33"),
            D("33.33"),
            D("33.34"),
        ]

    def test_frete_vai_por_cabeca_e_desconto_por_valor(self):
        itens = self._itens([10, 30], [D("10000"), D("90000")])
        r = sugerir_distribuicao(
            itens,
            frete=D("400"),
            comissao=D("0"),
            tributos=D("0"),
            descontos=D("1000"),
            abatimentos=D("0"),
        )
        assert (r[1]["freight_value"], r[2]["freight_value"]) == (
            D("100.00"),
            D("300.00"),
        )
        assert (r[1]["discount_value"], r[2]["discount_value"]) == (
            D("100.00"),
            D("900.00"),
        )

    def test_abatimento_vai_pelo_valor_ja_descontado(self):
        itens = self._itens([1, 1], [D("1000"), D("3000")])
        r = sugerir_distribuicao(
            itens,
            frete=D("0"),
            comissao=D("0"),
            tributos=D("0"),
            descontos=D("0"),
            abatimentos=D("400"),
        )
        assert (r[1]["abatement_value"], r[2]["abatement_value"]) == (
            D("100.00"),
            D("300.00"),
        )

    def test_sem_itens_nao_ha_sugestao(self):
        assert (
            sugerir_distribuicao(
                [],
                frete=D("1"),
                comissao=D("0"),
                tributos=D("0"),
                descontos=D("0"),
                abatimentos=D("0"),
            )
            == {}
        )


class TestDistribuicaoInformadaPeloUsuario:
    """Com mais de um item, o frete, a comissão, os tributos, os descontos e os
    adiantamentos são **informados** por item, e a soma tem de fechar."""

    def _distribuir(self, acerto, calculo, usuario, **por_item):
        primeiro, segundo = calculo.itens
        closing.registrar_distribuicao(
            acerto,
            [
                {"item": primeiro.item.pk, **por_item.get("primeiro", {})},
                {"item": segundo.item.pk, **por_item.get("segundo", {})},
            ],
            usuario=usuario,
        )

    def test_sem_distribuir_o_acerto_aponta_o_que_falta(self, compromisso_duplo):
        # compromisso_duplo: frete de R$ 1.000,00 e dois itens recebidos
        acerto = closing.criar_acerto(
            usuario=compromisso_duplo.created_by,
            compromisso=compromisso_duplo,
            date=DATA_ACERTO,
        )
        c = calcular_acerto(compromisso_duplo)
        assert any(
            "Frete (R$ 1.000,00)" in p and "faltam R$ 1.000,00" in p
            for p in c.pendencias
        )
        assert not c.aprovavel
        assert c.distribuicao_pendente["freight_value"] == D("1000.00")
        assert acerto.allocations.count() == 0

    def test_soma_que_nao_fecha_e_recusada_na_aprovacao(
        self, compromisso_duplo, gestor
    ):
        acerto = closing.criar_acerto(
            usuario=gestor, compromisso=compromisso_duplo, date=DATA_ACERTO
        )
        c = calcular_acerto(compromisso_duplo)
        self._distribuir(
            acerto,
            c,
            gestor,
            primeiro={"freight_value": D("300")},
            segundo={"freight_value": D("600")},
        )
        c = calcular_acerto(compromisso_duplo)
        assert c.distribuicao_pendente["freight_value"] == D("100.00")
        with pytest.raises(BusinessError, match=r"faltam R\$ 100,00"):
            closing.aprovar_acerto(acerto, usuario=gestor)

    def test_passar_do_total_tambem_e_recusado(self, compromisso_duplo, gestor):
        acerto = closing.criar_acerto(
            usuario=gestor, compromisso=compromisso_duplo, date=DATA_ACERTO
        )
        c = calcular_acerto(compromisso_duplo)
        self._distribuir(
            acerto,
            c,
            gestor,
            primeiro={"freight_value": D("700")},
            segundo={"freight_value": D("500")},
        )
        c = calcular_acerto(compromisso_duplo)
        assert any("passa do total" in p for p in c.pendencias)

    def test_distribuicao_que_fecha_vira_o_rateio_das_compras(
        self, compromisso_duplo, gestor
    ):
        acerto = closing.criar_acerto(
            usuario=gestor, compromisso=compromisso_duplo, date=DATA_ACERTO
        )
        c = calcular_acerto(compromisso_duplo)
        # o usuário escolhe uma divisão que **não** é por cabeça (344,83/655,17)
        self._distribuir(
            acerto,
            c,
            gestor,
            primeiro={"freight_value": D("250")},
            segundo={"freight_value": D("750")},
        )
        c = calcular_acerto(compromisso_duplo)
        primeiro, segundo = c.itens
        r1, r2 = c.rateios[primeiro.item.pk], c.rateios[segundo.item.pk]
        assert (r1.freight_value, r2.freight_value) == (D("250"), D("750"))
        assert r1.animal_value == D("43200.00") and r2.animal_value == D("57000.00")
        assert not c.pendencias

    def test_um_item_so_fica_com_tudo_sem_precisar_distribuir(
        self, acerto, compromisso
    ):
        c = calcular_acerto(compromisso)
        (rateio,) = c.rateios.values()
        assert rateio.freight_value == c.frete == D("500.00")
        assert not c.distribuicao_pendente

    def test_a_sugestao_pre_preenche_mas_nao_vale_sozinha(
        self, client, compromisso_duplo, gestor
    ):
        from django.urls import reverse

        acerto = closing.criar_acerto(
            usuario=gestor, compromisso=compromisso_duplo, date=DATA_ACERTO
        )
        client.force_login(gestor)
        html = client.get(
            reverse("procurement:acerto_distribuicao", args=[acerto.pk])
        ).content.decode()
        assert "sugestão" in html and "344.83" in html
        # nada foi gravado só por abrir a tela
        assert acerto.allocations.count() == 0
        assert calcular_acerto(compromisso_duplo).distribuicao_pendente


class TestLinhasEDocumentos:
    def test_linha_audita(self, acerto, escritorio):
        closing.registrar_linhas(acerto, [linha("Funrural", "300")], usuario=escritorio)
        assert AuditEvent.objects.filter(
            entity_type="SettlementLine", action=AuditAction.CREATE
        ).exists()

    def test_valor_zero_e_recusado(self, acerto, escritorio):
        with pytest.raises(BusinessError, match="maior que zero"):
            closing.registrar_linhas(acerto, [linha("GTA", "0")], usuario=escritorio)

    def test_tipo_inativo_e_recusado(self, acerto, escritorio):
        t = tipo("GTA")
        t.is_active = False
        t.save()
        with pytest.raises(BusinessError, match="inativo"):
            closing.registrar_linhas(acerto, [linha("GTA", "10")], usuario=escritorio)

    def test_corrigir_linha_exige_motivo_e_audita(self, acerto, escritorio):
        closing.registrar_linhas(acerto, [linha("Funrural", "300")], usuario=escritorio)
        existente = acerto.lines.get()
        with pytest.raises(BusinessError, match="motivo"):
            closing.registrar_linhas(
                acerto,
                [{"id": existente.pk} | linha("Funrural", "350")],
                usuario=escritorio,
            )
        closing.registrar_linhas(
            acerto,
            [{"id": existente.pk} | linha("Funrural", "350")],
            usuario=escritorio,
            motivo="Valor da guia",
        )
        evento = AuditEvent.objects.get(
            entity_type="SettlementLine", action=AuditAction.UPDATE
        )
        assert evento.changed_fields == ["amount"] and evento.reason == "Valor da guia"

    def test_retirar_linha_nao_apaga_do_banco(self, acerto, escritorio):
        closing.registrar_linhas(acerto, [linha("GTA", "40")], usuario=escritorio)
        existente = acerto.lines.get()
        closing.registrar_linhas(
            acerto, [], usuario=escritorio, motivo="Lançada errada"
        )
        assert acerto.lines.count() == 0
        assert SettlementLine.all_objects.get(pk=existente.pk).removed_at is not None

    def test_acerto_aprovado_trava_as_linhas(self, acerto_aprovado, escritorio):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            closing.registrar_linhas(
                acerto_aprovado, [linha("GTA", "40")], usuario=escritorio
            )

    def test_nota_fiscal_e_registrada(self, acerto, escritorio):
        closing.registrar_notas(
            acerto,
            [
                {
                    "number": "752",
                    "series": "1",
                    "issue_date": datetime.date(2025, 9, 20),
                    "amount": D("244200"),
                }
            ],
            usuario=escritorio,
        )
        assert acerto.fiscal_notes.get().number == "752"

    def test_nota_exige_numero_e_data(self, acerto, escritorio):
        with pytest.raises(BusinessError, match="número"):
            closing.registrar_notas(
                acerto,
                [{"number": " ", "issue_date": DATA_ACERTO, "amount": D("1")}],
                usuario=escritorio,
            )
        with pytest.raises(BusinessError, match="data de emissão"):
            closing.registrar_notas(
                acerto,
                [{"number": "1", "issue_date": None, "amount": D("1")}],
                usuario=escritorio,
            )

    def test_nota_vale_tambem_com_o_acerto_aprovado(self, acerto_aprovado, escritorio):
        closing.registrar_notas(
            acerto_aprovado,
            [
                {
                    "number": "9",
                    "series": "",
                    "issue_date": DATA_ACERTO,
                    "amount": D("0"),
                }
            ],
            usuario=escritorio,
        )
        assert FiscalNote.objects.filter(number="9").exists()
