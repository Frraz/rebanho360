import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.exceptions import BusinessError
from apps.documents.models import GeneratedDocument
from apps.documents.services import renderizar_html
from apps.procurement import commitments
from apps.procurement.scheduling import SLUG
from apps.procurement.tests.conftest import dados_item
from apps.reports.services import montar_relatorio

pytestmark = pytest.mark.django_db


def test_exemplo_cliente(criar_compromisso, categoria_desmamados, gestor):
    with patch("apps.documents.services.renderizar_pdf", return_value=b"%PDF-test"):
        for cabecas, media, preco in [(150, 5, 380), (250, 10, 350), (225, 11, 360)]:
            c = criar_compromisso(
                expected_payment_date=datetime.date(2026, 10, 15),
                itens=[
                    dados_item(
                        categoria_desmamados,
                        head_count=cabecas,
                        expected_arrobas=Decimal(media),
                        expected_band=1,
                        price_band_1=Decimal(preco),
                    )
                ],
            )
            commitments.aprovar_compromisso(c, usuario=gestor)
    r = montar_relatorio(gestor, SLUG, season=c.season, farm=c.destination_farm)
    assert len(r.linhas) == 3
    assert r.totais["cabecas"] == 625
    assert r.totais["valor"] == Decimal("2051000")
    html = renderizar_html(
        r, emitido_por="Teste", emitido_em=timezone.now(), versao="teste"
    )
    assert "15/10/2026" in html
    assert "Produtor:" in html
    assert "2.051.000,00" in html
    assert GeneratedDocument.objects.filter(entity_id=SLUG).count() == 3


def test_falha_pdf_preserva_aprovacao_e_retry(client, gestor, rascunho):
    with patch(
        "apps.documents.services.renderizar_pdf", side_effect=RuntimeError("teste")
    ):
        c = commitments.aprovar_compromisso(rascunho, usuario=gestor)
    c.refresh_from_db()
    assert c.status == "CONFIRMADA"
    doc = GeneratedDocument.objects.get(entity_id=SLUG)
    assert doc.status == "ERRO"
    with pytest.raises(BusinessError):
        commitments.aprovar_compromisso(c, usuario=gestor)
    assert GeneratedDocument.objects.filter(entity_id=SLUG).count() == 1
    client.force_login(gestor)
    with patch("apps.documents.services.renderizar_pdf", return_value=b"%PDF-test"):
        assert (
            client.post(
                reverse("documents:regerar_programacao", args=[doc.document_id])
            ).status_code
            == 302
        )
    doc.refresh_from_db()
    assert doc.status == "PRONTO"


def test_previsao_incompleta_e_filtros(criar_compromisso, categoria_desmamados, gestor):
    c = criar_compromisso(
        itens=[dados_item(categoria_desmamados, expected_arrobas=None)]
    )
    with patch("apps.documents.services.renderizar_pdf", return_value=b"%PDF-test"):
        commitments.aprovar_compromisso(c, usuario=gestor)
    r = montar_relatorio(gestor, SLUG, season=c.season, farm=c.destination_farm)
    assert r.secoes[0].linhas[0]["valor"] is None
    assert r.totais["situacao"] == "Total parcial"
    assert r.totais["valor"] is None
    assert "Não informada" in " ".join(r.secoes[0].notas)
    r = montar_relatorio(
        gestor,
        SLUG,
        season=c.season,
        farm=c.destination_farm,
        extras={"start": c.date + datetime.timedelta(days=1)},
    )
    assert not r.linhas


def test_papel_escopo_e_formulario(client, campo_baixao, escritorio, gestor, rascunho):
    from django.core.exceptions import PermissionDenied

    from apps.accounts.models import Role, User

    with patch("apps.documents.services.renderizar_pdf", return_value=b"%PDF-test"):
        commitments.aprovar_compromisso(rascunho, usuario=gestor)
    with pytest.raises(PermissionDenied):
        montar_relatorio(campo_baixao, SLUG, season=rascunho.season, farm=None)
    restrito = User.objects.create_user(
        username="programacao-restrita", password="teste", role=Role.ESCRITORIO
    )
    # Sem fazendas autorizadas, nenhum compromisso pode aparecer.
    assert not montar_relatorio(
        restrito, SLUG, season=rascunho.season, farm=None
    ).linhas
    client.force_login(escritorio)
    response = client.get(reverse("procurement:compromisso_editar", args=[rascunho.pk]))
    assert response.status_code == 200
    assert b"expected_payment_date" in response.content
    import os
    from pathlib import Path

    if os.environ.get("JEFESON_EVIDENCE_DIR"):
        Path(os.environ["JEFESON_EVIDENCE_DIR"], "formulario.html").write_bytes(
            response.content
        )


def test_pdf_real_multiplas_paginas(criar_compromisso, gestor, tmp_path):
    import os
    from pathlib import Path

    from apps.documents.services import renderizar_pdf

    c = criar_compromisso()
    with patch("apps.documents.services.renderizar_pdf", return_value=b"%PDF-test"):
        commitments.aprovar_compromisso(c, usuario=gestor)
    r = montar_relatorio(gestor, SLUG, season=c.season, farm=c.destination_farm)
    r.secoes = r.secoes * 16
    pdf = renderizar_pdf(
        r,
        emitido_por="Validação sintética",
        emitido_em=timezone.now(),
        versao="programacao-v1",
    )
    assert pdf.startswith(b"%PDF")
    if os.environ.get("JEFESON_EVIDENCE_DIR"):
        Path(os.environ["JEFESON_EVIDENCE_DIR"], "programacao.pdf").write_bytes(pdf)


def test_cabeca_rascunho_e_data_editavel(
    criar_compromisso, categoria_desmamados, gestor
):
    from apps.procurement.models import PriceBasis

    criar_compromisso()  # negociação não entra no consolidado
    data = datetime.date(2026, 11, 1)
    c = criar_compromisso(
        itens=[
            dados_item(
                categoria_desmamados,
                head_count=3,
                price_basis=PriceBasis.CABECA,
                unit_price=Decimal("1500"),
            )
        ]
    )
    commitments.editar_rascunho(
        c, {"expected_payment_date": data}, None, usuario=gestor
    )
    c.refresh_from_db()
    assert c.expected_payment_date == data
    with patch("apps.documents.services.renderizar_pdf", return_value=b"%PDF-test"):
        commitments.aprovar_compromisso(c, usuario=gestor)
    r = montar_relatorio(gestor, SLUG, season=c.season, farm=c.destination_farm)
    assert len(r.linhas) == 1
    assert r.totais["valor"] == Decimal("4500")
    assert r.secoes[0].linhas[0]["media"] is None


def test_retry_protegido(client, escritorio, gestor, rascunho):
    with patch(
        "apps.documents.services.renderizar_pdf", side_effect=RuntimeError("teste")
    ):
        commitments.aprovar_compromisso(rascunho, usuario=gestor)
    doc = GeneratedDocument.objects.get(entity_id=SLUG)
    url = reverse("documents:regerar_programacao", args=[doc.document_id])
    client.force_login(escritorio)
    assert client.post(url).status_code == 404
    client.force_login(gestor)
    assert client.get(url).status_code == 405


def test_fax_e_fantasia_no_contrato(rascunho, gestor):
    from apps.procurement.contract import renderizar_html as contrato_html

    rascunho.seller.trade_name = "Produtor sintético"
    rascunho.seller.fax = "(00) 0000-0000"
    html = contrato_html(rascunho, emitido_por="Teste", emitido_em=timezone.now())
    assert "Produtor sintético" in html
    assert "(00) 0000-0000" in html
    assert rascunho.commissioned.name in html
