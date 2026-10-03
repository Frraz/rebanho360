"""Validação de entrada vinda da web."""

from django import forms

from apps.organizations.models import BusinessUnit, Company, Season


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "name",
            "legal_name",
            "tax_id",
            "address",
            "city",
            "state",
            "phone",
        ]
        widgets = {
            "state": forms.TextInput(attrs={"maxlength": 2, "class": "uppercase"}),
        }


class BusinessUnitForm(forms.ModelForm):
    class Meta:
        model = BusinessUnit
        fields = ["company", "name", "code"]


class SeasonForm(forms.ModelForm):
    class Meta:
        model = Season
        fields = ["company", "name", "start_date", "end_date"]
        widgets = {
            # `format` força ISO: sem ele, o DateInput usa o formato pt-br
            # (DD/MM/AAAA) para `value=`, que `<input type="date">` não
            # reconhece — o campo aparenta estar preenchido no HTML, mas o
            # navegador descarta e mostra vazio (achado ao verificar em
            # 360px com navegador real, F1-11).
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        company = cleaned.get("company")
        if start and end and end <= start:
            raise forms.ValidationError("A data final deve ser depois da inicial.")

        if start and end and company:
            sobrepostas = Season.objects.filter(
                company=company, start_date__lte=end, end_date__gte=start
            ).exclude(pk=self.instance.pk)
            if sobrepostas.exists():
                outra = sobrepostas.first()
                raise forms.ValidationError(
                    f"Período sobreposto à safra {outra.name} "
                    f"({outra.start_date:%d/%m/%Y} a {outra.end_date:%d/%m/%Y})."
                )
        return cleaned
