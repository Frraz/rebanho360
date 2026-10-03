# Fontes do projeto

Material original que deu origem ao Rebanho360. **Esta pasta não é versionada** (só este arquivo): contém planilhas reais da fazenda, relatórios de um frigorífico e a transcrição de um áudio. Fica apenas no disco de quem desenvolve.

Os arquivos esperados estão descritos em [`../README.md`](../README.md#fontes) e em [`../00-visao-geral.md`](../00-visao-geral.md#as-três-fontes-do-projeto).

## Num clone novo

Sem estes arquivos o sistema funciona normalmente; o que muda:

- ~47 testes de importação **pulam** (`backend/apps/imports/tests/conftest.py`) por não achar `planilhas/CONTROLE PASTO*.xlsx`;
- os links para estes arquivos, nos outros documentos, ficam quebrados no GitHub.

Para rodá-los, copie os arquivos para cá, mantendo a estrutura:

```
docs/fontes/
├── planilhas/CONTROLE PASTO …xlsx
├── planilhas/REPORTAGEM IVAN.xlsx
├── relatorios-legado/*.png
├── Sistema_Gestao_Pasto_Compra_Gado_Estrutura_Funcional.md
├── imagem.jpeg
├── audio.txt
└── referencia/
```
