# Estado de implementação

Atualizado em 2026-09-19. “Parcial” significa que já há modelo ou fluxo testado, mas o módulo ainda não atende todos os requisitos e critérios de aceite da especificação v1.0.

| Módulo | Estado | Entrega disponível |
| --- | --- | --- |
| M01 Campanhas e organizações | Parcial | Tenant, campanha, fase, vínculos e isolamento de API |
| M02 Central de comando | Não iniciado | — |
| M03 Projetos e tarefas | Parcial | Projetos, tarefas e bloqueio de dependências cíclicas |
| M04 Financeiro e orçamento | Parcial | Orçamento, obrigação, aprovação segregada, pagamento e conciliação |
| M05 Arrecadação | Parcial | Recebimentos financeiros e estimáveis separados no modelo |
| M06 Contabilidade | Parcial | Lotes, manifesto e registro de entrega externa |
| M07 Compras e fornecedores | Parcial | Solicitação, itens, fornecedor e pedido |
| M08 Jurídico | Não iniciado | — |
| M09 Calendário regulatório | Não iniciado | — |
| M10 Estoque | Parcial | Saldos e movimentos transacionais sem saldo negativo |
| M11 Patrimônio | Não iniciado | — |
| M12 Logística | Não iniciado | — |
| M13 Equipes | Parcial | Vínculos, papéis e expiração por campanha |
| M14 Pessoas | Parcial | Pessoa e contatos cifrados, blind index e revisão de duplicidade |
| M15 Agenda e eventos | Não iniciado | — |
| M16 Resultados públicos | Não iniciado | — |
| M17 Comunicação | Não iniciado | — |
| M18 Estúdio | Não iniciado | — |
| M19 Atendimento | Parcial | Protocolo e criação idempotente a partir de submissão |
| M20 Propostas | Não iniciado | — |
| M21 Documentos | Parcial | Quarentena, versões, hash e classificação |
| M22 Dia da eleição | Não iniciado | — |
| M23 Relatórios e auditoria | Parcial | Auditoria imutável e outbox/inbox |
| M24 Encerramento | Não iniciado | — |
| M25 Formulários por link | Parcial | Publicação imutável, links, envio público/assistido e validação |

## Bloqueios para piloto com dados reais

- MFA e fluxo completo de convite/recuperação;
- armazenamento de objetos e antivírus para uploads;
- PostgreSQL com RLS e testes reais de concorrência;
- políticas de retenção aprovadas por jurídico e privacidade;
- validação contábil das regras financeiras;
- testes de carga, restauração, acessibilidade e segurança;
- telas de operação além do Django Admin;
- homologação dos dois ciclos completos descritos na especificação.
