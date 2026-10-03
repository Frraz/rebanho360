"""As telas do ciclo: papel (403), escopo (404), CSRF e o fluxo completo
pelo cliente — do compromisso ao acerto aprovado e reaberto."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import Role, User, UserFarmAccess
from apps.audit.models import AuditEvent
from apps.core.reversible import Status
from apps.procurement import closing
from apps.procurement.models import Commitment, Receiving, Settlement, Trip
from apps.procurement.tests.conftest import (
    DATA_RECEBIMENTO,
    D,
    tipo,
)
from apps.purchases.models import Purchase

pytestmark = pytest.mark.django_db


def formset(prefixo, linhas, *, iniciais=0):
    dados = {
        f"{prefixo}-TOTAL_FORMS": str(len(linhas)),
        f"{prefixo}-INITIAL_FORMS": str(iniciais),
        f"{prefixo}-MIN_NUM_FORMS": "0",
        f"{prefixo}-MAX_NUM_FORMS": "1000",
    }
    for i, linha in enumerate(linhas):
        for campo, valor in linha.items():
            dados[f"{prefixo}-{i}-{campo}"] = "" if valor is None else str(valor)
    return dados


class TestPapelEEscopo:
    URLS_DE_LEITURA = (
        "procurement:compromisso_lista",
        "procurement:acerto_lista",
    )

    def test_anonimo_vai_para_o_login(self, client):
        resposta = client.get(reverse("procurement:compromisso_lista"))
        assert resposta.status_code == 302 and "/entrar/" in resposta["Location"]

    @pytest.mark.parametrize("nome", URLS_DE_LEITURA)
    def test_campo_nao_ve_o_ciclo(self, client, campo_baixao, nome):
        client.force_login(campo_baixao)
        assert client.get(reverse(nome)).status_code == 403

    def test_campo_nao_ve_o_detalhe_nem_lanca(self, client, campo_baixao, compromisso):
        client.force_login(campo_baixao)
        assert (
            client.get(
                reverse("procurement:compromisso_detalhe", args=[compromisso.pk])
            ).status_code
            == 403
        )
        assert client.get(reverse("procurement:compromisso_novo")).status_code == 403

    @pytest.mark.parametrize("papel", ["escritorio", "gestor", "admin"])
    def test_papeis_que_veem_as_listas(self, client, request, papel, compromisso):
        client.force_login(request.getfixturevalue(papel))
        resposta = client.get(reverse("procurement:compromisso_lista"))
        assert resposta.status_code == 200
        assert compromisso.code in resposta.content.decode()

    def test_consulta_ve_mas_nao_lanca(self, client, sao_francisco, compromisso):
        user = User.objects.create_user(username="c", password="x", role=Role.CONSULTA)
        UserFarmAccess.objects.create(user=user, farm=sao_francisco)
        client.force_login(user)
        assert (
            client.get(
                reverse("procurement:compromisso_detalhe", args=[compromisso.pk])
            ).status_code
            == 200
        )
        assert client.get(reverse("procurement:compromisso_novo")).status_code == 403

    def test_fora_do_escopo_devolve_404_nao_403(
        self, client, baixao, compromisso, viagem, recebimento
    ):
        de_outra_fazenda = User.objects.create_user(
            username="outro", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(
            user=de_outra_fazenda, farm=baixao, can_write=True
        )
        client.force_login(de_outra_fazenda)
        for nome, pk in (
            ("procurement:compromisso_detalhe", compromisso.pk),
            ("procurement:compromisso_editar", compromisso.pk),
            ("procurement:viagem_detalhe", viagem.pk),
            ("procurement:recebimento_detalhe", recebimento.pk),
            ("procurement:romaneio", compromisso.items.get().pk),
        ):
            assert client.get(reverse(nome, args=[pk])).status_code == 404, nome

    def test_lista_so_mostra_o_que_a_fazenda_do_usuario_alcanca(
        self, client, baixao, compromisso
    ):
        de_outra = User.objects.create_user(
            username="outro", password="x", role=Role.ESCRITORIO
        )
        UserFarmAccess.objects.create(user=de_outra, farm=baixao, can_write=True)
        client.force_login(de_outra)
        html = client.get(reverse("procurement:compromisso_lista")).content.decode()
        assert compromisso.code not in html

    def test_post_sem_csrf_e_recusado(self, escritorio, compromisso):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(escritorio)
        resposta = cliente.post(
            reverse("procurement:acerto_novo", args=[compromisso.pk])
        )
        assert resposta.status_code == 403
        assert not Settlement.objects.exists()

    def test_escritorio_nao_aprova_acerto_pela_tela(self, client, escritorio, acerto):
        client.force_login(escritorio)
        resposta = client.post(reverse("procurement:acerto_aprovar", args=[acerto.pk]))
        acerto.refresh_from_db()
        assert resposta.status_code == 302 and acerto.status == Status.RASCUNHO


class TestFluxoPelasTelas:
    def test_do_compromisso_ao_acerto_aprovado_e_reaberto(
        self,
        client,
        gestor,
        sao_francisco,
        produtor,
        comissionado,
        categoria_desmamados,
        transportador,
        classe,
        regra_de_comissao,
    ):
        client.force_login(gestor)

        # compromisso, já aprovado
        resposta = client.post(
            reverse("procurement:compromisso_novo"),
            {
                "date": "2025-09-01",
                "seller": produtor.pk,
                "destination_farm": sao_francisco.pk,
                "pickup_date": "2025-09-03",
                "payment_days": "30",
                "acao": "aprovar",
                **formset(
                    "compradores",
                    [{"partner": comissionado.pk, "type": "PERCENTUAL", "value": ""}],
                ),
                **formset(
                    "itens",
                    [
                        {
                            "category": categoria_desmamados.pk,
                            "head_count": 10,
                            "avg_weight_kg": "480",
                            "price_basis": "ARROBA",
                            "price_band_4": "270.00",
                            "expected_band": "4",
                            "expected_arrobas": "17",
                        }
                    ],
                ),
            },
        )
        assert resposta.status_code == 302, resposta.content.decode()[:2000]
        compromisso = Commitment.objects.get()
        assert compromisso.status == Status.CONFIRMADA
        assert compromisso.commission.value == D(
            "1"
        )  # a regra vigente, gravada na aprovação
        item = compromisso.items.get()

        # viagem
        resposta = client.post(
            reverse("procurement:viagem_nova", args=[compromisso.pk]),
            {
                "pickup_date": "2025-09-03",
                "carrier": transportador.pk,
                "freight_criterion": "POR_CABECA",
                "freight_rate": "50",
                **formset(
                    "cargas",
                    [
                        {
                            "item": item.pk,
                            "planned_qty": 10,
                            "shipped_qty": 10,
                            "origin_weight_kg": "5000",
                        }
                    ],
                ),
            },
        )
        assert resposta.status_code == 302
        viagem = Trip.objects.get()

        # recebimento
        resposta = client.post(
            reverse("procurement:recebimento_novo", args=[viagem.pk]),
            {
                "date": "2025-09-04",
                "trip_loss_percent": "2",
                **formset(
                    "linhas",
                    [
                        {
                            "load": viagem.loads.get().pk,
                            "received_qty": 10,
                            "received_weight_kg": "4900",
                        }
                    ],
                ),
            },
        )
        assert resposta.status_code == 302
        recebimento = Receiving.objects.get()
        corpo = client.get(
            reverse("procurement:recebimento_detalhe", args=[recebimento.pk])
        ).content.decode()
        assert "Quebra de viagem" in corpo and "2,00%" in corpo

        # romaneio
        resposta = client.post(
            reverse("procurement:romaneio", args=[item.pk]),
            {
                **formset(
                    "linhas",
                    [
                        {
                            "carcass_class": classe.pk,
                            "band": 4,
                            "head_count": 10,
                            "carcass_weight_kg": "2400",
                        }
                    ],
                ),
            },
        )
        assert resposta.status_code == 302, resposta.content.decode()[:1500]

        # acerto
        client.post(reverse("procurement:acerto_novo", args=[compromisso.pk]))
        acerto = Settlement.objects.get()
        client.post(
            reverse("procurement:acerto_linhas", args=[acerto.pk]),
            formset(
                "linhas",
                [{"tax_type": tipo("Funrural").pk, "amount": "300"}],
            ),
        )
        detalhe = client.get(reverse("procurement:acerto_detalhe", args=[acerto.pk]))
        assert detalhe.status_code == 200
        html = detalhe.content.decode()
        assert "Previsto × realizado" in html and "Do bruto ao líquido" in html

        # aprovar
        confirmacao = client.get(
            reverse("procurement:acerto_aprovar", args=[acerto.pk])
        )
        assert "Aprovar este acerto vai" in confirmacao.content.decode()
        client.post(reverse("procurement:acerto_aprovar", args=[acerto.pk]))
        acerto.refresh_from_db()
        assert acerto.status == Status.CONFIRMADA
        compra = Purchase.objects.get()
        assert compra.status == Status.CONFIRMADA and compra.tax_value == D("300.00")

        # trava: o romaneio recusa edição e a mensagem diz o caminho
        resposta = client.post(
            reverse("procurement:romaneio", args=[item.pk]),
            formset("linhas", []),
        )
        assert resposta.status_code == 200
        assert "reabra o acerto" in resposta.content.decode()

        # impacto da reabertura, depois reabre
        impacto = client.get(reverse("procurement:acerto_reabrir", args=[acerto.pk]))
        assert "Isto vai desfazer" in impacto.content.decode()
        client.post(
            reverse("procurement:acerto_reabrir", args=[acerto.pk]),
            {"motivo": "Peso de carcaça trocado"},
        )
        acerto.refresh_from_db()
        compra.refresh_from_db()
        assert acerto.status == Status.RASCUNHO and compra.status == Status.EXCLUIDA

    def test_reabrir_sem_motivo_mostra_o_erro_e_nao_reabre(
        self, client, gestor, acerto_aprovado
    ):
        client.force_login(gestor)
        resposta = client.post(
            reverse("procurement:acerto_reabrir", args=[acerto_aprovado.pk]),
            {"motivo": ""},
        )
        assert resposta.status_code == 200
        assert "Motivo" in resposta.content.decode()
        acerto_aprovado.refresh_from_db()
        assert acerto_aprovado.status == Status.CONFIRMADA

    def test_reabrir_bloqueado_mostra_o_caminho_com_link(
        self, client, gestor, acerto_aprovado, escritorio
    ):
        closing.registrar_notas(
            acerto_aprovado,
            [
                {
                    "number": "752",
                    "series": "1",
                    "issue_date": DATA_RECEBIMENTO,
                    "amount": D("43200"),
                }
            ],
            usuario=escritorio,
        )
        client.force_login(gestor)
        html = client.get(
            reverse("procurement:acerto_reabrir", args=[acerto_aprovado.pk])
        ).content.decode()
        assert "nota fiscal registrada" in html
        assert "Ir para as notas fiscais" in html
        assert f"/acertos/{acerto_aprovado.pk}/#notas-fiscais" in html
        assert 'name="motivo"' not in html  # bloqueado: sem formulário de confirmar

    def test_escritorio_nao_reabre_pela_tela(self, client, escritorio, acerto_aprovado):
        client.force_login(escritorio)
        client.post(
            reverse("procurement:acerto_reabrir", args=[acerto_aprovado.pk]),
            {"motivo": "x"},
        )
        acerto_aprovado.refresh_from_db()
        assert acerto_aprovado.status == Status.CONFIRMADA

    def test_exclusao_de_compromisso_mostra_a_analise_de_impacto(
        self, client, gestor, compromisso, viagem
    ):
        client.force_login(gestor)
        html = client.get(
            reverse("procurement:compromisso_excluir", args=[compromisso.pk])
        ).content.decode()
        assert "Isto vai desfazer" in html and "dependem deste" in html
        assert viagem.code in html

    def test_exclusao_em_cascata_pela_tela_audita_como_um_ato(
        self, client, gestor, compromisso, viagem, recebimento
    ):
        client.force_login(gestor)
        client.post(
            reverse("procurement:compromisso_excluir", args=[compromisso.pk]),
            {"motivo": "Cancelado", "cascata": "1"},
        )
        compromisso.refresh_from_db()
        assert compromisso.status == Status.EXCLUIDA
        raizes = {
            e.cascade_root
            for e in AuditEvent.objects.filter(action="DELETE")
            if e.cascade_root
        }
        assert len(raizes) == 1

    def test_rascunho_do_compromisso_se_exclui_por_quem_lanca(
        self, client, escritorio, rascunho
    ):
        client.force_login(escritorio)
        client.post(
            reverse("procurement:compromisso_excluir", args=[rascunho.pk]),
            {"motivo": "Duplicado"},
        )
        rascunho.refresh_from_db()
        assert rascunho.status == Status.EXCLUIDA

    def test_escritorio_nao_exclui_compromisso_aprovado(
        self, client, escritorio, compromisso
    ):
        client.force_login(escritorio)
        client.post(
            reverse("procurement:compromisso_excluir", args=[compromisso.pk]),
            {"motivo": "x"},
        )
        compromisso.refresh_from_db()
        assert compromisso.status == Status.CONFIRMADA

    def test_restaurar_pela_tela(self, client, gestor, compromisso):
        client.force_login(gestor)
        client.post(
            reverse("procurement:compromisso_excluir", args=[compromisso.pk]),
            {"motivo": "Engano"},
        )
        client.post(reverse("procurement:compromisso_restaurar", args=[compromisso.pk]))
        compromisso.refresh_from_db()
        assert compromisso.status == Status.CONFIRMADA


class TestFormularios:
    def test_compromisso_sem_item_valido_mostra_erro_de_campo(
        self, client, escritorio, sao_francisco, produtor
    ):
        client.force_login(escritorio)
        resposta = client.post(
            reverse("procurement:compromisso_novo"),
            {
                "date": "2025-09-01",
                "seller": produtor.pk,
                "destination_farm": sao_francisco.pk,
                **formset("itens", [{"head_count": 10}], iniciais=1),
            },
        )
        assert resposta.status_code == 200
        assert not Commitment.objects.exists()
        assert "field-error" in resposta.content.decode()

    def test_erro_de_negocio_aparece_com_o_texto_especifico(
        self, client, escritorio, sao_francisco, comissionado, categoria_desmamados
    ):
        client.force_login(escritorio)
        resposta = client.post(
            reverse("procurement:compromisso_novo"),
            {
                "date": "2025-09-01",
                "seller": comissionado.pk,  # não é produtor nem fornecedor
                "destination_farm": sao_francisco.pk,
                **formset(
                    "itens",
                    [
                        {
                            "category": categoria_desmamados.pk,
                            "head_count": 5,
                            "price_basis": "ARROBA",
                            "price_band_1": "200",
                        }
                    ],
                    iniciais=1,
                ),
            },
        )
        # o parceiro nem aparece na escolha: o formulário recusa antes do serviço
        assert resposta.status_code == 200
        assert not Commitment.objects.exists()

    def test_corrigir_compromisso_aprovado_exige_motivo(
        self,
        client,
        escritorio,
        compromisso,
        produtor,
        sao_francisco,
        categoria_desmamados,
    ):
        client.force_login(escritorio)
        item = compromisso.items.get()
        resposta = client.post(
            reverse("procurement:compromisso_editar", args=[compromisso.pk]),
            {
                "date": "2025-09-01",
                "seller": produtor.pk,
                "destination_farm": sao_francisco.pk,
                "distance_km": "120",
                **formset("compradores", []),
                **formset(
                    "itens",
                    [
                        {
                            "id": item.pk,
                            "category": categoria_desmamados.pk,
                            "head_count": 10,
                            "price_basis": "ARROBA",
                            "price_band_4": "270",
                            "expected_band": "4",
                        }
                    ],
                    iniciais=1,
                ),
            },
        )
        assert resposta.status_code == 200
        assert "Informe o motivo" in resposta.content.decode()

    def test_romaneio_de_item_por_cabeca_redireciona_com_mensagem(
        self, client, escritorio, gestor, criar_compromisso, categoria_desmamados
    ):
        from apps.procurement import commitments
        from apps.procurement.tests.conftest import dados_item

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
            usuario=gestor,
        )
        client.force_login(escritorio)
        resposta = client.get(
            reverse("procurement:romaneio", args=[c.items.get().pk]), follow=True
        )
        assert "precificado por cabeça" in resposta.content.decode()

    def test_telas_de_detalhe_abrem(
        self, client, escritorio, compromisso, viagem, recebimento, romaneio, acerto
    ):
        client.force_login(escritorio)
        for nome, pk in (
            ("procurement:compromisso_detalhe", compromisso.pk),
            ("procurement:compromisso_editar", compromisso.pk),
            ("procurement:comissao_definir", compromisso.pk),
            ("procurement:viagem_nova", compromisso.pk),
            ("procurement:viagem_detalhe", viagem.pk),
            ("procurement:viagem_editar", viagem.pk),
            ("procurement:recebimento_novo", viagem.pk),
            ("procurement:recebimento_detalhe", recebimento.pk),
            ("procurement:recebimento_editar", recebimento.pk),
            ("procurement:romaneio", compromisso.items.get().pk),
            ("procurement:acerto_detalhe", acerto.pk),
            ("procurement:acerto_linhas", acerto.pk),
            ("procurement:acerto_notas", acerto.pk),
        ):
            resposta = client.get(reverse(nome, args=[pk]))
            assert resposta.status_code == 200, nome

    def test_menu_mostra_o_ciclo_para_quem_pode_ver_e_esconde_de_campo(
        self, client, escritorio, campo_baixao
    ):
        client.force_login(escritorio)
        assert "Compromissos" in client.get("/").content.decode()
        client.force_login(campo_baixao)
        assert "Compromissos" not in client.get("/").content.decode()

    def test_comissao_pela_tela(self, client, escritorio, compromisso, comissionado):
        client.force_login(escritorio)
        resposta = client.post(
            reverse("procurement:comissao_definir", args=[compromisso.pk]),
            {
                "payee": comissionado.pk,
                "type": "POR_CABECA",
                "base": "BRUTO",
                "value": "12.5",
                "extra_amount": "",
            },
        )
        assert resposta.status_code == 302
        from apps.procurement.models import Commission

        assert Commission.objects.get().type == "POR_CABECA"
