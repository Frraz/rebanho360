# Firewall

VPS **compartilhado** com outros sistemas. Toda alteração de firewall entra
aqui, com data e motivo — ver docs/arquitetura/02-infra-e-deploy.md#firewall.

## Estado esperado

| Porta | Protocolo | Motivo |
|---|---|---|
| 22 | tcp | SSH, só por chave — senha desabilitada |
| 80 | tcp | HTTP → redireciona para HTTPS |
| 443 | tcp | HTTPS |

Nada mais. `5432` (Postgres) e `6379` (Redis) **nunca** abertos — não são
publicados nem no `docker-compose.prod.yml` (sem `ports:` nesses serviços).

## Antes do primeiro deploy (F0-17)

- [ ] Confirmar que a porta `8010` está livre no host (`ss -ltnp | grep 8010`)
- [ ] Confirmar que `ufw status` (ou equivalente) só libera 22/80/443
- [ ] Documentar aqui qualquer exceção, com data e motivo

## Histórico de alterações

| Data | Alteração | Motivo | Quem |
|---|---|---|---|
| — | Nenhuma alteração ainda | — | — |
