# Definition of Done

Vale para toda tarefa de todas as fases. Tela que aparece não é funcionalidade pronta.

---

## Checklist

### Funciona
- [ ] Backend implementado, com validação no servidor
- [ ] Integrado ao fluxo — não é tela solta
- [ ] Não cria dado duplicado nem exige redigitar o que já existe

### Protege
- [ ] Permissão verificada **e escopo de fazenda aplicado** (`for_user`, nunca `.all()`)
- [ ] Registro fora do escopo devolve `404`, não `403`
- [ ] Operação que escreve em mais de uma tabela é atômica
- [ ] Estado lido sob `select_for_update` antes de mudar, nas operações críticas
- [ ] Gera auditoria onde importa, com `reason` nas edições e exclusões

### Desfaz
- [ ] **É editável, excluível e restaurável**
- [ ] `desfazer_efeitos()` implementado e testado
- [ ] `dependentes()` declarado, e a análise de impacto aparece antes de executar

### Avisa
- [ ] Erro de validação destaca o campo
- [ ] Erro de negócio tem mensagem específica — *"Saldo insuficiente: há 12 cabeças de Machos 13 a 24 meses no Baixão, foram informadas 20"*, não "operação inválida"
- [ ] Erro inesperado mostra código de referência, nunca traceback
- [ ] Indicador sem dado aparece como "—" com o motivo, nunca como `0`

### É testado
- [ ] Testes das **regras de cálculo** — não cobertura artificial
- [ ] `safe_div` com divisor zero devolve `None`
- [ ] Concorrência testada onde há risco de duplicidade ou saldo negativo

### Serve
- [ ] Funciona no desktop
- [ ] **Funciona em 360 px — verificado no navegador, não suposto**
- [ ] Segue o [design system](../ux/02-design-system.md): classes de componente e partials existentes, ícone do sprite, sem emoji, um botão primário por tela, status com texto **e** marcador
- [ ] Lista vira cartão no celular; estados vazio, erro e sucesso existem
- [ ] CSS recompilado (`sh bin/build_css.sh`) se mexeu em classe — `output.css` não é versionado
- [ ] Texto em português claro, com o termo que o produtor usa
- [ ] Depois de salvar, sugere o próximo passo

### Não regride
- [ ] Não quebra o que já existe
- [ ] Documentação atualizada quando a decisão mudou

---

## Prioridade em caso de conflito

1. **Integridade dos dados**
2. **Segurança**
3. Fluxo operacional correto
4. Usabilidade
5. Clareza visual
6. Desempenho
7. Recurso secundário
8. Polimento

Na dúvida entre entregar rápido e manter o saldo correto, o saldo ganha.

---

## As quatro coisas que nunca passam

Independentemente de prazo:

1. **`float` em valor ou peso.** `Decimal` sempre — [ADR 0005](../arquitetura/adr/0005-decimal-e-arredondamento.md)
2. **Saldo de rebanho como campo gravado.** Sempre derivado do razão — [ADR 0002](../arquitetura/adr/0002-rebanho-como-razao-de-movimentacoes.md)
3. **Consulta sem escopo de fazenda.** `.all()` numa listagem é vazamento — [ADR 0003](../arquitetura/adr/0003-escopo-por-fazenda-desde-a-fase-0.md)
4. **Caminho de código que altere um `AuditEvent`.** Nem para `ADMIN` — [ADR 0006](../arquitetura/adr/0006-tudo-editavel-com-auditoria-imutavel.md)

---

## O maior risco do projeto

Não é Django, Docker nem PostgreSQL. É **modelar o negócio errado**.

Por isso as pendências em [regras-negocio/99](../regras-negocio/99-pendencias.md) são item de roadmap, não nota de rodapé. Duas delas — **#5** e **#2** — mexem na carga histórica, e resolver depois custa muito mais caro que perguntar antes.

Quando faltar uma regra: **não inventar em silêncio.** Registrar a pendência, implementar a alternativa mais reversível, deixar o código isolado para ajuste.
