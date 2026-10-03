# ADR 0009 — Dispositivo confiável no segundo fator

**Data:** 2026-10-03 · **Status:** Aceita

## Problema

Quem ativa o 2FA digitava o código **a cada entrada**: o estado "verificado" vivia só na sessão (`otp_verificado_em`), e para `ADMIN` e `FINANCEIRO` o cookie ainda morria ao fechar o navegador (`set_expiry(0)`). Na prática, um código e uma senha por dia, no mesmo computador. Segurança que cansa vira pressão para desligá-la (pendência #19).

## Decisão

**"Confiar neste dispositivo" ao confirmar o código** (caixa marcada por padrão, com aviso sobre computador compartilhado).

1. **Token aleatório em cookie** (`r360_dispositivo`, `HttpOnly`, `Secure`, `SameSite=Lax`). No banco (`TrustedDevice`) fica só o **HMAC** do token, como nos códigos de recuperação: ler o banco não permite se passar por um dispositivo.
2. **A senha continua sendo pedida** em todo login; o que se dispensa é só o código. O rate limit e o CSRF seguem iguais. O cookie só vale para o usuário a quem foi dado.
3. **Validade deslizante de 30 dias, teto de 90** desde que a confiança foi dada (`CHECK expires_at <= absolute_expires_at`).
4. **Sessão longa só no dispositivo confiável:** 14 dias, com logout depois de 8 h sem uso (`SessaoLongaMiddleware`). Fora dele, nada muda: 12 h, e `ADMIN`/`FINANCEIRO` continuam com o cookie que morre ao fechar o navegador.
5. **Mudar de IP não revoga.** Rede móvel e residencial trocam de IP o tempo todo; travar por IP traria de volta o incômodo que esta decisão resolve. O IP de cada uso é gravado, o evento fica na auditoria e a página Conta avisa "IP mudou desde que você confiou".
6. **Revogação:** pelo próprio usuário (um ou todos, na página Conta); automática ao trocar a senha (os outros), definir senha por link, encerrar sessões, desativar/excluir o usuário, e redefinir o 2FA. Todos os caminhos de "encerrar sessões" passam por `two_factor.encerrar_sessoes`, que revoga também os dispositivos. A sessão presa a um dispositivo revogado cai na próxima requisição.

## Alternativas descartadas

- **Prender ao IP (ou à faixa /24):** pede o código de novo a cada troca de rede; no campo, com 4G, anula o benefício. Também dependeria de `client_ip`, que hoje confia num `X-Forwarded-For` forjável.
- **Sessão sem fim / "lembrar de mim" só da sessão:** a confiança ficaria numa sessão que o servidor não consegue listar nem revogar por dispositivo.
- **Biblioteca de dispositivos confiáveis (django-otp):** o projeto já tem TOTP próprio; seria a única razão para trazer a dependência.

## Consequências

- Quem perde o computador depende de revogar (Conta ou ADMIN → "Encerrar sessões") — por isso a lista mostra último uso e IP.
- `client_ip` continua confiando no primeiro item de `X-Forwarded-For`: o IP gravado na auditoria pode ser forjado. Não afeta a decisão (o IP aqui só é auditado), mas está registrado na pendência #49.
- `RequestContextMiddleware` passou a rodar logo após a autenticação, para que o que o `SessaoLongaMiddleware` e o `TwoFactorMiddleware` auditam leve IP, user-agent e `request_id`.
