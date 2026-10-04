"""Layout das tabelas do PDF de relatório.

Relatório com muitas colunas estourava a página: o WeasyPrint não encolhe uma
tabela abaixo da soma das larguras mínimas das colunas, e a última saía cortada
pela margem. Daqui sai, para cada tabela, uma densidade (tamanho da letra e do
espaçamento pelo número de colunas) e larguras proporcionais ao conteúdo, para
a tabela caber sempre na página e o texto longo quebrar em linhas.
"""

from __future__ import annotations

#: Acima disto, letra menor e colunas de largura fixa.
COLUNAS_DENSA = 9
COLUNAS_MUITO_DENSA = 12

#: Peso mínimo e máximo de uma coluna, em caracteres: coluna de texto longo
#: quebra em várias linhas em vez de roubar a largura das demais.
PESO_MINIMO = 5
PESO_MAXIMO = 26


def densidade(colunas: int) -> str:
    if colunas > COLUNAS_MUITO_DENSA:
        return "muito-densa"
    if colunas > COLUNAS_DENSA:
        return "densa"
    return ""


def _peso(rotulo: str, valores) -> int:
    maior_palavra = max((len(p) for p in str(rotulo).split()), default=0) + 1
    maior_valor = max((len(str(v)) for v in valores), default=0)
    return min(max(maior_valor, maior_palavra, PESO_MINIMO), PESO_MAXIMO)


def larguras_percentuais(tabela: dict) -> list[float]:
    """Largura de cada coluna, em %, proporcional ao maior conteúdo dela."""
    cabecalho = tabela["cabecalho"]
    linhas = tabela["celulas"]
    pesos = [
        _peso(rotulo, (linha[i][0] for linha in linhas))
        for i, rotulo in enumerate(cabecalho)
    ]
    total = sum(pesos) or 1
    return [round(100 * p / total, 2) for p in pesos]


def preparar_tabela(tabela: dict) -> dict:
    """A tabela de `para_tela` com `densidade` e `larguras` para o PDF."""
    nivel = densidade(len(tabela["cabecalho"]))
    return {
        **tabela,
        "densidade": nivel,
        "larguras": larguras_percentuais(tabela) if nivel else [],
    }


def densidade_do_documento(tabelas: list[dict]) -> str:
    """A mais densa entre as tabelas: define a margem lateral da página."""
    niveis = [t["densidade"] for t in tabelas]
    for nivel in ("muito-densa", "densa"):
        if nivel in niveis:
            return nivel
    return ""
