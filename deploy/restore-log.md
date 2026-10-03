# Log de restauração testada

**Mensal, na agenda.** Backup nunca restaurado é hipótese, não garantia —
ver docs/arquitetura/02-infra-e-deploy.md#restauração-testada.

## Procedimento

1. Subir Postgres limpo em container descartável:
   ```bash
   docker run --rm -d --name rebanho360_restore_test \
     -e POSTGRES_DB=rebanho360 -e POSTGRES_USER=rebanho360 -e POSTGRES_PASSWORD=rebanho360 \
     postgres:16-alpine
   ```
2. Restaurar o dump mais recente:
   ```bash
   docker exec -i rebanho360_restore_test pg_restore -U rebanho360 -d rebanho360 \
     < /backups/db/rebanho360_<timestamp>.dump
   ```
3. Conferir: total de cabeças por fazenda, total de custos da safra,
   contagem de movimentos, deslocamentos que não fecham em zero e eventos
   de auditoria. As consultas estão em `deploy/restore-check.sql`:
   ```bash
   docker exec -i rebanho360_restore_test psql -U rebanho360 -d rebanho360 \
     < deploy/restore-check.sql
   ```
   Rode o mesmo arquivo no banco de produção (`docker exec -i rebanho360_db ...`)
   e compare os números. A seção 5 tem que voltar vazia.
4. Anotar data, duração e resultado na tabela abaixo.
5. Destruir o container: `docker rm -f rebanho360_restore_test`.

## Histórico

| Data | Duração | Resultado | Quem | Observações |
|---|---|---|---|---|
| — | — | — | — | Nenhuma restauração real executada ainda — primeira entra na F0-18, após o primeiro deploy em produção (F0-17). `restore-check.sql` foi validado contra o banco de desenvolvimento (seed_demo) em 01/10/2026. |
