from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class Role(models.TextChoices):
    """Papel define a ação; `UserFarmAccess` define o alcance (ADR 0003)."""

    ADMIN = "ADMIN", "Administrador"
    GESTOR = "GESTOR", "Gestor"
    ESCRITORIO = "ESCRITORIO", "Escritório"
    CAMPO = "CAMPO", "Campo"
    FINANCEIRO = "FINANCEIRO", "Financeiro"
    CONSULTA = "CONSULTA", "Consulta"


ROLES_COM_ACESSO_AMPLO = (Role.ADMIN, Role.GESTOR)


class User(AbstractUser):
    """Usuário do sistema. Papel + escopo de fazenda definem o que vê."""

    role = models.CharField(
        "Papel",
        max_length=20,
        choices=Role.choices,
        default=Role.CONSULTA,
    )
    phone = models.CharField("Telefone", max_length=20, blank=True)
    birth_date = models.DateField("Data de nascimento", null=True, blank=True)
    # Opcional e só com dígitos. Quem edita é o próprio usuário (página Conta);
    # na auditoria e nas telas de terceiros aparece mascarado.
    cpf = models.CharField("CPF", max_length=11, blank=True)
    last_login_ip = models.GenericIPAddressField(
        "Último IP de login", null=True, blank=True
    )
    # Senha temporária definida por um administrador: a pessoa troca no primeiro
    # acesso (`PasswordChangeRequiredMiddleware`).
    must_change_password = models.BooleanField("Deve trocar a senha", default=False)
    # Exclusão lógica (regra 5): o usuário sai da operação, nunca do banco — a
    # auditoria e os registros que ele lançou continuam apontando para ele.
    deleted_at = models.DateTimeField("Excluído em", null=True, blank=True)

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"
        constraints = [
            # Um e-mail, uma conta — sem diferenciar maiúsculas. Quem não tem
            # e-mail (pessoal de campo) fica de fora, assim como o excluído:
            # o e-mail dele pode ser usado de novo.
            models.UniqueConstraint(
                Lower("email"),
                condition=models.Q(deleted_at__isnull=True) & ~models.Q(email=""),
                name="uniq_user_email_ci",
            ),
            # Um CPF, uma conta. O opcional (vazio) e o excluído ficam de fora.
            models.UniqueConstraint(
                "cpf",
                condition=models.Q(deleted_at__isnull=True) & ~models.Q(cpf=""),
                name="uniq_user_cpf",
            ),
        ]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def has_broad_access(self) -> bool:
        """`ADMIN` e `GESTOR` enxergam todas as fazendas por definição do papel.
        O superusuário (oculto, de suporte) enxerga tudo, qualquer que seja o papel."""
        return self.is_superuser or self.role in ROLES_COM_ACESSO_AMPLO

    def accessible_farms(self):
        """Fazendas às quais o usuário tem acesso explícito via `UserFarmAccess`.

        Para `ADMIN`/`GESTOR`, use `ScopedManager.for_user()` diretamente —
        eles não precisam de linhas em `UserFarmAccess` para ver tudo.
        """
        from apps.properties.models import Farm

        farm_ids = self.farm_access.values_list("farm_id", flat=True)
        return Farm.objects.filter(id__in=farm_ids)


class UserFarmAccess(models.Model):
    """Escopo: user × fazenda. O papel define *o quê*; isto define *onde*.

    `Farm` só nasce na F1-02 — FK preguiçosa ("properties.Farm") para que
    `accounts` não dependa de `properties`. Ver ADR 0003.
    """

    user = models.ForeignKey(
        User,
        verbose_name="Usuário",
        related_name="farm_access",
        on_delete=models.CASCADE,
    )
    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="user_access",
        on_delete=models.CASCADE,
    )
    can_write = models.BooleanField("Pode lançar", default=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Acesso por fazenda"
        verbose_name_plural = "Acessos por fazenda"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "farm"], name="uniq_user_farm_access"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.farm_id}"


