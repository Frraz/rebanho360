"""O que acontece quando a exportação demora, falha, é cancelada ou expira."""

import datetime

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.exceptions import BusinessError
from apps.exports import catalog, services, tabular, tasks, writers
from apps.exports.models import ExportJob, ExportStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def na_fila(monkeypatch, django_capture_on_commit_callbacks):
    """Pede mas NÃO executa: o pedido fica na fila, como com o processador parado."""
    monkeypatch.setattr(tasks.executar, "delay", lambda pk: None)

    def _pedir(user, **pedido):
        pedido.setdefault("conjuntos", ["lotes"])
        pedido.setdefault("formatos", ["csv"])
        with django_capture_on_commit_callbacks(execute=True):
            return services.solicitar_exportacao(user=user, **pedido)

    return _pedir


class TestFila:
    def test_o_pedido_nasce_na_fila_com_os_itens_a_fazer(
        self, na_fila, gestor, operacao
    ):
        job = na_fila(
            gestor, conjuntos=["lotes", "compras"], relatorios=["custos-por-centro"]
        )

        assert job.status == ExportStatus.PENDENTE and job.em_andamento
        assert [i["estado"] for i in job.items] == ["pendente"] * 3
        assert [i["id"] for i in job.items] == [
            "dados:lotes",
            "dados:compras",
            "relatorio:custos-por-centro",
        ]
        assert job.percentual == 0

    def test_a_tarefa_e_enfileirada_so_depois_do_commit(
        self, monkeypatch, gestor, django_capture_on_commit_callbacks
    ):
        chamadas = []
        monkeypatch.setattr(tasks.executar, "delay", lambda pk: chamadas.append(pk))

        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            job = services.solicitar_exportacao(
                user=gestor, conjuntos=["lotes"], formatos=["csv"]
            )
            assert chamadas == []  # ainda dentro da transação do pedido
        assert len(callbacks) == 1
        callbacks[0]()
        assert chamadas == [job.pk]

    def test_fila_fora_do_ar_vira_erro_claro_em_vez_de_espera_eterna(
        self, monkeypatch, gestor, django_capture_on_commit_callbacks
    ):
        def quebra(pk):
            raise ConnectionError("redis fora do ar")

        monkeypatch.setattr(tasks.executar, "delay", quebra)
        with django_capture_on_commit_callbacks(execute=True):
            job = services.solicitar_exportacao(
                user=gestor, conjuntos=["lotes"], formatos=["csv"]
            )

        job.refresh_from_db()
        assert job.status == ExportStatus.ERRO
        assert "colocar a exportação na fila" in job.error

    def test_cada_um_tem_no_maximo_duas_em_andamento(self, na_fila, gestor, escritorio):
        na_fila(gestor)
        na_fila(gestor)
        with pytest.raises(BusinessError, match="já tem 2 exportações em andamento"):
            na_fila(gestor)
        assert (
            na_fila(escritorio).status == ExportStatus.PENDENTE
        )  # o limite é por pessoa

    def test_terminada_nao_conta_para_o_limite(self, na_fila, gestor):
        a = na_fila(gestor)
        na_fila(gestor)
        services.cancelar_exportacao(a, user=gestor)
        assert na_fila(gestor).status == ExportStatus.PENDENTE

    @pytest.mark.parametrize(
        "pedido,mensagem",
        [
            ({"conjuntos": [], "formatos": ["csv"]}, "pelo menos um conjunto"),
            ({"conjuntos": ["lotes"], "formatos": []}, "pelo menos um formato"),
            (
                {"conjuntos": ["lotes"], "formatos": ["docx"]},
                "Formato de arquivo desconhecido",
            ),
            ({"conjuntos": ["nao-existe"], "formatos": ["csv"]}, "nao-existe"),
            (
                {"relatorios": ["nao-existe"], "formatos": ["csv"]},
                "relatórios escolhidos",
            ),
            (
                {
                    "conjuntos": ["lotes"],
                    "formatos": ["csv"],
                    "de": datetime.date(2025, 9, 1),
                    "ate": datetime.date(2025, 8, 1),
                },
                "data inicial é depois",
            ),
        ],
    )
    def test_pedido_invalido_diz_o_que_falta(self, na_fila, gestor, pedido, mensagem):
        base = {"conjuntos": [], "formatos": []}
        with pytest.raises(BusinessError, match=mensagem):
            na_fila(gestor, **{**base, **pedido})

    def test_so_arquivos_anexos_dispensa_formato(self, na_fila, gestor):
        assert na_fila(gestor, conjuntos=[], formatos=[], incluir_arquivos=True)


