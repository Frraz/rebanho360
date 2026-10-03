"""Dashboard analítico (BI) — o painel de análise do Rebanho360.

Só **lê**. Cada módulo monta uma aba a partir dos serviços e seletores que o
resto do sistema já usa (regra 6: um indicador, um serviço); aqui só se agrega,
se compara e se transforma em gráfico. Nenhum derivado é gravado.

- `escopo.py`   — o recorte (usuário, safra, fazenda, data de corte) e a safra
                  anterior no mesmo ponto, para comparar
- `specs.py`    — o contrato com o navegador: gráfico, tabela, KPI, sparkline
- `abas.py`     — o registro das abas e quem vê cada uma
- `visao_geral.py`, `rebanho.py`, `compras.py`, `vendas.py`, `custos.py`,
  `financeiro.py`, `lotes.py`, `ciclo.py` — uma aba cada
- `insights.py` — as leituras automáticas ("o que merece atenção")

Docs: docs/regras-negocio/11-dashboard-analitico.md.
"""
