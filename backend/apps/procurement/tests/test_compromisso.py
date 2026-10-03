"""F5-05 — compromisso e itens: validação, aprovação, snapshot da comissão,
etapa derivada, edição e exclusão."""

import datetime

import pytest

from apps.audit.models import AuditAction, AuditEvent
from apps.commercial.models import CommissionRule
from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.reversible import Status
from apps.procurement import commitments, selectors, trips
from apps.procurement.models import Commission, CommitmentItem
from apps.procurement.tests.conftest import DATA_RETIRADA, D, dados_item

pytestmark = pytest.mark.django_db


class TestCriar:
    def test_cria_em_negociacao_sem_afetar_nada(self, rascunho):
        assert rascunho.status == Status.RASCUNHO
        assert rascunho.code == "OP-000001"  # o número único da operação
        assert rascunho.items.count() == 1
        assert rascunho.approved_at is None
        assert not hasattr(rascunho, "commission") or not Commission.objects.exists()

    def test_codigo_sequencial_por_safra(self, criar_compromisso):
        a, b = criar_compromisso(), criar_compromisso()
        assert (a.code, b.code) == ("OP-000001", "OP-000002")  # sequência global

    def test_cria_auditoria_do_compromisso_e_dos_itens(self, rascunho):
        eventos = AuditEvent.objects.filter(action=AuditAction.CREATE)
        assert eventos.filter(entity_type="Commitment").count() == 1
        assert eventos.filter(entity_type="CommitmentItem").count() == 1

    def test_produtor_precisa_do_papel(self, criar_compromisso, comissionado):
        with pytest.raises(BusinessError, match="Produtor nem de Fornecedor"):
            criar_compromisso(seller=comissionado)

    def test_comprador_precisa_ser_comissionado(self, criar_compromisso, produtor):
        with pytest.raises(BusinessError, match="Comissionado"):
            criar_compromisso(commissioned=produtor)

    def test_exige_ao_menos_um_item(self, criar_compromisso):
        with pytest.raises(BusinessError, match="pelo menos um item"):
            criar_compromisso(itens=[])

    def test_data_futura_e_recusada(self, criar_compromisso):
        with pytest.raises(BusinessError, match="futura"):
            criar_compromisso(date=datetime.date.today() + datetime.timedelta(days=2))

    def test_abate_antes_da_retirada_e_recusado(self, criar_compromisso):
        with pytest.raises(BusinessError, match="abate não pode ser antes"):
            criar_compromisso(
                pickup_date=datetime.date(2025, 9, 10),
                slaughter_date=datetime.date(2025, 9, 5),
            )

    def test_sem_safra_que_cubra_a_data(self, criar_compromisso):
        with pytest.raises(BusinessError, match="safra"):
            criar_compromisso(date=datetime.date(2020, 1, 1))

    def test_campo_nao_lanca(self, campo_baixao, dados_compromisso):
        dados = dict(dados_compromisso)
        itens = dados.pop("itens")
        with pytest.raises(BusinessError, match="permissão"):
            commitments.criar_compromisso(usuario=campo_baixao, itens=itens, **dados)

    def test_sem_escrita_na_fazenda_e_recusado(
        self, escritorio, dados_compromisso, baixao
    ):
        from apps.accounts.models import UserFarmAccess

        UserFarmAccess.objects.filter(user=escritorio, farm=baixao).delete()
        dados = dict(dados_compromisso) | {"destination_farm": baixao}
        itens = dados.pop("itens")
        with pytest.raises(BusinessError, match="permissão de lançamento"):
            commitments.criar_compromisso(usuario=escritorio, itens=itens, **dados)


