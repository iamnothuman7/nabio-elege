# ADR-002: Organização e campanha como fronteiras independentes

- Estado: aprovado
- Data: 2026-09-19

## Decisão

Todo registro operacional carrega `tenant_id` e `campaign_id`. Vínculos e papéis são concedidos por campanha. Identificadores enviados pelo cliente não escolhem o contexto autorizado.

A aplicação aplica quatro camadas complementares: autorização do serviço, filtros explícitos, integridade relacional e, em PostgreSQL, políticas de RLS a serem ativadas antes do piloto.

## Consequências

- Uma organização não recebe acesso automático ao conteúdo de todas as campanhas.
- Testes sempre usam pelo menos duas campanhas e verificam negação cruzada.
- Arquivos, filas, auditoria e relatórios conservam a mesma fronteira.
