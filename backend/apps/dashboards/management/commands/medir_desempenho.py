"""Mede o tempo e o número de consultas de cada tela pesada.

Serve para duas coisas: ver onde dói **antes** de mexer (a linha de base) e
provar o ganho **depois**. Cada tela é pedida como um usuário de verdade, pelo
cliente de teste do Django, com o mesmo middleware, contexto e templates.

    python manage.py medir_desempenho                      # tabela
    python manage.py medir_desempenho --salvar /tmp/antes  # guarda o conteúdo
    python manage.py medir_desempenho --comparar /tmp/antes  # confere que nada mudou

`--salvar`/`--comparar` guardam os dados dos gráficos de cada aba (o JSON que
a tela entrega ao navegador): a otimização não pode mudar nenhum número.
"""

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.core import context as ctx
from apps.dashboards.bi.abas import ABAS

# Telas além do dashboard: (rótulo, nome da rota). Só as que listam muito.
TELAS = (
    ("Início", "dashboards:inicio"),
    ("Lotes", "livestock:lote_lista"),
    ("Movimentações", "herd:movimento_lista"),
    ("Pesagens", "herd:pesagem_lista"),
    ("Compras", "purchases:lista"),
    ("Vendas", "sales:lista"),
    ("Custos", "costs:lista"),
    ("Contas a pagar", "finance:contas_a_pagar"),
    ("Pagamentos", "finance:pagamento_lista"),
    ("Ciclo de compra", "procurement:compromisso_lista"),
    ("Acertos", "procurement:acerto_lista"),
    ("Parceiros", "partners:lista"),
    ("Auditoria", "audit:console"),
    ("Relatórios", "reports:indice"),
)


class Coletor:
    """Conta as consultas sem o teto de 9.000 do `connection.queries_log`:
    telas ruins passam disso e o log dá a volta, escondendo o problema."""

    def __init__(self):
        self.vezes = Counter()
        self.tempo = defaultdict(float)
        self.total = 0
        self.no_banco = 0.0

    def __call__(self, execute, sql, params, many, context):
        t0 = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            dt = time.perf_counter() - t0
            forma = _forma(sql)
            self.total += 1
            self.no_banco += dt
            self.vezes[forma] += 1
            self.tempo[forma] += dt

    def __len__(self):
        return self.total


_NUMEROS = re.compile(r"\b\d+(\.\d+)?\b")
_LITERAIS = re.compile(r"'[^']*'")
_LISTAS = re.compile(r"\((\s*%s\s*,?)+\)|\((\s*\?\s*,?)+\)")
_DADOS = re.compile(
    r'<script id="dash-dados" type="application/json">(.*?)</script>', re.S
)


def _forma(sql: str) -> str:
    """A consulta sem os valores: duas execuções iguais viram a mesma linha."""
    sql = _LITERAIS.sub("?", sql)
    sql = _NUMEROS.sub("?", sql)
    sql = _LISTAS.sub("(?)", sql)
    return re.sub(r"\s+", " ", sql)[:140]


class Command(BaseCommand):
    help = "Mede tempo e nº de consultas das telas pesadas (linha de base e prova)."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", default="gestor@teste")
        parser.add_argument("--safra", type=int, help="id da safra (padrão: a atual)")
        parser.add_argument("--fazenda", type=int, help="id da fazenda (padrão: todas)")
        parser.add_argument("--so", help="só telas cujo rótulo contém este texto")
        parser.add_argument("--repetidas", type=int, default=3)
        parser.add_argument("--salvar", help="pasta onde guardar o conteúdo das abas")
        parser.add_argument("--comparar", help="pasta guardada antes, para conferir")

    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError("Só em desenvolvimento (DEBUG=True).")
        try:
            usuario = User.objects.get(email=o["usuario"])
        except User.DoesNotExist as exc:
            raise CommandError(f"Usuário {o['usuario']} não existe.") from exc

        # O debug toolbar formata cada consulta (painel SQL) e, em telas com
        # milhares delas, passa a ser metade do tempo medido: fora da medição.
        self._sem_toolbar = override_settings(
            DEBUG_TOOLBAR_CONFIG={"SHOW_TOOLBAR_CALLBACK": lambda request: False}
        )
        self._sem_toolbar.enable()
        cliente = Client(HTTP_HOST="localhost")
        cliente.force_login(usuario)
        sessao = cliente.session
        if o["safra"]:
            sessao[ctx.SESSION_SEASON_ID] = o["safra"]
        if o["fazenda"]:
            sessao[ctx.SESSION_FARM_ID] = o["fazenda"]
        sessao.save()

        alvos = [
            (
                f"Dashboard › {a.rotulo}",
                reverse("dashboards:dashboard_aba", args=[a.slug]),
            )
            for a in ABAS
            if a.visivel(usuario)
        ]
        alvos += [(rotulo, reverse(rota)) for rotulo, rota in TELAS]
        if o["so"]:
            alvos = [t for t in alvos if o["so"].lower() in t[0].lower()]

        salvar = Path(o["salvar"]) if o["salvar"] else None
        comparar = Path(o["comparar"]) if o["comparar"] else None
        for pasta in (salvar,):
            if pasta:
                pasta.mkdir(parents=True, exist_ok=True)

        linhas, diferentes = [], []
        for rotulo, url in alvos:
            cliente.get(reverse("dashboards:inicio"))  # aquece sessão e conexão
            consultas = Coletor()
            with connection.execute_wrapper(consultas):
                t0 = time.perf_counter()
                resposta = cliente.get(url, HTTP_HX_REQUEST="true")
                dt = time.perf_counter() - t0
            linhas.append((rotulo, resposta.status_code, dt, consultas))

            html = resposta.content.decode("utf-8", "replace")
            achado = _DADOS.search(html)
            if achado and (salvar or comparar):
                nome = re.sub(r"\W+", "_", rotulo) + ".json"
                dados = json.dumps(json.loads(achado.group(1)), sort_keys=True)
                if salvar:
                    (salvar / nome).write_text(dados)
                if comparar:
                    antes = (comparar / nome).read_text()
                    if antes != dados:
                        diferentes.append(rotulo)

        self._imprimir(linhas, o["repetidas"])
        if comparar:
            if diferentes:
                self.stdout.write(
                    self.style.ERROR("NÚMEROS DIFERENTES em: " + ", ".join(diferentes))
                )
                raise CommandError("A otimização mudou o conteúdo de uma aba.")
            self.stdout.write(
                self.style.SUCCESS("Conteúdo das abas idêntico ao salvo.")
            )

    def _imprimir(self, linhas, quantas):
        largura = max(len(r) for r, *_ in linhas)
        self.stdout.write(
            f"\n{'Tela':<{largura}}  HTTP  {'tempo':>8}  {'consultas':>9}  {'no banco':>9}"
        )
        total_t = total_q = 0
        for rotulo, status, dt, consultas in linhas:
            no_banco = consultas.no_banco
            total_t += dt
            total_q += len(consultas)
            self.stdout.write(
                f"{rotulo:<{largura}}  {status:>4}  {dt:>7.2f}s  {len(consultas):>9}  {no_banco:>8.2f}s"
            )
            if quantas:
                for forma, vezes, seg in self._repetidas(consultas, quantas):
                    if vezes > 3:
                        self.stdout.write(f"    {vezes:>5}× {seg:>6.2f}s  {forma}")
        self.stdout.write(f"\nTotal: {total_t:.2f}s, {total_q} consultas.")

    @staticmethod
    def _repetidas(consultas, quantas):
        return [
            (f, n, consultas.tempo[f]) for f, n in consultas.vezes.most_common(quantas)
        ]
