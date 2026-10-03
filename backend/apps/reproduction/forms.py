from django import forms

from apps.core import context as ctx
from apps.organizations.models import Season
from apps.properties.models import Farm
from apps.reproduction.models import BreedingCycle


def _n(rotulo, **extra):
    return forms.IntegerField(
        label=rotulo,
        required=False,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
        **extra,
    )


class BreedingCycleForm(forms.Form):
    farm = forms.ModelChoiceField(label="Fazenda", queryset=Farm.objects.none())
    season = forms.ModelChoiceField(
        label="Safra de nascimento", queryset=Season.objects.none()
    )
    breeding_months = forms.IntegerField(
        label="Tempo de estação (meses)",
        required=False,
        min_value=1,
        max_value=12,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    females_total = _n("Total de fêmeas no rebanho")
    females_over_18m = _n("Fêmeas acima de 18 meses")
    heifers_exposed = _n("Novilhas em monta")
    heifers_pregnant = _n("Novilhas prenhes")
    challenge_heifers_exposed = _n("Novilhas desafio em monta")
    challenge_heifers_pregnant = _n("Novilhas desafio prenhes")
    primiparous_exposed = _n("Primíparas em monta")
    primiparous_pregnant = _n("Primíparas prenhes")
    cows_exposed = _n("Vacas em monta")
    cows_pregnant = _n("Vacas prenhes")
    inseminated = _n("Fêmeas inseminadas (IA/IATF)")
    pregnant_by_ai = _n("Prenhes por IA/IATF")
    pregnant_by_bull = _n("Prenhes por touro")
    weaned_calves = _n("Bezerros desmamados")
    notes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = (
            ctx.available_farms(user) if user else Farm.objects.none()
        )
        self.fields["season"].queryset = Season.objects.order_by("-start_date")


class BreedingCycleEditForm(BreedingCycleForm):
    edit_reason = forms.CharField(
        label="Motivo da correção",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Por que este ciclo está sendo corrigido. Fica na auditoria.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Fazenda e safra identificam o ciclo: não mudam na correção.
        for campo in ("farm", "season"):
            self.fields[campo].disabled = True


def iniciais_do_ciclo(ciclo: BreedingCycle) -> dict:
    campos = [f for f in BreedingCycleForm.base_fields if f not in ("farm", "season")]
    return {
        "farm": ciclo.farm_id,
        "season": ciclo.season_id,
        **{campo: getattr(ciclo, campo) for campo in campos},
    }
