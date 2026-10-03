"""As seis classificações de carcaça e os tipos de tributo/taxa do legado
(`04_Conferencia_do_Acerto`).

A migração `0002` os semeia em todo banco novo; esta função garante o mesmo
em banco esvaziado por teste transacional. Idempotente — e **só cria o que
não existe**: nunca sobrescreve o que o usuário renomeou ou desativou.

As naturezas dos tipos são **provisórias** (pendência #21): dependem do
contador e do produtor, e mudam em Tipos de tributo e taxa, sem código.
"""

from apps.commercial.models import CarcassClass, TaxNature, TaxType

CLASSES = [
    ("MAGRO", "Magro", 1),
    ("AUSENTE", "Gordura ausente", 2),
    ("ESCASSA", "Gordura escassa", 3),
    ("MEDIANA", "Gordura mediana", 4),
    ("UNIFORME", "Gordura uniforme", 5),
    ("LESAO", "Lesão traumática", 6),
]

TIPOS = [
    ("Funrural", TaxNature.TRIBUTO),
    ("Fundepec", TaxNature.TAXA),
    ("GTA", TaxNature.TAXA),
    ("ICMS", TaxNature.TRIBUTO),
    ("Taxa de abate", TaxNature.TAXA),
    ("Indenização", TaxNature.TAXA),
    ("Idaterra", TaxNature.TAXA),
    ("Incentivo Precoce", TaxNature.CREDITO),
    ("Crédito GR-3", TaxNature.CREDITO),
    ("Desconto", TaxNature.DESCONTO),
    ("Adiantamento", TaxNature.ADIANTAMENTO),
]


def garantir_cadastros_comerciais() -> None:
    for codigo, nome, ordem in CLASSES:
        CarcassClass.objects.get_or_create(
            code=codigo, defaults={"name": nome, "display_order": ordem}
        )
    for ordem, (nome, natureza) in enumerate(TIPOS, start=1):
        TaxType.objects.get_or_create(
            name=nome, defaults={"nature": natureza, "display_order": ordem}
        )
