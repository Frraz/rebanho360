"""Leitura. Consultas e agregações."""

from django.db.models import Count, Q

from apps.accounts.models import AccessRequest, AccessRequestStatus, User

ESTADOS = (
    ("ativos", "Ativos"),
    ("inativos", "Inativos"),
    ("excluidos", "Excluídos"),
    ("todos", "Todos"),
)


def usuarios_visiveis(ator):
    """Usuários que `ator` pode ver. O superusuário é a conta de suporte: fica
    escondido de todos os demais (listas, detalhe, filtros). Só ele mesmo e
    outros superusuários o enxergam."""
    if ator is not None and getattr(ator, "is_superuser", False):
        return User.objects.all()
    return User.objects.filter(is_superuser=False)


def listar_usuarios(*, ator, termo: str = "", papel: str = "", estado: str = "ativos"):
    qs = usuarios_visiveis(ator).annotate(
        qtd_fazendas=Count("farm_access", distinct=True)
    )
    if estado == "ativos":
        qs = qs.filter(is_active=True, deleted_at__isnull=True)
    elif estado == "inativos":
        qs = qs.filter(is_active=False, deleted_at__isnull=True)
    elif estado == "excluidos":
        qs = qs.filter(deleted_at__isnull=False)
    if papel:
        qs = qs.filter(role=papel)
    termo = (termo or "").strip()
    if termo:
        qs = qs.filter(
            Q(username__icontains=termo)
            | Q(first_name__icontains=termo)
            | Q(last_name__icontains=termo)
            | Q(email__icontains=termo)
        )
    return qs.order_by("first_name", "username")


def contar_solicitacoes_pendentes() -> int:
    return AccessRequest.objects.filter(status=AccessRequestStatus.PENDENTE).count()


def listar_solicitacoes(*, situacao: str = "PENDENTE"):
    qs = AccessRequest.objects.select_related("decided_by", "user")
    if situacao in AccessRequestStatus.values:
        qs = qs.filter(status=situacao)
    return qs
