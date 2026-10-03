"""Análise de impacto: o que excluir/editar um registro vai desfazer, e o
que depende dele — mostrada **antes** de executar, nunca um "Tem certeza?"
genérico. Ver docs/regras-negocio/06#análise-de-impacto.
"""

from dataclasses import dataclass, field

from apps.core.reversible import Status


@dataclass
class Impacto:
    efeitos: list[str] = field(default_factory=list)
    dependentes: list = field(default_factory=list)
    bloqueios: list[str] = field(default_factory=list)

    @property
    def bloqueado(self) -> bool:
        return bool(self.bloqueios)

    @property
    def exige_cascata(self) -> bool:
        return bool(self.dependentes)

    @property
    def rotulos_dependentes(self) -> list[str]:
        return [rotulo(dep) for dep in self.dependentes]


def rotulo(registro) -> str:
    return f"{registro._meta.verbose_name} {registro}"


def analisar_impacto(registro) -> Impacto:
    """Três desfechos possíveis (06#análise-de-impacto): sem dependência
    (executa direto), com dependência reversível (cascata explícita) ou com
    bloqueio (recusa explicando o caminho)."""
    efeitos = (
        registro.descrever_efeitos() if registro.status == Status.CONFIRMADA else []
    )
    return Impacto(
        efeitos=efeitos,
        dependentes=list(registro.dependentes()),
        bloqueios=registro.bloqueios(),
    )
