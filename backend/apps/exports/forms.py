"""Formulário do pedido. As **escolhas válidas dependem de quem pede**: um
conjunto que o papel não vê nem existe como opção (e, se alguém forjar o POST,
o serviço recusa de novo)."""

from django import forms

from apps.core import context as ctx
from apps.exports import catalog, services

_FORMATOS = [(chave, rotulo) for chave, rotulo, _ in services.FORMATOS]
_ESTILOS = [(chave, rotulo) for chave, rotulo, _ in services.ESTILOS_DO_CSV]


class ExportForm(forms.Form):
    conjuntos = forms.MultipleChoiceField(required=False, label="Dados do sistema")
    relatorios = forms.MultipleChoiceField(required=False, label="Relatórios prontos")
    formatos = forms.MultipleChoiceField(
        required=False,
        label="Formatos",
        choices=_FORMATOS,
        widget=forms.CheckboxSelectMultiple,
    )
    csv = forms.ChoiceField(
        label="Como gravar o CSV",
        choices=_ESTILOS,
        initial="br",
        widget=forms.RadioSelect,
    )
    fazenda = forms.ModelChoiceField(
        label="Fazenda",
        queryset=None,
        required=False,
        empty_label="Todas as fazendas do meu acesso",
    )
    safra = forms.ModelChoiceField(
        label="Safra", queryset=None, required=False, empty_label="Todas as safras"
    )
    de = forms.DateField(
        label="De", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    ate = forms.DateField(
        label="Até", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    incluir_excluidos = forms.BooleanField(
        label="Incluir registros excluídos",
        required=False,
        help_text="Eles saem marcados como excluídos, com o motivo. Sem isto, só o que está valendo.",
    )
    incluir_arquivos = forms.BooleanField(
        label="Incluir os arquivos anexos",
        required=False,
        help_text="As planilhas que você importou e os PDFs que foram gerados. Podem ser grandes.",
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["conjuntos"].choices = [
            (c.chave, c.titulo) for c in catalog.conjuntos_para(user)
        ]
        self.fields["relatorios"].choices = [
            (slug, titulo) for slug, titulo, _ in catalog.relatorios_para(user)
        ]
        self.fields["fazenda"].queryset = ctx.available_farms(user).order_by("name")
        self.fields["safra"].queryset = ctx.available_seasons(ctx.current_company())

    def pedido(self) -> dict:
        """Argumentos de `solicitar_exportacao`."""
        dados = self.cleaned_data
        return {
            "user": self.user,
            "conjuntos": dados["conjuntos"],
            "relatorios": dados["relatorios"],
            "formatos": dados["formatos"],
            "fazenda": dados["fazenda"],
            "safra": dados["safra"],
            "de": dados["de"],
            "ate": dados["ate"],
            "incluir_excluidos": dados["incluir_excluidos"],
            "incluir_arquivos": dados["incluir_arquivos"],
            "estilo_csv": dados["csv"],
        }