class TestItens:
    def test_item_por_arroba_exige_preco_de_alguma_faixa(
        self, criar_compromisso, categoria_desmamados
    ):
        item = dados_item(
            categoria_desmamados,
            price_band_1=None,
            price_band_2=None,
            price_band_3=None,
            price_band_4=None,
            price_band_5=None,
            expected_band=None,
        )
        with pytest.raises(BusinessError, match="pelo menos uma faixa"):
            criar_compromisso(itens=[item])

    def test_item_por_cabeca_exige_preco_unitario(
        self, criar_compromisso, categoria_desmamados
    ):
        with pytest.raises(BusinessError, match="preço por cabeça"):
            criar_compromisso(
                itens=[
                    dados_item(
                        categoria_desmamados,
                        price_basis="CABECA",
                        unit_price=None,
                        expected_band=None,
                    )
                ]
            )

    def test_faixa_esperada_precisa_ter_preco(
        self, criar_compromisso, categoria_desmamados
    ):
        with pytest.raises(BusinessError, match="não tem preço"):
            criar_compromisso(
                itens=[
                    dados_item(categoria_desmamados, price_band_3=None, expected_band=3)
                ]
            )

    def test_preco_zero_e_recusado(self, criar_compromisso, categoria_desmamados):
        with pytest.raises(BusinessError, match="Faixa 2"):
            criar_compromisso(
                itens=[dados_item(categoria_desmamados, price_band_2=D("0"))]
            )

    def test_dois_itens_com_categorias_diferentes(
        self, criar_compromisso, categoria_desmamados, categoria_vaca
    ):
        compromisso = criar_compromisso(
            itens=[dados_item(categoria_desmamados), dados_item(categoria_vaca)]
        )
        assert [i.number for i in compromisso.items.order_by("number")] == [1, 2]

    def test_categoria_inativa_e_recusada(
        self, criar_compromisso, categoria_desmamados
    ):
        categoria_desmamados.is_active = False
        categoria_desmamados.save()
        with pytest.raises(BusinessError, match="inativa"):
            criar_compromisso()

    def test_lote_de_outra_fazenda_e_recusado(
        self, criar_compromisso, categoria_desmamados, lote_baixao
    ):
        with pytest.raises(BusinessError, match="é da fazenda"):
            criar_compromisso(itens=[dados_item(categoria_desmamados, lot=lote_baixao)])

    def test_preco_da_faixa(self, item):
        assert item.preco_da_faixa(2) == D("237.60")
        assert item.preco_da_faixa(6) is None
        assert item.preco_da_faixa(None) is None


class TestAprovar:
    def test_aprovar_registra_quem_e_quando(self, compromisso, gestor):
        assert compromisso.status == Status.CONFIRMADA
        assert compromisso.approved_by == gestor
        assert compromisso.approved_at is not None

    def test_escritorio_lanca_mas_nao_aprova(self, rascunho, escritorio):
        # Cliente, 2026-10-03: aprovam ADMIN e GESTOR.
        with pytest.raises(BusinessError, match="administrador ou gestor"):
            commitments.aprovar_compromisso(rascunho, usuario=escritorio)

    def test_quem_lancou_pode_aprovar_o_proprio_lancamento(
        self, gestor, dados_compromisso
    ):
        """Sem segregação (cliente, 2026-10-03): a auditoria guarda quem lançou
        e quem aprovou, mesmo sendo a mesma pessoa."""
        dados = dict(dados_compromisso)
        itens = dados.pop("itens")
        c = commitments.criar_compromisso(usuario=gestor, itens=itens, **dados)
        c = commitments.aprovar_compromisso(c, usuario=gestor)
        assert c.created_by == c.approved_by == gestor
        assert c.approved_at is not None

    def test_aprovar_duas_vezes_e_recusado(self, compromisso, escritorio, gestor):
        with pytest.raises(BusinessError, match="já foi aprovado"):
            commitments.aprovar_compromisso(compromisso, usuario=gestor)

    def test_aprovar_audita_confirmacao(self, compromisso):
        assert AuditEvent.objects.filter(
            action=AuditAction.CONFIRM, entity_type="Commitment"
        ).exists()

    def test_sem_regra_nao_ha_comissao(self, compromisso):
        assert not Commission.objects.filter(commitment=compromisso).exists()


