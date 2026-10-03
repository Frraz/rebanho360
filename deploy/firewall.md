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

- [x] A porta `8010` estava ocupada (`agi_nginx`) — usamos a `8013` (`WEB_HOST_PORT` no `.env`). Confirme com `ss -ltnp | grep 8013`
- [x] `ufw` ativado com 22/80/443 (estava inativo)
- [ ] Documentar aqui qualquer exceção, com data e motivo

## Histórico de alterações

| Data | Alteração | Motivo | Quem |
|---|---|---|---|
| 2026-10-03 | `ufw` ativado com 22, 80 e 443 (estava inativo) | Deploy do Rebanho360 no VPS compartilhado; efeito colateral a conferir: porta 3000 (`next-server`) deixa de ser acessível de fora e containers que chamem o host por IP podem ser barrados | Warley |
