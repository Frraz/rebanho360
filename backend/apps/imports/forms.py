"""Validação de entrada vinda da web.

As opções de cada importação são as escolhas que a planilha não traz:
fazenda, classe padrão, mapeamento de categorias e de destinos. Ficam
gravadas no `ImportBatch.options` — a importação é explicável depois.
"""

from django import forms

from apps.costs.models import CostClass
from apps.herd.models import WeighingReason
from apps.imports import readers
from apps.imports.importers.compras import SUGESTAO_BEZERROS, ImportadorDeCompras
from apps.imports.importers.movimentacoes import ImportadorDeMovimentacoes
from apps.imports.importers.pesagens import ImportadorDePesagens
from apps.imports.importers.vendas import PAPEIS_DE_COMPRADOR, ImportadorDeVendas
from apps.imports.models import ImportKind
from apps.livestock.models import AnimalCategory, Lot, LotStatus
from apps.organizations.models import Season
from apps.partners.models import Partner
from apps.properties.models import Farm


class UploadForm(forms.Form):
    kind = forms.ChoiceField(label="O que importar", choices=ImportKind.choices)
    file = forms.FileField(label="Planilha (.xlsx)")
    confirmar_reimportacao = forms.BooleanField(
        label="Já importei este arquivo e quero importar de novo mesmo assim",
        required=False,
    )


