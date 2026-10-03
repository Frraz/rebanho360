"""Validação de entrada vinda da web."""

import re

from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts import user_management as usuarios
from apps.accounts.models import Role, User
from apps.core.validators import formatar_cpf, validar_cpf
from apps.properties.models import Farm

MASCARA_CPF = (
    "$el.value = $el.value.replace(/\\D/g, '').slice(0, 11)"
    ".replace(/(\\d{3})(\\d)/, '$1.$2').replace(/(\\d{3})(\\d)/, '$1.$2')"
    ".replace(/(\\d{3})(\\d{1,2})$/, '$1-$2')"
)
TELEFONE = re.compile(r"^[0-9+()\-\s.]{8,20}$")

NIVEL_SEM_ACESSO = ""
NIVEL_LEITURA = "leitura"
NIVEL_LANCAR = "lancar"
NIVEIS_DE_ACESSO = (
    (NIVEL_SEM_ACESSO, "Sem acesso"),
    (NIVEL_LEITURA, "Só consulta"),
    (NIVEL_LANCAR, "Consulta e lançamento"),
)


def _uma_linha(valor: str) -> str:
    return " ".join((valor or "").split())


def _telefone(valor: str) -> str:
    valor = _uma_linha(valor)
    if valor and not TELEFONE.match(valor):
        raise ValidationError("Informe só números, com DDD. Ex.: (63) 99999-0000.")
    return valor


def _validar_senhas(form, usuario_provisorio: User) -> None:
    """`senha` e `senha2` iguais e aceitas pelos validadores do projeto."""
    senha = form.cleaned_data.get("senha", "")
    senha2 = form.cleaned_data.get("senha2", "")
    if not senha:
        form.add_error("senha", "Informe a senha temporária.")
        return
    if senha != senha2:
        form.add_error("senha2", "As senhas não são iguais.")
        return
    try:
        password_validation.validate_password(senha, usuario_provisorio)
    except ValidationError as exc:
        form.add_error("senha", exc)