class TestIdempotencia:
    def test_executar_duas_vezes_gera_um_arquivo_so(self, na_fila, gestor, operacao):
        job = na_fila(gestor)

        primeira = services.executar_exportacao(job.pk)
        arquivo = primeira.file.name
        segunda = services.executar_exportacao(job.pk)

        assert primeira.status == segunda.status == ExportStatus.PRONTO
        assert segunda.file.name == arquivo
        assert ExportJob.objects.count() == 1

    def test_pedido_que_nao_esta_na_fila_nao_roda(self, na_fila, gestor):
        job = na_fila(gestor)
        services.cancelar_exportacao(job, user=gestor)

        job = services.executar_exportacao(job.pk)

        assert job.status == ExportStatus.CANCELADO and not job.file


class TestCancelamento:
    def test_cancelar_na_fila_e_na_hora(self, na_fila, gestor):
        job = na_fila(gestor)

        job = services.cancelar_exportacao(job, user=gestor)

        assert job.status == ExportStatus.CANCELADO and job.finished_at
        assert AuditEvent.objects.filter(
            entity_id=str(job.job_id), action="CANCEL"
        ).exists()

    def test_cancelar_rodando_para_no_proximo_ponto_de_controle_e_nao_entrega_nada(
        self, na_fila, gestor, operacao, monkeypatch
    ):
        job = na_fila(gestor, conjuntos=["lotes", "compras", "razao-do-rebanho"])
        lidos = []
        original = services._ler_conjunto

        def le_e_pede_cancelamento(conjunto, *a, **kw):
            resultado = original(conjunto, *a, **kw)
            lidos.append(conjunto.chave)
            # Pedido de cancelamento chega no meio da exportação.
            ExportJob.objects.filter(pk=job.pk).update(cancel_requested=True)
            return resultado

        monkeypatch.setattr(services, "_ler_conjunto", le_e_pede_cancelamento)
        monkeypatch.setattr(services, "PASSO_DO_PROGRESSO", 1)

        job = services.executar_exportacao(job.pk)

        assert job.status == ExportStatus.CANCELADO
        assert not job.file and lidos == [
            "lotes"
        ]  # parou no ponto de controle seguinte

    def test_nao_ha_o_que_cancelar_depois_de_pronta(self, na_fila, gestor, operacao):
        job = services.executar_exportacao(na_fila(gestor).pk)
        with pytest.raises(BusinessError, match="já terminou"):
            services.cancelar_exportacao(job, user=gestor)

    def test_arquivos_temporarios_nao_sobram(self, na_fila, gestor, operacao, settings):
        services.executar_exportacao(na_fila(gestor).pk)
        raiz = services._raiz_temporaria()
        assert list(raiz.iterdir()) == []