class TOTPDevice(models.Model):
    """O aplicativo autenticador do usuário (segundo fator, F4-09).

    O segredo é só dele e do servidor: nunca vai para log, para auditoria
    (`snapshot()` não é chamado neste modelo) nem para URL. `confirmed` só
    vira verdadeiro depois que o usuário prova que o aplicativo gera os
    códigos — configurar pela metade não tranca ninguém fora.
    """

    user = models.OneToOneField(
        User,
        verbose_name="Usuário",
        related_name="totp_device",
        on_delete=models.CASCADE,
    )
    secret = models.CharField("Segredo", max_length=64)
    confirmed = models.BooleanField("Confirmado", default=False)
    # Último passo de 30 s aceito: o mesmo código não vale duas vezes (replay).
    last_used_step = models.BigIntegerField("Último passo usado", null=True, blank=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    confirmed_at = models.DateTimeField("Confirmado em", null=True, blank=True)

    class Meta:
        verbose_name = "Segundo fator (TOTP)"
        verbose_name_plural = "Segundos fatores (TOTP)"

    def __str__(self) -> str:
        return f"2FA de {self.user_id} ({'ativo' if self.confirmed else 'pendente'})"


class RecoveryCode(models.Model):
    """Código de uso único para quem perdeu o celular. Guardado só como HMAC:
    o código em texto aparece uma vez, na tela em que é gerado."""

    user = models.ForeignKey(
        User,
        verbose_name="Usuário",
        related_name="recovery_codes",
        on_delete=models.CASCADE,
    )
    code_hash = models.CharField("Hash do código", max_length=64)
    used_at = models.DateTimeField("Usado em", null=True, blank=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Código de recuperação"
        verbose_name_plural = "Códigos de recuperação"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "code_hash"], name="uniq_recovery_code_per_user"
            )
        ]

    def __str__(self) -> str:
        return f"Código de recuperação de {self.user_id}"


class AccessRequestStatus(models.TextChoices):
    PENDENTE = "PENDENTE", "Pendente"
    APROVADA = "APROVADA", "Aprovada"
    RECUSADA = "RECUSADA", "Recusada"


class AccessRequest(models.Model):
    """Pedido de acesso feito por quem ainda não tem conta (tela pública).

    Não é um usuário: não tem senha, papel nem fazenda. O administrador decide
    — aprovar cria o `User` com papel e fazendas escolhidos por ele, recusar
    encerra o pedido. O pedido nunca é apagado: fica como registro de quem
    pediu, quando e quem decidiu.
    """

    full_name = models.CharField("Nome completo", max_length=150)
    email = models.EmailField("E-mail")
    phone = models.CharField("Telefone", max_length=20, blank=True)
    message = models.TextField("Quem é e por que precisa de acesso", max_length=1000)
    status = models.CharField(
        "Situação",
        max_length=10,
        choices=AccessRequestStatus.choices,
        default=AccessRequestStatus.PENDENTE,
        db_index=True,
    )
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField("Solicitado em", auto_now_add=True)

    decided_at = models.DateTimeField("Decidido em", null=True, blank=True)
    decided_by = models.ForeignKey(
        User,
        verbose_name="Decidido por",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    decision_reason = models.TextField("Motivo da decisão", blank=True)
    user = models.ForeignKey(
        User,
        verbose_name="Conta criada",
        related_name="access_requests",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    class Meta:
        verbose_name = "Solicitação de acesso"
        verbose_name_plural = "Solicitações de acesso"
        ordering = ["-created_at"]
        constraints = [
            # Quem insiste não entra na fila duas vezes: um pedido pendente por e-mail.
            models.UniqueConstraint(
                Lower("email"),
                condition=models.Q(status="PENDENTE"),
                name="uniq_pending_access_request_email",
            ),
            models.CheckConstraint(
                check=models.Q(status="PENDENTE", decided_at__isnull=True)
                | models.Q(~models.Q(status="PENDENTE"), decided_at__isnull=False),
                name="access_request_decision_matches_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"
