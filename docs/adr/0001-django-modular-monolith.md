# ADR-001: Monólito modular em Django

- Estado: aprovado
- Data: 2026-09-19

## Contexto

A especificação propõe um monólito modular com trabalhadores separados. A decisão posterior do proprietário definiu Python e Django como stack principal.

## Decisão

Usar Django como aplicação transacional, Django Ninja para contratos HTTP, PostgreSQL como banco de produção, Redis/Celery para tarefas e módulos internos separados por domínio.

As regras de negócio ficam em serviços de aplicação. Modelos não substituem autorização. Toda operação crítica valida organização, campanha, vínculo, permissão, versão e estado antes de persistir auditoria e evento de outbox na mesma transação.

## Consequências

- A primeira entrega reduz coordenação entre serviços.
- Cada domínio mantém modelos e serviços próprios.
- Filas processam relatórios, arquivos e integrações sem receber autoridade implícita.
- Extração futura de um serviço exige contrato e migração explícitos.
