"""`float` nunca em `models.py`/`services.py` — ADR 0005. Dinheiro, peso,
arroba e percentual são sempre `Decimal`; um `float()` acidental no meio de
uma cadeia de cálculo contamina o resultado em silêncio.

Roda como teste (não só como lint) para que a regra valha em qualquer CI,
mesmo sem um plugin de lint dedicado — ruff não suporta regras arbitrárias
por nome de arquivo sem um plugin próprio.
"""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
ALLOWLIST_MARKER = "# float-ok"


def _arquivos_sensiveis():
    for padrao in ("models.py", "services.py"):
        yield from BACKEND_DIR.glob(f"apps/*/{padrao}")


class TestSemFloatEmCodigoDeCalculo:
    def test_nenhum_arquivo_sensivel_usa_float(self):
        ofensores = []
        for arquivo in _arquivos_sensiveis():
            texto = arquivo.read_text(encoding="utf-8")
            for numero, linha in enumerate(texto.splitlines(), start=1):
                if "float(" in linha and ALLOWLIST_MARKER not in linha:
                    ofensores.append(f"{arquivo.relative_to(BACKEND_DIR)}:{numero}")

        assert (
            not ofensores
        ), "float() encontrado em models.py/services.py (ADR 0005): " + ", ".join(
            ofensores
        )
