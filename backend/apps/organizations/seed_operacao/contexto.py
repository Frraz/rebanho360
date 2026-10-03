"""Estado compartilhado de uma execução do seed.

O seed **não cria nem altera usuário**. Ele só descobre, entre os que já
existem, quem exerce cada papel e lança em nome dessa pessoa — como um
funcionário real faria. Papel sem usuário cai no administrador.
"""

import datetime
import heapq
import itertools
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.db import DataError, IntegrityError

from apps.accounts.models import Role, User
from apps.core.exceptions import BusinessError

ERROS_ESPERADOS = (BusinessError, IntegrityError, DataError)


@dataclass
class Atores:
    admin: User  # lança e dá baixa
    gestor: User  # aprova compromisso, acerto e pagamento
    avisos: list[str] = field(default_factory=list)


def descobrir_atores() -> Atores:
    """ADMIN e GESTOR entre os usuários ativos e não superusuários."""
    base = User.objects.filter(
        is_active=True, deleted_at__isnull=True, is_superuser=False
    )
    admin = base.filter(role=Role.ADMIN).order_by("id").first()
    if admin is None:
        raise ValueError(
            "Nenhum usuário ADMIN ativo. O seed lança em nome de um administrador "
            "existente e não cria usuário."
        )
    avisos = []
    gestor = base.filter(role=Role.GESTOR).order_by("id").first()
    if gestor is None:
        gestor = admin
        avisos.append(
            "Sem usuário GESTOR ativo: o ADMIN aprova compromissos, acertos e "
            "pagamentos. A baixa pode ser recusada por 'quem aprova não paga' se "
            "houver outro usuário financeiro com acesso."
        )
    return Atores(admin=admin, gestor=gestor, avisos=avisos)


@dataclass(order=True)
class Evento:
    data: datetime.date
    ordem: int
    tipo: str = field(compare=False)
    dados: dict = field(compare=False, default_factory=dict)


@dataclass
class LoteSim:
    """O que o seed sabe de um lote, além do banco: o plano de vida dele.

    Quantidades e categoria atual vêm sempre do razão (`herd.saldo`), nunca daqui.
    """

    lote: object
    fazenda: object
    categoria: str  # nome da categoria atual dos animais
    perfil: str  # perfil da fazenda onde o lote está
    data0: datetime.date
    peso0: object  # Decimal, kg por cabeça na entrada
    gmd: object  # Decimal, kg/dia no pico das águas
    plano: str  # ENGORDA, CONFINAMENTO, RECRIA, MATRIZES, BEZERROS
    rendimento: object | None = None
    sem_pesagem: bool = False  # caso proposital: lote esquecido sem pesar
    sem_carcaca: bool = False  # caso proposital: abate sem peso de carcaça
    saida_prevista: datetime.date | None = None


class Contexto:
    def __init__(self, *, rnd, escala, hoje, inicio, cutoff, company, atores, saida):
        self.rnd: random.Random = rnd
        self.escala = escala
        self.hoje = hoje
        self.inicio = inicio
        self.cutoff = cutoff
        self.company = company
        self.atores = atores
        self.admin = atores.admin
        self.gestor = atores.gestor
        self.saida = saida  # função de log (self.stdout.write)

        self.safras: list = []  # as 3 safras, em ordem
        self.safras_criadas: set[int] = set()  # pks criados pelo seed
        self.fazendas: dict[str, object] = {}  # code → Farm
        self.perfil: dict[str, str] = {}  # code → perfil
        self.parceiros: dict[str, list] = defaultdict(list)  # grupo → Partners
        self.pesos: dict[str, list[int]] = {}  # grupo → pesos de sorteio
        self.categorias: dict[str, object] = {}
        self.racas: list = []
        self.centros: dict[str, object] = {}
        self.classes: dict[str, object] = {}
        self.condicoes: dict[str, object] = {}
        self.tributos: dict[str, object] = {}
        self.carcass: dict[str, object] = {}
        self.maquinas: list = []

        self.lotes: dict[int, LoteSim] = {}
        self.matrizes: dict[str, LoteSim] = {}  # code da fazenda → lote das matrizes
        self.touros: dict[str, LoteSim] = {}
        self.nascidos: Counter = Counter()  # (farm.pk, safra.pk) → nascimentos
        self.desmamados: Counter = Counter()

        self._fila: list[Evento] = []
        self._seq = itertools.count()

        self.stats: Counter = Counter()
        self.falhas: dict[str, list[str]] = defaultdict(list)

    # ------------------------------------------------------------------ fila
    def agendar(self, data, nome_do_evento, /, **dados):
        """Põe um evento na fila. Data depois do corte (hoje ou o começo da
        próxima safra de outra empresa) nunca acontece."""
        if data is None or data > self.cutoff:
            return
        data = max(data, self.inicio)
        heapq.heappush(self._fila, Evento(data, next(self._seq), nome_do_evento, dados))

    def proximo(self) -> Evento | None:
        return heapq.heappop(self._fila) if self._fila else None

    @property
    def pendentes(self) -> int:
        return len(self._fila)

    # ------------------------------------------------------------- resultado
    def tentar(self, chave, funcao, *args, **kwargs):
        """Chama um serviço. Erro de regra de negócio vira contagem, não aborta:
        o seed mostra no fim quantas vezes cada coisa foi recusada e por quê."""
        try:
            resultado = funcao(*args, **kwargs)
        except ERROS_ESPERADOS as exc:
            self.stats[f"falha:{chave}"] += 1
            if len(self.falhas[chave]) < 3:
                self.falhas[chave].append(str(exc)[:240])
            return None
        self.stats[chave] += 1
        return resultado

    def safra_da_data(self, data):
        for s in self.safras:
            if s.start_date <= data <= s.end_date:
                return s
        return None

    def log(self, texto: str):
        self.saida(texto)