class TestSnapshotDaComissao:
    """O coração do cuidado da fase: a operação de janeiro não vira a de março."""

    def test_aprovar_copia_a_regra_vigente(
        self, rascunho, escritorio, regra_de_comissao, comissionado, gestor
    ):
        compromisso = commitments.aprovar_compromisso(rascunho, usuario=gestor)

        comissao = compromisso.commission
        assert (comissao.type, comissao.base, comissao.value) == (
            "PERCENTUAL",
            "BRUTO",
            D("1"),
        )
        assert comissao.rule == regra_de_comissao
        assert comissao.source == "REGRA"
        assert comissao.payee == comissionado

    def test_mudar_a_regra_depois_nao_muda_a_comissao_do_compromisso(
        self, rascunho, escritorio, regra_de_comissao, gestor
    ):
        compromisso = commitments.aprovar_compromisso(rascunho, usuario=gestor)

        regra_de_comissao.value = D("1.5")
        regra_de_comissao.base = "LIQUIDO"
        regra_de_comissao.save()
        CommissionRule.objects.create(
            type="POR_CABECA", value=D("99"), valid_from=datetime.date(2025, 9, 1)
        )

        compromisso.commission.refresh_from_db()
        assert compromisso.commission.value == D("1")
        assert compromisso.commission.base == "BRUTO"

    def test_apagar_a_regra_nao_apaga_a_comissao(
        self, rascunho, escritorio, regra_de_comissao, gestor
    ):
        compromisso = commitments.aprovar_compromisso(rascunho, usuario=gestor)
        regra_de_comissao.delete()

        comissao = Commission.objects.get(commitment=compromisso)
        assert comissao.rule is None and comissao.value == D("1")

    def test_aprovar_audita_a_gravacao_da_regra(
        self, rascunho, escritorio, regra_de_comissao, gestor
    ):
        commitments.aprovar_compromisso(rascunho, usuario=gestor)
        evento = AuditEvent.objects.get(entity_type="Commission")
        assert evento.action == AuditAction.CREATE
        assert "aprovação" in evento.reason

    def test_regra_do_comissionado_vence_a_geral(
        self, rascunho, escritorio, regra_de_comissao, comissionado, gestor
    ):
        propria = CommissionRule.objects.create(
            commissioned=comissionado,
            type="PERCENTUAL",
            base="LIQUIDO",
            value=D("2"),
            valid_from=datetime.date(2025, 1, 1),
        )
        compromisso = commitments.aprovar_compromisso(rascunho, usuario=gestor)
        assert compromisso.commission.rule == propria

    def test_regra_por_categoria_so_vale_se_todos_os_itens_tem_a_mesma(
        self,
        criar_compromisso,
        escritorio,
        categoria_desmamados,
        categoria_vaca,
        gestor,
    ):
        so_desmamados = CommissionRule.objects.create(
            category=categoria_desmamados,
            type="PERCENTUAL",
            value=D("3"),
            valid_from=datetime.date(2025, 1, 1),
        )
        misto = criar_compromisso(
            itens=[dados_item(categoria_desmamados), dados_item(categoria_vaca)]
        )
        misto = commitments.aprovar_compromisso(misto, usuario=gestor)
        assert not Commission.objects.filter(commitment=misto).exists()

        igual = commitments.aprovar_compromisso(criar_compromisso(), usuario=gestor)
        assert igual.commission.rule == so_desmamados

    def test_comprador_sem_valor_informado_recebe_a_regra_dele_na_aprovacao(
        self, criar_compromisso, gestor, comissionado, outro_comissionado
    ):
        CommissionRule.objects.create(
            commissioned=outro_comissionado,
            type="POR_CABECA",
            value=D("20"),
            valid_from=datetime.date(2025, 1, 1),
        )
        rascunho = criar_compromisso(
            compradores=[
                {"partner": comissionado, "type": "PERCENTUAL", "value": D("1.5")},
                {"partner": outro_comissionado, "type": "PERCENTUAL", "value": None},
            ]
        )
        compromisso = commitments.aprovar_compromisso(rascunho, usuario=gestor)
        por_comprador = {c.payee: c for c in commitments.comissoes_do(compromisso)}
        # o que foi digitado vale e não é sobrescrito; quem ficou em branco recebe a regra
        assert por_comprador[comissionado].source == "MANUAL"
        assert por_comprador[comissionado].value == D("1.5")
        assert por_comprador[outro_comissionado].source == "REGRA"
        assert por_comprador[outro_comissionado].type == "POR_CABECA"
        assert por_comprador[outro_comissionado].value == D("20")


