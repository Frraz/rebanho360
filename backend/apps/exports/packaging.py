"""O pacote final: um arquivo só, ou um ZIP com tudo e o manifesto.

O ZIP leva, além dos dados:

- `LEIA-ME.txt` — em português, como ler o que está ali (para quem abrir daqui
  a um ano, sem o sistema na frente);
- `manifesto.json` — cada arquivo com tamanho e SHA-256, o dicionário de
  colunas de cada conjunto, os filtros e os avisos. É o que permite provar
  que o arquivo não mudou e reimportar com segurança.
"""

import hashlib
import json
import zipfile
from pathlib import Path

from apps.exports.writers import TIPOS, VERSAO_DO_FORMATO, Arquivo

#: Já são comprimidos: gastar CPU deflatando PDF e planilha só aumenta o tempo.
SEM_COMPRESSAO = {".pdf", ".xlsx", ".zip"}


def sha256_do_arquivo(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def montar_leia_me(meta: dict, conjuntos: list[dict], relatorios: list[dict]) -> str:
    linhas = [
        "REBANHO360 — EXPORTAÇÃO DE DADOS",
        "=" * 34,
        f"Gerada em {meta['gerado_em_texto']} por {meta['gerado_por']}.",
        "Filtros: " + " · ".join(meta["filtros"]),
        "",
        "O QUE TEM AQUI",
        "--------------",
        "csv/         Um arquivo CSV por conjunto de dados. Abre direto no Excel",
        "             (separador ';', vírgula decimal, datas dd/mm/aaaa) — ou, se você",
        "             escolheu o padrão internacional, separador ',', ponto decimal e",
        "             datas aaaa-mm-dd.",
        "xlsx/        Uma planilha com uma aba por conjunto (e uma aba Resumo).",
        "json/        Um arquivo JSON por conjunto, com os valores exatos do banco,",
        "             descrevendo as próprias colunas. É o melhor formato para",
        "             reimportar ou processar por programa.",
        "pdf/         Para ler e imprimir. Mostra só as colunas principais.",
        "relatorios/  Relatórios prontos, com os mesmos números da tela.",
        "arquivos/    Planilhas que foram importadas e PDFs que foram gerados.",
        "manifesto.json  Lista cada arquivo com tamanho e SHA-256, e descreve as",
        "             colunas de cada conjunto.",
        "",
        "COMO LER OS DADOS",
        "-----------------",
        "* Toda tabela tem a coluna ID. Uma coluna 'Lote (ID)' guarda o ID do lote",
        "  na tabela de lotes: é assim que se religam as tabelas.",
        "* Campo vazio é informação que não existe. Não é zero.",
        "* Valores em dinheiro, peso e arroba guardam todas as casas decimais do",
        "  sistema; nada foi arredondado para a exportação.",
        "* O saldo do rebanho não é um campo: é a SOMA da coluna Quantidade de",
        "  'Razão do rebanho (linhas)'. Transferência tem duas linhas (uma",
        "  negativa na origem, uma positiva no destino) e soma zero.",
        "* Correções no razão aparecem como linhas de compensação, com a data do",
        "  fato original: nada é apagado, tudo foi corrigido para trás.",
        "* "
        + (
            "Registros excluídos ESTÃO incluídos (a coluna Situação diz EXCLUÍDA)."
            if meta["incluir_excluidos"]
            else "Registros excluídos NÃO estão incluídos."
        ),
        "* Indicadores como peso médio, custo por arroba e margem não são",
        "  gravados no sistema, são calculados. Para tê-los prontos, exporte os",
        "  relatórios (pasta relatorios/).",
        "* Os conjuntos foram lidos um depois do outro, não num instante único.",
        "  Se alguém lançou algo durante a exportação, um conjunto pode ter",
        "  esse lançamento e outro não. Para uma cópia completa e exata do banco,",
        "  use o backup do servidor (deploy/backup.sh).",
        "",
        "CONJUNTOS DE DADOS",
        "------------------",
    ]
    for c in conjuntos:
        linhas.append(f"* {c['rotulo']}: {c['registros']} registro(s)")
    if relatorios:
        linhas += ["", "RELATÓRIOS", "----------"]
        linhas += [f"* {r['rotulo']}" for r in relatorios]
    if meta["avisos"]:
        linhas += ["", "AVISOS", "------"]
        linhas += [f"* {a}" for a in meta["avisos"]]
    return "\n".join(linhas) + "\n"


def montar_manifesto(
    meta: dict, conjuntos: list[dict], relatorios: list[dict], arquivos: list[dict]
) -> str:
    corpo = {
        "sistema": "Rebanho360",
        "formato": VERSAO_DO_FORMATO,
        "gerado_em": meta["gerado_em"],
        "gerado_por": meta["gerado_por"],
        "filtros": meta["filtros"],
        "opcoes": meta["opcoes"],
        "conjuntos": conjuntos,
        "relatorios": relatorios,
        "arquivos": arquivos,
        "avisos": meta["avisos"],
    }
    return json.dumps(corpo, ensure_ascii=False, indent=1)


def empacotar(
    pasta: Path,
    arquivos: list[Arquivo],
    anexos: list[tuple[str, object]],
    *,
    meta: dict,
    conjuntos: list[dict],
    relatorios: list[dict],
    nome_base: str,
    ao_arquivo=None,
    ao_anexo=None,
) -> tuple[Path, str, str, list[str]]:
    """Devolve `(caminho, nome para baixar, tipo, avisos)`.

    Um arquivo só e sem anexos: entrega o próprio arquivo (quem pediu "os lotes
    em Excel" espera um `.xlsx`, não um ZIP com um `.xlsx` dentro). Mais que
    isso: ZIP. Anexo (`arcname`, `FieldFile`) é copiado do armazenamento para
    dentro do ZIP; o que sumiu do disco vira aviso, não falha."""
    if len(arquivos) == 1 and not anexos:
        unico = arquivos[0]
        extensao = unico.caminho.suffix
        return unico.caminho, f"{nome_base}{extensao}", unico.tipo, []

    avisos: list[str] = []
    saida = pasta / "pacote.zip"
    entradas: list[dict] = []
    with zipfile.ZipFile(
        saida, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as zf:
        for arquivo in arquivos:
            compressao = (
                zipfile.ZIP_STORED
                if arquivo.caminho.suffix in SEM_COMPRESSAO
                else zipfile.ZIP_DEFLATED
            )
            zf.write(arquivo.caminho, arquivo.nome, compress_type=compressao)
            entradas.append(
                {
                    "caminho": arquivo.nome,
                    "bytes": arquivo.caminho.stat().st_size,
                    "sha256": sha256_do_arquivo(arquivo.caminho),
                    "registros": arquivo.registros,
                    "descricao": arquivo.rotulo,
                }
            )
            if ao_arquivo:
                ao_arquivo()
        for arcname, campo in anexos:
            try:
                resumo = hashlib.sha256()
                tamanho = 0
                with (
                    campo.open("rb") as origem,
                    zf.open(arcname, "w", force_zip64=True) as destino,
                ):
                    for bloco in iter(lambda: origem.read(1024 * 1024), b""):
                        resumo.update(bloco)
                        tamanho += len(bloco)
                        destino.write(bloco)
                entradas.append(
                    {
                        "caminho": arcname,
                        "bytes": tamanho,
                        "sha256": resumo.hexdigest(),
                        "registros": None,
                        "descricao": "Arquivo anexo",
                    }
                )
            except (FileNotFoundError, OSError):
                avisos.append(
                    f"O arquivo {arcname.rsplit('/', 1)[-1]} não está mais no "
                    "servidor e ficou de fora."
                )
            if ao_anexo:
                ao_anexo()
        meta = {**meta, "avisos": [*meta["avisos"], *avisos]}
        zf.writestr("LEIA-ME.txt", montar_leia_me(meta, conjuntos, relatorios))
        zf.writestr(
            "manifesto.json", montar_manifesto(meta, conjuntos, relatorios, entradas)
        )
    return saida, f"{nome_base}.zip", TIPOS["zip"], avisos