class ContaForm(forms.Form):
    """Perfil que o próprio usuário edita. Sem papel, e-mail, usuário nem situação."""

    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    phone = forms.CharField(label="Telefone", max_length=20, required=False)
    birth_date = forms.DateField(
        label="Data de nascimento",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    cpf = forms.CharField(
        label="CPF",
        max_length=14,
        required=False,
        help_text="Opcional. Só você e a auditoria (mascarado) o veem.",
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "off",
                "placeholder": "000.000.000-00",
                # Máscara enquanto digita; o servidor aceita com ou sem pontuação.
                "x-data": "{}",
                "@input": MASCARA_CPF,
            }
        ),
    )

    def __init__(self, *args, usuario: User, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        if not self.is_bound:
            self.initial = {
                "first_name": usuario.first_name,
                "last_name": usuario.last_name,
                "phone": usuario.phone,
                "birth_date": usuario.birth_date,
                "cpf": formatar_cpf(usuario.cpf),
            }

    def clean_first_name(self):
        nome = _uma_linha(self.cleaned_data["first_name"])
        if not nome:
            raise ValidationError("Informe o seu nome.")
        return nome

    def clean_last_name(self):
        return _uma_linha(self.cleaned_data["last_name"])

    def clean_phone(self):
        return _telefone(self.cleaned_data["phone"])

    def clean_birth_date(self):
        nascimento = self.cleaned_data["birth_date"]
        if nascimento is None:
            return None
        hoje = timezone.localdate()
        idade = (
            hoje.year
            - nascimento.year
            - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
        )
        if nascimento > hoje:
            raise ValidationError("A data de nascimento não pode ser no futuro.")
        if idade < 14 or idade > 100:
            raise ValidationError("Confira a data: a idade informada não é plausível.")
        return nascimento

    def clean_cpf(self):
        return validar_cpf(self.cleaned_data["cpf"])


class MotivoForm(forms.Form):
    motivo = forms.CharField(
        label="Motivo",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Fica registrado na auditoria, com seu nome e a data.",
    )

    def clean_motivo(self):
        motivo = (self.cleaned_data["motivo"] or "").strip()
        if not motivo:
            raise ValidationError("Informe o motivo.")
        return motivo


class UsuarioForm(forms.Form):
    """Criar, editar ou aprovar uma solicitação (`modo`). O e-mail da
    aprovação não é campo: vem do pedido, porque é para ele que o link vai."""

    MODOS = ("criar", "editar", "aprovar")

    username = forms.CharField(
        label="Usuário (para entrar)",
        max_length=150,
        help_text="Letras, números e . _ - @ +. Não muda depois.",
    )
    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    email = forms.EmailField(
        label="E-mail",
        required=False,
        help_text="Para o convite e para redefinir a senha. Pode ficar em branco "
        "para quem não usa e-mail — aí a senha é temporária.",
    )
    phone = forms.CharField(label="Telefone", max_length=20, required=False)
    role = forms.ChoiceField(label="Papel", choices=Role.choices)

    senha_modo = forms.ChoiceField(
        label="Primeiro acesso",
        choices=(
            ("convite", "Enviar convite por e-mail — a pessoa define a própria senha"),
            ("temporaria", "Definir uma senha temporária — a pessoa troca ao entrar"),
        ),
        widget=forms.RadioSelect,
        initial="convite",
    )
    senha = forms.CharField(
        label="Senha temporária",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    senha2 = forms.CharField(
        label="Repita a senha temporária",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    motivo = forms.CharField(
        label="Motivo da alteração",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Fica registrado na auditoria, com seu nome e a data.",
    )

    def __init__(
        self, *args, modo="criar", usuario=None, solicitacao=None, proprio=False, **kw
    ):
        assert modo in self.MODOS
        super().__init__(*args, **kw)
        self.modo = modo
        self.usuario = usuario
        # Editando a própria conta: o escopo e o papel não se mexem (o serviço
        # ignora), então a regra "ao menos uma fazenda" não se aplica.
        self.proprio = proprio
        self.solicitacao = solicitacao
        self.farms = list(Farm.objects.filter(is_active=True).order_by("name"))

        if modo != "criar":
            for campo in ("senha_modo", "senha", "senha2"):
                del self.fields[campo]
        if modo != "editar":
            del self.fields["motivo"]
        if modo == "editar":
            del self.fields["username"]
        if modo == "aprovar":
            del self.fields["email"]
            partes = solicitacao.full_name.split()
            self.fields["username"].initial = self._sugerir_username(solicitacao.email)
            self.fields["first_name"].initial = partes[0] if partes else ""
            self.fields["last_name"].initial = " ".join(partes[1:])
            self.fields["phone"].initial = solicitacao.phone
        if modo == "editar" and not self.is_bound:
            for campo in ("first_name", "last_name", "email", "phone", "role"):
                self.fields[campo].initial = getattr(usuario, campo)

    @staticmethod
    def _sugerir_username(email: str) -> str:
        base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower()) or "usuario"
        candidato, n = base, 1
        while usuarios.usuario_em_uso(candidato):
            n += 1
            candidato = f"{base}{n}"
        return candidato[:150]

    # ---- fazendas: um seletor por fazenda ----

    @property
    def farm_rows(self):
        """Uma linha por fazenda ativa, com o nível escolhido: do formulário
        enviado, ou do que o usuário já tem."""
        atuais = {}
        if self.usuario is not None:
            atuais = {a.farm_id: a.can_write for a in self.usuario.farm_access.all()}
        linhas = []
        for farm in self.farms:
            nome = f"farm_{farm.pk}"
            if self.is_bound:
                valor = self.data.get(nome, NIVEL_SEM_ACESSO)
            elif farm.pk in atuais:
                valor = NIVEL_LANCAR if atuais[farm.pk] else NIVEL_LEITURA
            else:
                valor = NIVEL_SEM_ACESSO
            linhas.append(
                {"farm": farm, "name": nome, "value": valor, "levels": NIVEIS_DE_ACESSO}
            )
        return linhas

    # ---- validação ----

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        for validador in User._meta.get_field("username").validators:
            validador(username)
        if usuarios.usuario_em_uso(username):
            raise ValidationError("Este usuário já existe. Escolha outro.")
        return username

    def clean_first_name(self):
        return _uma_linha(self.cleaned_data["first_name"])

    def clean_last_name(self):
        return _uma_linha(self.cleaned_data["last_name"])

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        exceto = self.usuario.pk if self.usuario is not None else None
        if usuarios.email_em_uso(email, exceto_pk=exceto):
            raise ValidationError("Já existe uma conta com este e-mail.")
        return email

    def clean_phone(self):
        return _telefone(self.cleaned_data["phone"])

    def clean(self):
        dados = super().clean()
        papel = dados.get("role")

        acessos = {}
        for linha in self.farm_rows:
            valor = linha["value"]
            if valor not in {n for n, _ in NIVEIS_DE_ACESSO}:
                self.add_error(None, "Nível de acesso inválido.")
                break
            if valor != NIVEL_SEM_ACESSO:
                acessos[linha["farm"]] = valor == NIVEL_LANCAR
        dados["acessos"] = acessos
        amplo = papel in {Role.ADMIN, Role.GESTOR}
        if papel and not amplo and not acessos and self.farms and not self.proprio:
            self.add_error(
                None,
                "Marque ao menos uma fazenda: este papel só enxerga as fazendas "
                "que receber. (Administrador e Gestor veem todas.)",
            )

        if self.modo == "criar":
            if dados.get("senha_modo") == "temporaria":
                provisorio = User(
                    username=dados.get("username", ""),
                    first_name=dados.get("first_name", ""),
                    email=dados.get("email", ""),
                )
                _validar_senhas(self, provisorio)
            elif not dados.get("email") and "email" not in self.errors:
                self.add_error(
                    "email",
                    "Informe o e-mail para enviar o convite, ou escolha a senha "
                    "temporária.",
                )
        return dados


class RedefinirSenhaForm(forms.Form):
    modo = forms.ChoiceField(
        label="Como redefinir",
        choices=(
            ("link", "Enviar um link por e-mail — a pessoa define a nova senha"),
            ("temporaria", "Definir uma senha temporária — a pessoa troca ao entrar"),
        ),
        widget=forms.RadioSelect,
        initial="link",
    )
    senha = forms.CharField(
        label="Senha temporária",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    senha2 = forms.CharField(
        label="Repita a senha temporária",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    motivo = forms.CharField(
        label="Motivo",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Fica registrado na auditoria, com seu nome e a data.",
    )

    def __init__(self, *args, usuario, **kw):
        super().__init__(*args, **kw)
        self.usuario = usuario

    def clean_motivo(self):
        motivo = (self.cleaned_data["motivo"] or "").strip()
        if not motivo:
            raise ValidationError("Informe o motivo.")
        return motivo

    def clean(self):
        dados = super().clean()
        if dados.get("modo") == "temporaria":
            _validar_senhas(self, self.usuario)
        elif dados.get("modo") == "link" and not self.usuario.email:
            self.add_error(
                "modo",
                "Este usuário não tem e-mail. Cadastre um na edição ou defina "
                "uma senha temporária.",
            )
        return dados


class RecusarSolicitacaoForm(MotivoForm):
    motivo = forms.CharField(
        label="Motivo da recusa",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Anotação interna, na auditoria. Não vai no e-mail ao solicitante.",
    )
    avisar = forms.BooleanField(
        label="Avisar o solicitante por e-mail (sem o motivo)",
        required=False,
        initial=True,
    )


class SolicitacaoAcessoForm(forms.Form):
    """Tela pública. `website` é a isca para robôs: invisível para gente."""

    full_name = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(label="E-mail", max_length=254)
    phone = forms.CharField(label="Telefone (opcional)", max_length=20, required=False)
    message = forms.CharField(
        label="Quem é você e por que precisa de acesso?",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Ex.: sou encarregado da Fazenda Santa Rita e vou lançar as pesagens.",
    )
    website = forms.CharField(required=False, widget=forms.TextInput)

    def clean_full_name(self):
        nome = _uma_linha(self.cleaned_data["full_name"])
        if len(nome.split()) < 2:
            raise ValidationError("Informe nome e sobrenome.")
        return nome

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        return _telefone(self.cleaned_data["phone"])

    def clean_message(self):
        mensagem = (self.cleaned_data["message"] or "").strip()
        if len(mensagem) < 10:
            raise ValidationError("Conte em uma frase quem você é e o que vai fazer.")
        return mensagem

    @property
    def parece_robo(self) -> bool:
        return bool(self.cleaned_data.get("website"))
