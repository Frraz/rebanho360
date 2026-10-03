# ADR 0003 — Escopo por fazenda desde a Fase 0

**Data:** 2026-09-30 · **Status:** Aceita

## Problema

Mais de 10 pessoas, entre campo e escritório, em 5 fazendas. Quem cuida do Baixão não deve enxergar o Goiano. Controle por papel resolve *o quê* a pessoa faz, mas não *sobre quais dados*.

A pergunta é de **momento**, não de necessidade: construir agora ou quando doer?

## Decisão

**Agora, na Fase 0**, antes de existir a primeira tela de listagem.

Dois eixos independentes:

- **Papel** (`role` no `User`) define a ação: `ADMIN`, `GESTOR`, `ESCRITORIO`, `CAMPO`, `FINANCEIRO`, `CONSULTA`. Usa permissões nativas do Django.
- **Escopo** (`UserFarmAccess`, user × fazenda) define o alcance. Aplicado por um manager base:

```python
class ScopedManager(models.Manager):
    def for_user(self, user):
        if user.role in (Role.ADMIN, Role.GESTOR):
            return self.all()
        return self.filter(farm__in=user.accessible_farms())
```

Todo modelo com fazenda herda. Toda view lista por `for_user(request.user)`, nunca por `.all()`.

## Alternativas descartadas

**Só papel, escopo depois.** O mais tentador — funciona hoje, com um produtor e uma equipe que se conhece. E é a decisão que fica cara: enxertar escopo depois significa reauditar **cada view, cada relatório, cada dashboard, cada exportação** do sistema. Um esquecimento vaza dado financeiro entre fazendas, e é o tipo de falha que ninguém percebe até vazar.

**Django Guardian (permissão por objeto).** Tabela genérica de permissões objeto a objeto. Resolve um problema mais geral que o nosso ao custo de um join a mais em toda consulta e de uma indireção que dificulta entender quem vê o quê. Nosso escopo é uma dimensão só: fazenda.

**Motor de autorização abstrato** (políticas, regras compostas, herança de escopo). Overengineering claro. Cinco fazendas, seis papéis.

## Consequências

**Boas:** vazamento entre fazendas fica improvável por construção, não por lembrança. Testar é direto: usuário sem acesso ao Goiano não vê registro do Goiano. Custo praticamente zero agora — uma tabela e um manager.

**Ruins:** todo modelo novo com fazenda precisa herdar o manager — item obrigatório na revisão de código. `ADMIN` e `GESTOR` continuam enxergando tudo; se um dia gestor precisar de escopo, é uma linha. Agregações globais (dashboard consolidado) precisam decidir explicitamente se respeitam escopo — **decisão: respeitam**, e o dashboard mostra apenas as fazendas do usuário.

**Teste que não pode faltar:** para cada modelo com fazenda, um teste confirmando que usuário fora do escopo recebe lista vazia e `404` no detalhe — nunca `403`, que confirmaria a existência do registro.