def _id(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


class OpcoesDeCustosForm(forms.Form):
    farm_id = forms.ModelChoiceField(
        label="Fazenda dos custos",
        queryset=Farm.objects.filter(is_active=True),
        help_text="A planilha de custos não tem coluna de fazenda: todos vão para a escolhida.",
    )
    default_cost_class_id = forms.ModelChoiceField(
        label="Classe para lançamentos sem classe na planilha",
        queryset=CostClass.objects.filter(is_active=True),
        required=False,
        help_text="156 lançamentos vêm sem classe. Sem escolher, eles ficam pendentes.",
    )
    default_description = forms.CharField(
        label="Descrição para lançamentos sem descrição (opcional)",
        required=False,
        max_length=200,
        help_text="Deixe em branco para revisar um a um.",
    )

    def __init__(self, *args, batch=None, **kwargs):
        initial = {
            "farm_id": batch.options.get("farm_id"),
            "default_cost_class_id": batch.options.get("default_cost_class_id"),
            "default_description": batch.options.get("default_description", ""),
        }
        super().__init__(*args, initial=initial, **kwargs)

    def opcoes(self) -> dict:
        d = self.cleaned_data
        return {
            "farm_id": d["farm_id"].pk,
            "default_cost_class_id": (
                d["default_cost_class_id"].pk if d["default_cost_class_id"] else None
            ),
            "default_description": d["default_description"],
        }


class OpcoesDeComprasForm(forms.Form):
    """Um campo por texto de categoria e de fazenda que a planilha usa."""

    def __init__(self, *args, batch=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch = batch
        importador = ImportadorDeCompras()
        categorias = AnimalCategory.objects.filter(is_active=True)
        fazendas = Farm.objects.filter(is_active=True)
        mapa_categorias = batch.options.get("category_map") or {}
        mapa_fazendas = batch.options.get("farm_map") or {}
        existentes_c = {readers.normalizar(c.name): c.pk for c in categorias}
        existentes_f = {readers.normalizar(f.name): f.pk for f in fazendas}

        self.textos_categoria = importador.textos_de_categoria(batch)
        self.textos_fazenda = importador.textos_de_fazenda(batch)
        for i, texto in enumerate(self.textos_categoria):
            norma = readers.normalizar(texto)
            inicial = mapa_categorias.get(norma) or existentes_c.get(norma)
            ajuda = ""
            if norma == "bezerros" and not mapa_categorias.get(norma):
                sugerida = next(
                    (c.pk for c in categorias if c.name == SUGESTAO_BEZERROS), None
                )
                inicial = inicial or sugerida
                ajuda = "Sugestão a confirmar com o produtor: BEZERROS = Machos Desm. até 12m."
            self.fields[f"cat_{i}"] = forms.ModelChoiceField(
                label=f'Categoria "{texto}" na planilha é…',
                queryset=categorias,
                initial=inicial,
                help_text=ajuda,
            )
        for i, texto in enumerate(self.textos_fazenda):
            norma = readers.normalizar(texto)
            self.fields[f"faz_{i}"] = forms.ModelChoiceField(
                label=f'Fazenda "{texto}" na planilha é…',
                queryset=fazendas,
                initial=mapa_fazendas.get(norma) or existentes_f.get(norma),
            )

    def opcoes(self) -> dict:
        d = self.cleaned_data
        return {
            "category_map": {
                readers.normalizar(t): d[f"cat_{i}"].pk
                for i, t in enumerate(self.textos_categoria)
            },
            "farm_map": {
                readers.normalizar(t): d[f"faz_{i}"].pk
                for i, t in enumerate(self.textos_fazenda)
            },
        }


class OpcoesDeMovimentacoesForm(forms.Form):
    season_id = forms.ModelChoiceField(
        label="Safra do saldo anterior",
        queryset=Season.objects.all(),
        help_text="O SALDO ANTERIOR do quadro-resumo de cada aba entra como saldo inicial, datado na abertura desta safra.",
    )

    def __init__(self, *args, batch=None, **kwargs):
        super().__init__(*args, **kwargs)
        importador = ImportadorDeMovimentacoes()
        self.fields["season_id"].initial = batch.options.get("season_id")
        fazendas = Farm.objects.filter(is_active=True)
        mapa_abas = batch.options.get("farm_map") or {}
        existentes = {readers.normalizar(f.name): f.pk for f in fazendas}

        self.abas = importador.abas(batch)
        for i, aba in enumerate(self.abas):
            norma = readers.normalizar(aba)
            self.fields[f"aba_{i}"] = forms.ModelChoiceField(
                label=f'Aba "{aba}" é a fazenda…',
                queryset=fazendas,
                initial=mapa_abas.get(norma) or existentes.get(norma),
            )

        mapa_destinos = batch.options.get("destinos") or {}
        self.destinos = importador.textos_de_destino(batch)
        acoes = [
            ("NAO", "Não vincular (fica só na observação)"),
            ("CRIAR", "Criar parceiro com este nome"),
            ("VINCULAR", "Vincular a um parceiro existente"),
        ]
        for i, (texto, quantidade) in enumerate(self.destinos):
            atual = mapa_destinos.get(readers.normalizar(texto)) or {}
            self.fields[f"dest_acao_{i}"] = forms.ChoiceField(
                label=f'Destino "{texto}" ({quantidade} linha{"s" if quantidade != 1 else ""})',
                choices=acoes,
                initial=atual.get("acao", "NAO"),
            )
            self.fields[f"dest_parceiro_{i}"] = forms.ModelChoiceField(
                label=f'Parceiro para "{texto}"',
                queryset=Partner.objects.filter(is_active=True),
                required=False,
                initial=atual.get("partner_id"),
            )

    def clean(self):
        dados = super().clean()
        for i, (texto, _) in enumerate(self.destinos):
            if dados.get(f"dest_acao_{i}") == "VINCULAR" and not dados.get(
                f"dest_parceiro_{i}"
            ):
                self.add_error(f"dest_parceiro_{i}", "Escolha o parceiro.")
        return dados

    def opcoes(self) -> dict:
        d = self.cleaned_data
        destinos = {}
        for i, (texto, _) in enumerate(self.destinos):
            acao = d[f"dest_acao_{i}"]
            decisao = {"acao": acao}
            if acao == "VINCULAR":
                decisao["partner_id"] = d[f"dest_parceiro_{i}"].pk
            destinos[readers.normalizar(texto)] = decisao
        return {
            "season_id": d["season_id"].pk,
            "farm_map": {
                readers.normalizar(aba): d[f"aba_{i}"].pk
                for i, aba in enumerate(self.abas)
            },
            "destinos": destinos,
        }


class OpcoesDeVendasForm(forms.Form):
    """Categoria, fazenda e comprador: o que a planilha escreve de um jeito
    e o cadastro de outro ("MACHOS 25 - 36" × "Machos 25 a 36 meses")."""

    def __init__(self, *args, batch=None, **kwargs):
        super().__init__(*args, **kwargs)
        importador = ImportadorDeVendas()
        categorias = AnimalCategory.objects.filter(is_active=True)
        fazendas = Farm.objects.filter(is_active=True)
        mapa_c = batch.options.get("category_map") or {}
        mapa_f = batch.options.get("farm_map") or {}
        mapa_p = batch.options.get("buyer_map") or {}
        existentes_c = {readers.normalizar(c.name): c.pk for c in categorias}
        existentes_f = {readers.normalizar(f.name): f.pk for f in fazendas}
        existentes_p = {
            readers.normalizar(p.name): p.pk
            for p in Partner.objects.filter(is_active=True)
        }

        self.textos_categoria = importador.textos_de_categoria(batch)
        self.textos_fazenda = importador.textos_de_fazenda(batch)
        self.textos_comprador = importador.textos_de_comprador(batch)

        for i, texto in enumerate(self.textos_categoria):
            norma = readers.normalizar(texto)
            self.fields[f"cat_{i}"] = forms.ModelChoiceField(
                label=f'Categoria "{texto}" na planilha é…',
                queryset=categorias,
                initial=mapa_c.get(norma) or existentes_c.get(norma),
            )
        for i, texto in enumerate(self.textos_fazenda):
            norma = readers.normalizar(texto)
            self.fields[f"faz_{i}"] = forms.ModelChoiceField(
                label=f'Fazenda "{texto}" na planilha é…',
                queryset=fazendas,
                required=False,
                initial=mapa_f.get(norma) or existentes_f.get(norma),
                help_text=(
                    "Só precisa quando uma venda cria uma saída nova. Se ela é "
                    "vinculada a uma saída já registrada, a fazenda vem da saída."
                ),
            )
        for i, texto in enumerate(self.textos_comprador):
            norma = readers.normalizar(texto)
            atual = mapa_p.get(norma) or {}
            self.fields[f"comp_{i}"] = forms.ModelChoiceField(
                label=f'Comprador "{texto}" é o parceiro…',
                queryset=Partner.objects.filter(is_active=True),
                required=False,
                empty_label="Criar um parceiro com este nome",
                initial=atual.get("partner_id") or existentes_p.get(norma),
            )
            self.fields[f"comp_papel_{i}"] = forms.ChoiceField(
                label=f'Papel de "{texto}" nesta venda',
                choices=PAPEIS_DE_COMPRADOR,
                initial=atual.get("role", "FRIGORIFICO"),
                help_text="Se o parceiro ainda não tem este papel, ele é acrescentado ao importar.",
            )

    def opcoes(self) -> dict:
        d = self.cleaned_data
        return {
            "category_map": {
                readers.normalizar(t): d[f"cat_{i}"].pk
                for i, t in enumerate(self.textos_categoria)
            },
            "farm_map": {
                readers.normalizar(t): d[f"faz_{i}"].pk
                for i, t in enumerate(self.textos_fazenda)
                if d.get(f"faz_{i}")
            },
            "buyer_map": {
                readers.normalizar(t): {
                    "partner_id": d[f"comp_{i}"].pk if d.get(f"comp_{i}") else None,
                    "role": d[f"comp_papel_{i}"],
                }
                for i, t in enumerate(self.textos_comprador)
            },
        }


class _LoteComFazenda(forms.ModelChoiceField):
    def label_from_instance(self, lote):
        return f"{lote.code} · {lote.farm.name}"


class OpcoesDePesagensForm(forms.Form):
    """A planilha não diz de qual lote é cada pesagem: lote e motivo de cada
    grupo (data + motivo) são decisão do usuário, com a sugestão do sistema
    já preenchida — que só vale depois de salvar."""

    def __init__(self, *args, batch=None, **kwargs):
        super().__init__(*args, **kwargs)
        importador = ImportadorDePesagens()
        lotes = Lot.objects.exclude(status=LotStatus.EXCLUIDO).select_related("farm")
        salvo = batch.options.get("grupos") or {}

        self.grupos = importador.grupos(batch)
        for i, grupo in enumerate(self.grupos):
            rotulo = importador.rotulo_do_grupo(grupo)
            sugestao = importador.sugestao_do_grupo(grupo)
            decisao = salvo.get(grupo["chave"]) or {}
            lote_inicial = decisao.get("lot_id") or (
                sugestao["lote"].pk if sugestao["lote"] else None
            )
            self.fields[f"g{i}_lot"] = _LoteComFazenda(
                label=f"Lote da pesagem de {rotulo}",
                queryset=lotes,
                initial=lote_inicial,
                help_text=(
                    f"Sugestão: {sugestao['lote'].code} — {sugestao['por_que']}."
                    if sugestao["lote"]
                    else "A planilha não diz de qual lote é esta pesagem."
                ),
            )
            self.fields[f"g{i}_reason"] = forms.ChoiceField(
                label=f"Motivo da pesagem de {rotulo}",
                choices=WeighingReason.choices,
                initial=decisao.get("reason") or sugestao["motivo"],
                help_text=(
                    f'Na planilha: "{grupo["motivo_texto"]}".'
                    if grupo["motivo_texto"]
                    else "A planilha não traz motivo para este bloco."
                ),
            )

    def opcoes(self) -> dict:
        d = self.cleaned_data
        return {
            "grupos": {
                grupo["chave"]: {
                    "lot_id": d[f"g{i}_lot"].pk,
                    "reason": d[f"g{i}_reason"],
                }
                for i, grupo in enumerate(self.grupos)
            }
        }


FORMS_DE_OPCOES = {
    ImportKind.CUSTOS: OpcoesDeCustosForm,
    ImportKind.COMPRAS: OpcoesDeComprasForm,
    ImportKind.MOVIMENTACOES: OpcoesDeMovimentacoesForm,
    ImportKind.VENDAS: OpcoesDeVendasForm,
    ImportKind.PESAGENS: OpcoesDePesagensForm,
}
