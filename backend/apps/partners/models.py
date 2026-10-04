from django.db import models


class Partner(models.Model):
    """Parceiro multi-papel: fornecedor, comprador, frigorífico, transportador
    etc. Nunca duplicar a pessoa porque ela exerce mais de um papel — ver
    docs/modelo-dados/01-entidades.md#pessoas-e-acesso."""

    name = models.CharField("Nome", max_length=150)
    legal_name = models.CharField("Razão social", max_length=200, blank=True)
    trade_name = models.CharField("Nome fantasia", max_length=150, blank=True)
    document = models.CharField("CPF/CNPJ", max_length=18, blank=True)
    address = models.CharField("Endereço", max_length=200, blank=True)
    city = models.CharField("Cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    phone = models.CharField("Telefone", max_length=20, blank=True)
    email = models.EmailField("E-mail", blank=True)
    notes = models.TextField("Observações", blank=True)
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Parceiro"
        verbose_name_plural = "Parceiros"
        ordering = ["name"]
        # A busca por nome tem índice trigram em `UPPER(name)`, criado por SQL na
        # migração (o Django 5.0 não monta índice de expressão com classe de
        # operador).
        indexes = [models.Index(fields=["document"])]

    def __str__(self) -> str:
        return self.name


class PartnerRoleChoice(models.TextChoices):
    PRODUTOR = "PRODUTOR", "Produtor"
    FORNECEDOR = "FORNECEDOR", "Fornecedor"
    COMPRADOR = "COMPRADOR", "Comprador"
    FRIGORIFICO = "FRIGORIFICO", "Frigorífico"
    TRANSPORTADOR = "TRANSPORTADOR", "Transportador"
    MOTORISTA = "MOTORISTA", "Motorista"
    COMISSIONADO = "COMISSIONADO", "Comissionado"
    FAVORECIDO = "FAVORECIDO", "Favorecido"
    PECUARISTA = "PECUARISTA", "Pecuarista"


class PartnerRole(models.Model):
    """Papel exercido por um parceiro. Um parceiro, vários papéis — nunca
    duplicar o cadastro porque a pessoa compra e vende."""

    partner = models.ForeignKey(
        Partner, verbose_name="Parceiro", related_name="roles", on_delete=models.CASCADE
    )
    role = models.CharField("Papel", max_length=20, choices=PartnerRoleChoice.choices)

    class Meta:
        verbose_name = "Papel do parceiro"
        verbose_name_plural = "Papéis do parceiro"
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "role"], name="uniq_partner_role"
            )
        ]

    def __str__(self) -> str:
        return f"{self.partner} · {self.get_role_display()}"


class BankAccountType(models.TextChoices):
    CORRENTE = "CORRENTE", "Conta corrente"
    POUPANCA = "POUPANCA", "Conta poupança"


class BankAccount(models.Model):
    """Conta bancária do parceiro. Dado sensível: nunca em log; alterar
    aqui é evento de auditoria de severidade alta
    (docs/regras-negocio/06-edicao-exclusao-e-auditoria.md#o-que-auditar-sempre)."""

    partner = models.ForeignKey(
        Partner,
        verbose_name="Parceiro",
        related_name="bank_accounts",
        on_delete=models.CASCADE,
    )
    bank_code = models.CharField("Código do banco", max_length=10, blank=True)
    bank_name = models.CharField("Banco", max_length=100, blank=True)
    branch = models.CharField("Agência", max_length=20, blank=True)
    account = models.CharField("Conta", max_length=30, blank=True)
    account_type = models.CharField(
        "Tipo de conta",
        max_length=10,
        choices=BankAccountType.choices,
        default=BankAccountType.CORRENTE,
    )
    pix_key = models.CharField("Chave Pix", max_length=140, blank=True)
    is_default = models.BooleanField("Conta padrão", default=False)

    class Meta:
        verbose_name = "Conta bancária"
        verbose_name_plural = "Contas bancárias"
        constraints = [
            models.UniqueConstraint(
                fields=["partner"],
                condition=models.Q(is_default=True),
                name="uniq_default_bank_account_per_partner",
            )
        ]

    def __str__(self) -> str:
        return f"{self.partner} · {self.bank_name or self.bank_code} {self.account}"
