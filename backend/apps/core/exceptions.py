"""Exceções de negócio, distintas de erro de validação ou de permissão."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Bloqueio:
    """Um motivo que impede editar/excluir agora — e o caminho para sair dele.

    `registro.bloqueios()` pode devolver `str` ou `Bloqueio`; este se comporta
    como texto (`str()`), e a tela de impacto mostra o link quando há `url`.
    É o "desfaça antes a baixa do pagamento", com o botão que leva até lá
    (docs/ux/01#análise-de-impacto, F4-05).
    """

    texto: str
    url: str = ""
    rotulo_url: str = ""

    def __str__(self) -> str:
        return self.texto


class BusinessError(Exception):
    """Erro de regra de negócio, com mensagem específica para o usuário.

    Nunca um "algo deu errado" genérico — ver docs/seguranca/01-seguranca.md.
    Exemplo: "Saldo insuficiente: há 12 cabeças de Machos 13 a 24 meses
    no Baixão, foram informadas 20."
    """


class DependencyError(BusinessError):
    """Levantada ao excluir/editar um registro que tem dependentes.

    Carrega a lista de dependentes para a view virar tela de análise
    de impacto, nunca um "tem certeza?" genérico.
    """

    def __init__(self, dependents: list, message: str | None = None):
        self.dependents = dependents
        super().__init__(message or "Este registro tem dependências.")


class BlockingDependencyError(BusinessError):
    """Levantada quando a dependência é bloqueante e não admite cascata.

    Ex.: pagamento já baixado, safra encerrada, saldo ficaria negativo.
    A mensagem sempre explica o caminho, nunca só recusa.
    """