class TestVariosCompradores:
    """Cliente, 2026-10-03: pode haver mais de um comprador, cada um com a sua
    comissão, informada individualmente."""

    def test_cada_comprador_tem_a_sua_comissao_e_o_primeiro_e_o_principal(
        self, criar_compromisso, comissionado, outro_comissionado
    ):
        c = criar_compromisso(
            compradores=[
                {"partner": comissionado, "type": "PERCENTUAL", "value": D("1")},
                {"partner": outro_comissionado, "type": "VALOR", "value": D("300")},
            ]
        )
        assert c.commissioned == comissionado
        linhas = commitments.comissoes_do(c)
        assert [(x.payee, x.type, x.value, x.position) for x in linhas] == [
            (comissionado, "PERCENTUAL", D("1"), 1),
            (outro_comissionado, "VALOR", D("300"), 2),
        ]

    def test_sem_limite_de_dois_compradores(self, criar_compromisso, escritorio):
        from apps.partners.models import PartnerRoleChoice
        from apps.procurement.tests.conftest import _parceiro

        quatro = [
            {
                "partner": _parceiro(f"Comprador {n}", PartnerRoleChoice.COMISSIONADO),
                "type": "PERCENTUAL",
                "value": D("1"),
            }
            for n in range(4)
        ]
        c = criar_compromisso(compradores=quatro)
        assert len(commitments.comissoes_do(c)) == 4

    def test_comprador_repetido_e_recusado(self, criar_compromisso, comissionado):
        dado = {"partner": comissionado, "type": "PERCENTUAL", "value": D("1")}
        with pytest.raises(BusinessError, match="mais de uma vez"):
            criar_compromisso(compradores=[dado, dado])

    def test_comprador_precisa_ser_comissionado(self, criar_compromisso, produtor):
        with pytest.raises(BusinessError, match="Comissionado"):
            criar_compromisso(
                compradores=[
                    {"partner": produtor, "type": "PERCENTUAL", "value": D("1")}
                ]
            )

    def test_editar_o_rascunho_acrescenta_e_retira_compradores(
        self, criar_compromisso, escritorio, comissionado, outro_comissionado
    ):
        c = criar_compromisso(
            compradores=[
                {"partner": comissionado, "type": "PERCENTUAL", "value": D("1")}
            ]
        )
        commitments.editar_rascunho(
            c,
            {},
            None,
            usuario=escritorio,
            compradores=[
                {"partner": outro_comissionado, "type": "VALOR", "value": D("50")},
                {"partner": comissionado, "type": "PERCENTUAL", "value": D("1")},
            ],
        )
        c.refresh_from_db()
        assert c.commissioned == outro_comissionado  # o primeiro da lista
        assert [x.payee for x in commitments.comissoes_do(c)] == [
            outro_comissionado,
            comissionado,
        ]
        commitments.editar_rascunho(
            c,
            {},
            None,
            usuario=escritorio,
            compradores=[
                {"partner": comissionado, "type": "PERCENTUAL", "value": D("1")}
            ],
        )
        assert [x.payee for x in commitments.comissoes_do(c)] == [comissionado]
        assert AuditEvent.objects.filter(action=AuditAction.DELETE).exists()

    def test_corrigir_os_compradores_do_aprovado_exige_motivo(
        self, compromisso, escritorio, outro_comissionado
    ):
        with pytest.raises(BusinessError, match="(?i)motivo"):
            commitments.editar_compromisso(
                compromisso,
                {},
                None,
                usuario=escritorio,
                motivo="",
                compradores=[
                    {"partner": outro_comissionado, "type": "VALOR", "value": D("10")}
                ],
            )

    def test_acrescentar_comprador_depois_de_aprovado_pela_comissao(
        self, compromisso, escritorio, outro_comissionado
    ):
        commitments.definir_comissao(
            compromisso,
            tipo="VALOR",
            valor=D("90"),
            favorecido=outro_comissionado,
            usuario=escritorio,
        )
        assert len(commitments.comissoes_do(compromisso)) >= 1
        assert commitments.comissoes_do(compromisso)[-1].payee == outro_comissionado

    def test_comprador_sem_valor_aguarda_a_regra_e_a_tela_diz_isso(
        self, criar_compromisso, comissionado
    ):
        c = criar_compromisso(
            compradores=[{"partner": comissionado, "type": "PERCENTUAL", "value": None}]
        )
        (linha,) = commitments.comissoes_do(c)
        assert linha.aguarda_regra
        assert "gravada na aprovação" in linha.regra_em_texto()

    def test_acrescentar_comprador_na_correcao_do_aprovado_aplica_a_regra_dele(
        self, compromisso, escritorio, gestor, outro_comissionado
    ):
        CommissionRule.objects.create(
            commissioned=outro_comissionado,
            type="POR_CABECA",
            value=D("20"),
            valid_from=datetime.date(2025, 1, 1),
        )
        commitments.editar_compromisso(
            compromisso,
            {},
            None,
            usuario=gestor,
            motivo="Novo comprador entrou",
            compradores=[
                {"partner": outro_comissionado, "type": "PERCENTUAL", "value": None}
            ],
        )
        linha = Commission.objects.get(commitment=compromisso, payee=outro_comissionado)
        assert linha.source == "REGRA" and linha.type == "POR_CABECA"
        assert linha.value == D("20")

    def test_retirar_comprador_pede_motivo_e_audita(
        self, compromisso, escritorio, comissionado, outro_comissionado
    ):
        commitments.definir_comissao(
            compromisso,
            tipo="VALOR",
            valor=D("90"),
            favorecido=outro_comissionado,
            usuario=escritorio,
        )
        linha = Commission.objects.get(commitment=compromisso, payee=outro_comissionado)
        with pytest.raises(BusinessError, match="motivo"):
            commitments.retirar_comprador(
                compromisso, linha, usuario=escritorio, motivo=""
            )
        commitments.retirar_comprador(
            compromisso, linha, usuario=escritorio, motivo="Saiu da negociação"
        )
        assert not Commission.objects.filter(pk=linha.pk).exists()
        assert AuditEvent.objects.filter(
            action=AuditAction.DELETE, reason="Saiu da negociação"
        ).exists()