class TestFalhas:
    def test_falha_ao_ler_um_conjunto_derruba_tudo_e_nomeia_o_conjunto(
        self, na_fila, gestor, operacao, monkeypatch
    ):
        """Backup que perdeu uma tabela sem avisar é pior que nenhum."""
        job = na_fila(gestor, conjuntos=["lotes", "compras"], formatos=["csv", "json"])
        original = tabular.vinculos_a_carregar

        def quebra_em_compras(conjunto, *a, **kw):
            if conjunto.chave == "compras":
                raise RuntimeError("tabela corrompida")
            return original(conjunto, *a, **kw)

        monkeypatch.setattr(tabular, "vinculos_a_carregar", quebra_em_compras)

        job = services.executar_exportacao(job.pk)

        assert job.status == ExportStatus.ERRO and not job.file
        assert "Compras" in job.error and "Nada foi entregue" in job.error
        assert "tabela corrompida" not in job.error  # nunca traceback para o usuário
        assert str(job.job_id) in job.error  # mas o suporte consegue achar o log
        estados = {i["id"]: i["estado"] for i in job.items}
        assert estados == {"dados:lotes": "ok", "dados:compras": "erro"}

    def test_falha_ate_na_contagem_nomeia_o_conjunto(
        self, na_fila, gestor, operacao, monkeypatch
    ):
        job = na_fila(gestor, conjuntos=["lotes", "compras"])
        original = tabular.consulta
        monkeypatch.setattr(
            tabular,
            "consulta",
            lambda c, *a, **kw: (
                (_ for _ in ()).throw(RuntimeError("x"))
                if c.chave == "compras"
                else original(c, *a, **kw)
            ),
        )

        job = services.executar_exportacao(job.pk)

        assert job.status == ExportStatus.ERRO and "Compras" in job.error

    def test_relatorio_que_falha_vira_aviso_e_o_resto_segue(
        self, na_fila, gestor, operacao, monkeypatch
    ):
        from apps.reports import services as relatorios

        original = relatorios.montar_relatorio

        def quebra(user, slug, **kw):
            if slug == "custos-por-centro":
                raise RuntimeError("falhou")
            return original(user, slug, **kw)

        monkeypatch.setattr(relatorios, "montar_relatorio", quebra)
        job = na_fila(
            gestor,
            conjuntos=["lotes"],
            relatorios=["custos-por-centro", "custos-por-fazenda"],
            formatos=["csv"],
        )

        job = services.executar_exportacao(job.pk)

        assert job.status == ExportStatus.PRONTO
        assert any("Custos por centro de custo" in a for a in job.warnings)
        estados = {i["id"]: i["estado"] for i in job.items}
        assert estados["relatorio:custos-por-centro"] == "erro"
        assert estados["relatorio:custos-por-fazenda"] in ("ok",)

    def test_se_tudo_ficou_de_fora_nao_entrega_zip_vazio(self, na_fila, financeiro):
        from apps.accounts.models import Role

        job = na_fila(financeiro, conjuntos=["contas-bancarias"], formatos=["csv"])
        financeiro.role = Role.ESCRITORIO
        financeiro.save()

        job = services.executar_exportacao(job.pk)

        assert (
            job.status == ExportStatus.ERRO and "Nenhum arquivo foi gerado" in job.error
        )


class TestManutencao:
    def test_exportacao_sem_sinal_de_vida_e_dada_como_interrompida(
        self, na_fila, gestor
    ):
        job = na_fila(gestor)
        ExportJob.objects.filter(pk=job.pk).update(
            status=ExportStatus.PROCESSANDO,
            heartbeat_at=timezone.now() - datetime.timedelta(minutes=45),
        )
        viva = na_fila(gestor)
        ExportJob.objects.filter(pk=viva.pk).update(
            status=ExportStatus.PROCESSANDO, heartbeat_at=timezone.now()
        )

        resultado = services.manutencao()

        assert resultado["interrompidas"] == 1
        job.refresh_from_db()
        viva.refresh_from_db()
        assert job.status == ExportStatus.ERRO and "interrompida" in job.error
        assert viva.status == ExportStatus.PROCESSANDO

    def test_arquivo_vencido_e_apagado_e_o_pedido_fica(self, na_fila, gestor, operacao):
        job = services.executar_exportacao(na_fila(gestor).pk)
        caminho = job.file.path
        import os

        assert os.path.exists(caminho)
        ExportJob.objects.filter(pk=job.pk).update(
            expires_at=timezone.now() - datetime.timedelta(minutes=1)
        )

        resultado = services.manutencao()

        job.refresh_from_db()
        assert resultado["expiradas"] == 1
        assert (
            job.status == ExportStatus.EXPIRADO and not job.file and job.file_removed_at
        )
        assert not os.path.exists(caminho)
        assert ExportJob.objects.filter(
            pk=job.pk
        ).exists()  # o pedido nunca sai do banco
        assert AuditEvent.objects.filter(
            entity_id=str(job.job_id), action="DELETE", reason__contains="prazo"
        ).exists()

    def test_o_prazo_padrao_e_de_30_dias(self, na_fila, gestor, operacao, settings):
        del settings.EXPORT_RETENTION_DAYS  # o que vale sem o .env
        job = services.executar_exportacao(na_fila(gestor).pk)
        assert (
            datetime.timedelta(days=29, hours=23)
            < job.expires_at - job.finished_at
            <= datetime.timedelta(days=30)
        )

    def test_o_prazo_vem_da_configuracao(self, na_fila, gestor, operacao, settings):
        settings.EXPORT_RETENTION_DAYS = 2
        job = services.executar_exportacao(na_fila(gestor).pk)
        assert (
            datetime.timedelta(days=1, hours=23)
            < job.expires_at - job.finished_at
            <= datetime.timedelta(days=2)
        )

    def test_quem_pediu_pode_apagar_o_arquivo_antes_do_prazo(
        self, na_fila, gestor, operacao
    ):
        job = services.executar_exportacao(na_fila(gestor).pk)

        job = services.apagar_arquivo(job, user=gestor)

        assert job.status == ExportStatus.EXPIRADO and not job.file
        with pytest.raises(BusinessError):
            services.apagar_arquivo(job, user=gestor)

    def test_pedir_de_novo_repete_os_parametros(
        self, na_fila, gestor, baixao, operacao
    ):
        original = na_fila(
            gestor,
            conjuntos=["lotes", "compras"],
            formatos=["csv", "json"],
            fazenda=baixao,
            incluir_excluidos=True,
            estilo_csv="intl",
        )
        services.cancelar_exportacao(original, user=gestor)

        novo = services.repetir_exportacao(original, user=gestor)

        assert novo.pk != original.pk and novo.status == ExportStatus.PENDENTE
        assert novo.params == original.params


