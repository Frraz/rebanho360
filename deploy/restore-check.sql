-- Conferência pós-restauração (passo 3 de deploy/restore-log.md).
-- Só lê: pode rodar em qualquer banco restaurado, sem alterar nada.
--
--   docker exec -i rebanho360_restore_test psql -U rebanho360 -d rebanho360 \
--     < deploy/restore-check.sql
--
-- Compare os números com os do banco de produção no mesmo dia (rode este
-- mesmo arquivo lá, com `docker exec -i rebanho360_db ...`) e anote em
-- deploy/restore-log.md. O saldo do rebanho é a SOMA do razão — nunca um
-- campo (CLAUDE.md, regra 1) —, então somar o razão confere o rebanho inteiro.

\echo '== 1. Cabeças por fazenda (soma do razão do rebanho)'
SELECT f.code AS fazenda,
       SUM(l.quantity) AS cabecas
  FROM herd_herdledgerentry l
  JOIN properties_farm f ON f.id = l.farm_id
 GROUP BY f.code
 ORDER BY f.code;

SELECT SUM(quantity) AS cabecas_total FROM herd_herdledgerentry;

\echo '== 2. Custos confirmados por safra'
SELECT s.name AS safra,
       COUNT(*) AS lancamentos,
       SUM(c.amount) AS total
  FROM costs_costentry c
  JOIN organizations_season s ON s.id = c.season_id
 WHERE c.status = 'CONFIRMADA'
 GROUP BY s.name
 ORDER BY s.name;

\echo '== 3. Movimentações por situação'
SELECT status, COUNT(*) AS movimentos
  FROM herd_herdmovement
 GROUP BY status
 ORDER BY status;

\echo '== 4. Compras e vendas por situação'
SELECT 'compras' AS tipo, status, COUNT(*) FROM purchases_purchase GROUP BY status
UNION ALL
SELECT 'vendas', status, COUNT(*) FROM sales_sale GROUP BY status
ORDER BY 1, 2;

\echo '== 5. Integridade: deslocamentos que não fecham em zero (esperado: nenhuma linha)'
SELECT m.id, m.type, SUM(l.quantity) AS soma
  FROM herd_herdmovement m
  JOIN herd_herdledgerentry l ON l.movement_id = m.id
 WHERE m.type IN ('TRANSFERENCIA', 'EVOLUCAO', 'RECLASSIFICACAO')
 GROUP BY m.id, m.type
HAVING SUM(l.quantity) <> 0;

\echo '== 6. Auditoria (deve ter eventos; nunca menos que em produção)'
SELECT COUNT(*) AS eventos_de_auditoria FROM audit_auditevent;