class TestComissaoManual:
    def test_define_a_comissao_do_compromisso(
        self, compromisso, escritorio, comissionado
    ):
        comissao = commitments.definir_comissao(
            compromisso,
            tipo="POR_CABECA",
            base="BRUTO",
            valor=D("12.50"),
            extra=D("100"),
            favorecido=comissionado,
            usuario=escritorio,
        )
        assert comissao.source == "MANUAL" and comissao.rule is None
        assert comissao.extra_amount == D("100")

    def test_corrigir_exige_motivo(self, compromisso, escritorio, comissionado):
        commitments.definir_comissao(
            compromisso,
            tipo="PERCENTUAL",
            base="BRUTO",
            valor=D("1"),
            favorecido=comissionado,
            usuario=escritorio,
        )
        with pytest.raises(BusinessError, match="motivo"):
            commitments.definir_comissao(
                compromisso,
                tipo="PERCENTUAL",
                base="BRUTO",
                valor=D("2"),
                favorecido=comissionado,
                usuario=escritorio,
            )

    def test_favorecido_precisa_ser_comissionado(
        self, compromisso, escritorio, produtor
    ):
        with pytest.raises(BusinessError, match="Comissionado"):
            commitments.definir_comissao(
                compromisso,
                tipo="PERCENTUAL",
                base="BRUTO",
                valor=D("1"),
                favorecido=produtor,
                usuario=escritorio,
            )

    def test_percentual_acima_de_100_e_recusado(self, compromisso, escritorio):
        with pytest.raises(BusinessError, match="100"):
            commitments.definir_comissao(
                compromisso,
                tipo="PERCENTUAL",
                base="BRUTO",
                valor=D("101"),
                usuario=escritorio,
            )


class TestEtapaDerivada:
    """A etapa não é campo: sai do que existe, e recua sozinha."""

    def test_da_negociacao_ao_acerto_aprovado(
        self, rascunho, escritorio, gestor, categoria_desmamados
    ):
        assert selectors.etapa_do_compromisso(rascunho) == "EM_NEGOCIACAO"

    def test_sequencia_completa(
        self, acerto, aprovar, compromisso, viagem, recebimento
    ):
        # fixtures encadeadas: o acerto existe, mas ainda não foi aprovado
        assert selectors.etapa_do_compromisso(compromisso) == "EM_ACERTO"
        aprovar(acerto)
        assert selectors.etapa_do_compromisso(compromisso) == "ACERTO_APROVADO"

    def test_aprovado_com_programacao_e_programado(self, compromisso):
        assert selectors.etapa_do_compromisso(compromisso) == "PROGRAMADO"

    def test_aprovado_sem_programacao(self, criar_compromisso, escritorio, gestor):
        c = criar_compromisso(pickup_date=None, slaughter_date=None)
        c = commitments.aprovar_compromisso(c, usuario=gestor)
        assert selectors.etapa_do_compromisso(c) == "APROVADO"

    def test_viagem_sem_recebimento_esta_em_viagem(self, compromisso, viagem):
        assert selectors.etapa_do_compromisso(compromisso) == "EM_VIAGEM"

    def test_recebido(self, compromisso, recebimento):
        assert selectors.etapa_do_compromisso(compromisso) == "RECEBIDO"

    def test_excluir_o_recebimento_faz_a_etapa_recuar_sozinha(
        self, compromisso, recebimento, gestor
    ):
        from apps.procurement import receivings

        receivings.excluir_recebimento(
            recebimento, usuario=gestor, motivo="Lançado errado"
        )
        assert selectors.etapa_do_compromisso(compromisso) == "EM_VIAGEM"

    def test_excluir_a_viagem_recua_para_programado(self, compromisso, viagem, gestor):
        trips.excluir_viagem(viagem, usuario=gestor, motivo="Cancelada")
        assert selectors.etapa_do_compromisso(compromisso) == "PROGRAMADO"

    def test_excluido(self, compromisso, gestor):
        excluido = commitments.excluir_compromisso(
            compromisso, usuario=gestor, motivo="Duplicado"
        )
        assert selectors.etapa_do_compromisso(excluido) == "EXCLUIDO"

    def test_nenhum_campo_de_etapa_no_modelo(self):
        from apps.procurement.models import Commitment

        nomes = {f.name for f in Commitment._meta.get_fields()}
        assert not nomes & {"stage", "etapa", "phase", "step"}