class TestProgresso:
    def test_o_progresso_anda_e_a_etapa_diz_o_que_esta_sendo_lido(
        self, na_fila, gestor, operacao, monkeypatch
    ):
        job = na_fila(gestor, conjuntos=["lotes", "razao-do-rebanho"])
        vistos = []
        original = services.Progresso.sincronizar

        def espia(self):
            original(self)
            atual = ExportJob.objects.get(pk=self.job.pk)
            vistos.append(
                (atual.status, atual.stage, atual.work_done, atual.work_total)
            )

        monkeypatch.setattr(services.Progresso, "sincronizar", espia)
        monkeypatch.setattr(services, "PASSO_DO_PROGRESSO", 1)

        job = services.executar_exportacao(job.pk)

        assert job.status == ExportStatus.PRONTO and job.percentual == 100
        assert all(s == ExportStatus.PROCESSANDO for s, *_ in vistos)
        etapas = [e for _, e, _, _ in vistos]
        assert any(e.startswith("Lendo Lotes (1 de 2)") for e in etapas)
        assert any(
            e.startswith("Lendo Razão do rebanho (linhas) (2 de 2)") for e in etapas
        )
        feitos = [f for *_, f, _ in vistos]
        assert feitos == sorted(feitos) and feitos[-1] > feitos[0]
        total = vistos[-1][3]
        assert total == sum(
            tabular.contar(catalog.conjunto_por_chave(k), gestor, tabular.Filtros())
            for k in ("lotes", "razao-do-rebanho")
        )

    def test_item_a_item_o_estado_e_a_contagem_ficam_gravados(
        self, na_fila, gestor, operacao
    ):
        job = services.executar_exportacao(
            na_fila(gestor, conjuntos=["lotes", "pastos"]).pk
        )
        itens = {i["id"]: i for i in job.items}
        assert (
            itens["dados:lotes"]["estado"] == "ok"
            and itens["dados:lotes"]["linhas"] == 4
        )
        assert (
            itens["dados:pastos"]["estado"] == "vazio"
            and itens["dados:pastos"]["linhas"] == 0
        )


class TestPdfEmPartes:
    def test_tabela_grande_vira_varios_pdfs_e_a_unica_parte_nao_ganha_sufixo(
        self, tmp_path, gestor, operacao
    ):
        meta = {
            "gerado_por": "teste",
            "gerado_em_dt": timezone.localtime(),
            "filtros": ["Todas as safras"],
        }
        colunas = tabular.colunas_do_conjunto(
            catalog.conjunto_por_chave("lotes"), gestor, tabular.LEGIVEL
        )
        conjunto = catalog.conjunto_por_chave("lotes")

        def gerar(linhas_por_parte, limite, n):
            escritor = writers.PdfEscritor(tmp_path / str(n), meta=meta)
            escritor.LINHAS_POR_PARTE, escritor.LIMITE_DE_LINHAS = (
                linhas_por_parte,
                limite,
            )
            escritor.abrir(conjunto, colunas)
            for i in range(n):
                escritor.linha([None] * len(colunas))
            return escritor.fechar()

        unica = gerar(10, 100, 10)  # exatamente uma parte cheia
        assert [a.nome for a in unica] == ["pdf/lotes.pdf"]
        varias = gerar(10, 100, 25)
        assert [a.nome for a in varias] == [
            "pdf/lotes-parte-01.pdf",
            "pdf/lotes-parte-02.pdf",
            "pdf/lotes-parte-03.pdf",
        ]
        cortada = gerar(10, 20, 35)
        assert len(cortada) == 2 and "primeiras 20 linhas" in cortada[0].aviso
