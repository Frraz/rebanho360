"""Login por usuário **ou** e-mail (resposta do cliente, 2026-10-03: o e-mail
faz parte da identificação do usuário)."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOuUsuarioBackend(ModelBackend):
    """Tenta o usuário; se não achar e o texto parece e-mail, procura pelo e-mail.

    O e-mail é único entre as contas não excluídas (constraint `uniq_user_email_ci`),
    então a busca nunca é ambígua. Conta excluída não entra — e o resto das
    regras (inativo, senha, segundo fator) continua sendo do `ModelBackend`.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        usuario = super().authenticate(request, username, password, **kwargs)
        if usuario is not None or not username or "@" not in username:
            return usuario
        User = get_user_model()
        candidato = User.objects.filter(
            email__iexact=username.strip(), deleted_at__isnull=True
        ).first()
        if candidato is None:
            # Gasta o mesmo tempo de um hash, para não revelar se o e-mail existe.
            User().set_password(password or "")
            return None
        return super().authenticate(
            request, candidato.get_username(), password, **kwargs
        )