class TestEditarExcluirRestaurar:
    def test_editar_rascunho_nao_pede_motivo(self, rascunho, escritorio):
        editado = commitments.editar_rascunho(
            rascunho, {"origin_city": "Alvorada-TO"}, None, usuario=escritorio
        )
        assert editado.origin_city == "Alvorada-TO" and editado.version == 2

    def test_editar_aprovado_exige_motivo(self, compromisso, escritorio):
        with pytest.raises(BusinessError, match="Motivo"):
            commitments.editar_compromisso(
                compromisso, {"distance_km": 120}, None, usuario=escritorio, motivo=""
            )

    def test_editar_aprovado_audita_antes_e_depois(self, compromisso, escritorio):
        commitments.editar_compromisso(
            compromisso,
            {"distance_km": 120},
            None,
            usuario=escritorio,
            motivo="Distância conferida",
        )
        evento = AuditEvent.objects.filter(
            entity_type="Commitment", action=AuditAction.UPDATE
        ).get()
        assert evento.reason == "Distância conferida"
        assert "distance_km" in evento.changed_fields

    def test_corrigir_o_preco_de_um_item_aprovado_audita_a_linha(
        self, compromisso, item, escritorio, categoria_desmamados
    ):
        itens = [
            {"id": item.pk} | dados_item(categoria_desmamados, price_band_4=D("280.00"))
        ]
        commitments.editar_compromisso(
            compromisso, {}, itens, usuario=escritorio, motivo="Preço renegociado"
        )
        item.refresh_from_db()
        assert item.price_band_4 == D("280.00")
        evento = AuditEvent.objects.filter(
            entity_type="CommitmentItem", action=AuditAction.UPDATE
        ).get()
        assert evento.reason == "Preço renegociado"
        assert evento.changed_fields == ["price_band_4"]

    def test_item_retirado_nao_sai_do_banco(
        self, compromisso, escritorio, categoria_desmamados, categoria_vaca, item
    ):
        itens = [
            {"id": item.pk} | dados_item(categoria_desmamados),
            dados_item(categoria_vaca),
        ]
        commitments.editar_compromisso(
            compromisso, {}, itens, usuario=escritorio, motivo="Acrescentou vacas"
        )
        segundo = compromisso.items.get(number=2)

        commitments.editar_compromisso(
            compromisso,
            {},
            [{"id": item.pk} | dados_item(categoria_desmamados)],
            usuario=escritorio,
            motivo="Tirou as vacas",
        )

        assert compromisso.items.count() == 1
        retirado = CommitmentItem.all_objects.get(pk=segundo.pk)  # continua no banco
        assert retirado.removed_at is not None
        assert AuditEvent.objects.filter(
            entity_type="CommitmentItem", action=AuditAction.DELETE
        ).exists()

    def test_item_com_viagem_nao_pode_ser_retirado(
        self, compromisso, viagem, escritorio, categoria_vaca
    ):
        with pytest.raises(BlockingDependencyError, match="já tem viagem"):
            commitments.editar_compromisso(
                compromisso,
                {},
                [dados_item(categoria_vaca)],
                usuario=escritorio,
                motivo="Trocar item",
            )

    def test_excluir_sem_dependentes(self, compromisso, gestor):
        commitments.excluir_compromisso(compromisso, usuario=gestor, motivo="Duplicado")
        compromisso.refresh_from_db()
        assert compromisso.status == Status.EXCLUIDA
        assert compromisso.delete_reason == "Duplicado"

    def test_excluir_exige_motivo(self, compromisso, gestor):
        with pytest.raises(BusinessError, match="Motivo"):
            commitments.excluir_compromisso(compromisso, usuario=gestor, motivo=" ")

    def test_escritorio_nao_exclui_aprovado(self, compromisso, escritorio):
        with pytest.raises(BusinessError, match="permissão"):
            commitments.excluir_compromisso(
                compromisso, usuario=escritorio, motivo="Quero apagar"
            )

    def test_excluir_com_viagem_pede_cascata(self, compromisso, viagem, gestor):
        with pytest.raises(DependencyError) as erro:
            commitments.excluir_compromisso(
                compromisso, usuario=gestor, motivo="Cancelado"
            )
        assert viagem in erro.value.dependents

    def test_excluir_em_cascata_leva_viagem_e_recebimento(
        self, compromisso, recebimento, viagem, gestor
    ):
        ultimo = AuditEvent.objects.order_by("-id").first().id
        commitments.excluir_compromisso(
            compromisso, usuario=gestor, motivo="Cancelado", cascata=True
        )
        viagem.refresh_from_db()
        recebimento.refresh_from_db()
        assert viagem.status == Status.EXCLUIDA
        assert recebimento.status == Status.EXCLUIDA
        eventos = AuditEvent.objects.filter(id__gt=ultimo, action=AuditAction.DELETE)
        assert {e.entity_type for e in eventos} >= {"Commitment", "Trip", "Receiving"}
        assert len({e.cascade_root for e in eventos}) == 1  # lido como UM ato
        assert eventos.first().cascade_root is not None

    def test_restaurar_aprovado_volta_aprovado(self, compromisso, gestor):
        commitments.excluir_compromisso(compromisso, usuario=gestor, motivo="Engano")
        compromisso.refresh_from_db()
        commitments.restaurar_compromisso(compromisso, usuario=gestor)
        compromisso.refresh_from_db()
        assert compromisso.status == Status.CONFIRMADA

    def test_rascunho_excluido_volta_rascunho_nao_aprovado(self, rascunho, gestor):
        commitments.excluir_compromisso(rascunho, usuario=gestor, motivo="Engano")
        rascunho.refresh_from_db()
        commitments.restaurar_compromisso(rascunho, usuario=gestor)
        rascunho.refresh_from_db()
        assert rascunho.status == Status.RASCUNHO
        assert rascunho.approved_at is None

    def test_restaurar_nao_troca_quem_aprovou(self, compromisso, gestor, escritorio):
        commitments.excluir_compromisso(compromisso, usuario=gestor, motivo="Engano")
        compromisso.refresh_from_db()
        commitments.restaurar_compromisso(compromisso, usuario=gestor)
        compromisso.refresh_from_db()
        assert compromisso.approved_by == gestor


