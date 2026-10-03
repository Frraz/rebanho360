"""As 2 classes e os 11 centros de custo reais (docs/regras-negocio/02).

A migração `0004` os semeia em todo banco novo; esta função garante o mesmo
em um banco que já os perdeu (ex.: `seed_demo` rodado em banco de testes
esvaziado). Idempotente. A lista da migração é uma cópia congelada — migração
não importa código vivo.
"""

from apps.costs.models import CostCenter, CostClass

CLASSES = ["CUSTEIO", "INVESTIMENTO"]

CENTROS = [
    "FUNCIONARIO",
    "PARQUE DE MÁQUINAS",
    "DESPESA GADO",
    "INFRAESTRUTURA",
    "OUTROS",
    "NUTRIÇÃO",
    "PASTAGEM",
    "IMPOSTO E TAXAS",
    "COMISSÃO",
    "SANIDADE",
    "FERPAM",
    # Centro próprio do frete (cliente, 2026-10-03): separa o custo dos animais,
    # o do frete e os demais custos da operação.
    "FRETE",
]


def garantir_classes_e_centros() -> None:
    for nome in CLASSES:
        CostClass.objects.get_or_create(name=nome)
    for nome in CENTROS:
        CostCenter.objects.get_or_create(name=nome)
