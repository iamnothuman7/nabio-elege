# Superadministrador, uso e identidade compacta

Atualização solicitada em 22/09/2026. Mantém a conta proprietária e a demonstração existentes; não redefine senhas, não cria administradores duplicados e não modifica RLS ou migrations.

## Administração

- `/plataforma/`: organizações, campanhas, usuários, situação, último login e pendências de senha/MFA.
- Criação de cliente com organização/campanha isolada e gestor; criação de usuário adicional em campanha existente com papel da mesma organização. Nenhum desses formulários cria superusuário ou concede papel reservado de operador da plataforma.
- Suspensão/reativação de acessos e encerramento de sessões de clientes. A própria conta administrativa e outras contas administrativas são protegidas dessas ações.
- Acesso a campanha e à sua auditoria por POST com CSRF, vínculo explícito e evento auditado. Sigilo jurídico e demais permissões continuam aplicados.
- `/plataforma/atividade/`: eventos imutáveis da própria conta administrativa, com busca, categoria e paginação. Os eventos operacionais de clientes ficam nas respectivas campanhas; não há exportação de logs brutos de servidor, segredos ou dados sigilosos.
- Conta proprietária é persistente, sem vencimento de acesso. As senhas iniciais são entregues somente na conversa; a senha pessoal definitiva e o MFA são configurados pelo proprietário no primeiro acesso. Recuperação automática por e-mail ainda não está implementada.

## Métricas: o que os números significam

- Dois indicadores separados: páginas da landing servidas publicamente e páginas HTML autenticadas acessadas pelos clientes, incluindo demo; detalhe por organização na página corrente. Períodos de 7 e 30 dias e evolução diária em horário de Brasília.
- Contagem do lado do servidor após GET 200, sem identificar visitantes, usar cookies de rastreamento ou gravar IP, user-agent, URL/query, usuário individual, contatos ou conteúdo acessado. Não são visitantes únicos; robôs e recargas podem contar. HEAD, erros, redirecionamentos, APIs, downloads, formulários públicos, prefetch, administradores e requisições com DNT/GPC são excluídos.
- Contadores operacionais no Redis próprio, retenção de até 35 dias; podem se perder com expiração, limpeza ou evicção. Não constituem histórico permanente, faturamento ou auditoria. A interface explicita essa limitação e não apresenta indisponibilidade como zero. Não há dados retroativos inventados.
- Identificador da organização vem exclusivamente do contexto de autorização resolvido no servidor. Apenas o superadministrador vê os indicadores globais. Falha de escrita das métricas não bloqueia uma página válida.

## Visual

Logo preservada em pixels/proporção, reduzida no menu público (200 px desktop; 140–175 px mobile), navegação interna, login, formulários públicos e rodapé. Símbolos decorativos 3D não foram alterados.

Mapa: hover e seleção usam elevação de 8 unidades SVG, sem outline/box-shadow retangular nem destaque de toque nativo. Ao selecionar outro estado, o anterior volta ao plano; teclado mantém foco sobre o contorno geográfico. Preferência de movimento reduzido mantém a seleção sem movimento. Os demais controles preservam foco visível.

Testes e evidências de publicação devem ser registrados após a validação da revisão exata. Esta atualização não declara todos os módulos do produto completos; consulte `implementation-status.md`.