class TestTravaDoAcertoAprovado:
    def test_acerto_aprovado_trava_a_edicao_do_compromisso(
        self, acerto_aprovado, compromisso, escritorio
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            commitments.editar_compromisso(
                compromisso, {"distance_km": 1}, None, usuario=escritorio, motivo="x"
            )

    def test_trava_aparece_na_analise_de_impacto_com_o_caminho(
        self, acerto_aprovado, compromisso
    ):
        from apps.core.impact import analisar_impacto

        impacto = analisar_impacto(compromisso)
        assert impacto.bloqueado
        bloqueio = impacto.bloqueios[0]
        assert "reabra o acerto" in str(bloqueio)
        assert bloqueio.url.endswith(f"/{acerto_aprovado.pk}/")

    def test_acerto_aprovado_trava_a_comissao(
        self, acerto_aprovado, compromisso, escritorio
    ):
        with pytest.raises(BlockingDependencyError, match="reabra o acerto"):
            commitments.definir_comissao(
                compromisso,
                tipo="PERCENTUAL",
                base="BRUTO",
                valor=D("1"),
                usuario=escritorio,
            )

    def test_nao_ha_trava_sem_acerto(self, compromisso, escritorio):
        commitments.editar_compromisso(
            compromisso, {"distance_km": 90}, None, usuario=escritorio, motivo="ok"
        )
        assert DATA_RETIRADA  # sem acerto aprovado, edita normalmente
