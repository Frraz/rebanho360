import pytest
from django.http import Http404
from django.test import RequestFactory
from django.views.generic import DetailView, ListView

from apps.accounts.models import Role, User, UserFarmAccess
from apps.core.mixins import ScopedQuerysetMixin
from apps.core.models import ScopeTestModel
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db


@pytest.fixture
def farms():
    return (
        Farm.objects.create(name="Baixão", code="BXO"),
        Farm.objects.create(name="Goiano", code="GOI"),
    )


@pytest.fixture
def campo_user(farms):
    baixao, _goiano = farms
    user = User.objects.create_user(
        username="campo.baixao", password="x", role=Role.CAMPO
    )
    UserFarmAccess.objects.create(user=user, farm=baixao)
    return user


@pytest.fixture
def gestor_user():
    return User.objects.create_user(username="gestor", password="x", role=Role.GESTOR)


class TestScopedManager:
    def test_papel_com_acesso_restrito_so_ve_fazenda_concedida(self, farms, campo_user):
        baixao, goiano = farms
        ScopeTestModel.objects.create(farm=baixao, label="do baixão")
        ScopeTestModel.objects.create(farm=goiano, label="do goiano")

        visiveis = ScopeTestModel.objects.for_user(campo_user)

        assert list(visiveis.values_list("label", flat=True)) == ["do baixão"]

    def test_usuario_sem_nenhum_acesso_recebe_lista_vazia(self, farms):
        baixao, _goiano = farms
        ScopeTestModel.objects.create(farm=baixao, label="do baixão")
        sem_acesso = User.objects.create_user(username="ninguem", password="x")

        assert list(ScopeTestModel.objects.for_user(sem_acesso)) == []

    def test_admin_e_gestor_veem_tudo(self, farms, gestor_user):
        baixao, goiano = farms
        ScopeTestModel.objects.create(farm=baixao, label="do baixão")
        ScopeTestModel.objects.create(farm=goiano, label="do goiano")

        assert ScopeTestModel.objects.for_user(gestor_user).count() == 2


class _ScopedList(ScopedQuerysetMixin, ListView):
    model = ScopeTestModel

    def get_queryset(self):
        return super().get_queryset()


class _ScopedDetail(ScopedQuerysetMixin, DetailView):
    model = ScopeTestModel


class TestScopedViewDevolve404NuncaA403:
    def test_detalhe_fora_do_escopo_devolve_404_nao_403(self, farms, campo_user):
        _baixao, goiano = farms
        obj = ScopeTestModel.objects.create(farm=goiano, label="do goiano")

        request = RequestFactory().get(f"/objetos/{obj.pk}/")
        request.user = campo_user

        view = _ScopedDetail()
        view.setup(request, pk=obj.pk)
        view.kwargs = {"pk": obj.pk}

        with pytest.raises(Http404):
            view.get_object()
