"""Quem pode importar planilha: quem pode lançar o que ela traz."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role

PAPEIS_QUE_IMPORTAM = (Role.ADMIN, Role.GESTOR, Role.ESCRITORIO)


def pode_importar(user) -> bool:
    return user.is_authenticated and user.role in PAPEIS_QUE_IMPORTAM


class ImportaMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return pode_importar(self.request.user)
