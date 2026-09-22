# Superadministrador, uso e identidade compacta

Atualização de acesso solicitada em 22/09/2026: duas contas explicitamente autorizadas podem usar senha definitiva e MFA opcional. O histórico abaixo registra a publicação anterior; a mudança de acesso tem registro operacional próprio. Não modifica RLS ou migrations.

## Administração

- `/plataforma/`: organizações, campanhas, usuários, situação, último login e pendências de senha/MFA.
- Criação de cliente com organização/campanha isolada e gestor; criação de usuário adicional em campanha existente com papel da mesma organização. Nenhum desses formulários cria superusuário ou concede papel reservado de operador da plataforma.
- Suspensão/reativação de acessos e encerramento de sessões de clientes. A própria conta administrativa e outras contas administrativas são protegidas dessas ações.
- Acesso a campanha e à sua auditoria por POST com CSRF, vínculo explícito e evento auditado. Sigilo jurídico e demais permissões continuam aplicados.
- `/plataforma/atividade/`: eventos imutáveis da própria conta administrativa, com busca, categoria e paginação. Os eventos operacionais de clientes ficam nas respectivas campanhas; não há exportação de logs brutos de servidor, segredos ou dados sigilosos.
- Conta proprietária é persistente, sem vencimento de acesso. Por solicitação expressa do proprietário, suas duas contas recebem senhas definitivas, sem troca inicial nem MFA obrigatório. Senhas entregues somente na conversa; recuperação automática por e-mail ainda não está implementada.

## Acesso direto por autorização explícita

`prepare_direct_access` exige duas contas existentes, um único vínculo ativo demo, senhas distintas de pelo menos 20 caracteres por stdin e confirmação explícita `--confirm-password-only`. A transação altera apenas essas contas, revoga suas sessões/fatores anteriores e registra auditoria sem segredos. Não é exposto por formulário ou API de cliente.

O grupo reservado `nabio-password-only-access` não concede permissões. Ele permite não cadastrar MFA; um fator posteriormente ativado continua obrigatório no próximo login. A política padrão permanece exigindo MFA para outras contas. HTTPS, CSRF, bloqueios de login e limites de campanha não são desativados. Login só com senha possui proteção menor contra comprometimento da senha, especialmente no superadministrador.

O antigo usuário demo é renomeado e mantém sua identidade no histórico. Seu vínculo demo é revogado; registros sintéticos são preservados, sem migração ou exclusão. Uma organização/campanha real vazia recebe o novo vínculo, com os mesmos direitos de cliente e nenhum privilégio global. Cargo, eleição e abrangência ficam explicitamente a configurar; não há inferência de número eleitoral a partir da senha.

Rollback de código anterior volta a exigir MFA; os dados e os hashes das novas senhas permanecem. Não restaurar banco nem reexecutar a conversão: ela recusa conta já convertida. Não reativar as credenciais antigas.

## Métricas: o que os números significam

- Dois indicadores separados: páginas da landing servidas publicamente e páginas HTML autenticadas acessadas pelos clientes, incluindo demo; detalhe por organização na página corrente. Períodos de 7 e 30 dias e evolução diária em horário de Brasília.
- Contagem do lado do servidor após GET 200, sem identificar visitantes, usar cookies de rastreamento ou gravar IP, user-agent, URL/query, usuário individual, contatos ou conteúdo acessado. Não são visitantes únicos; robôs e recargas podem contar. HEAD, erros, redirecionamentos, APIs, downloads, formulários públicos, prefetch, administradores e requisições com DNT/GPC são excluídos.
- Contadores operacionais no Redis próprio, retenção de até 35 dias; podem se perder com expiração, limpeza ou evicção. Não constituem histórico permanente, faturamento ou auditoria. A interface explicita essa limitação e não apresenta indisponibilidade como zero. Não há dados retroativos inventados.
- Identificador da organização vem exclusivamente do contexto de autorização resolvido no servidor. Apenas o superadministrador vê os indicadores globais. Falha de escrita das métricas não bloqueia uma página válida.

## Visual

Logo preservada em pixels/proporção, reduzida no menu público (200 px desktop; 140–175 px mobile), navegação interna, login, formulários públicos e rodapé. Símbolos decorativos 3D não foram alterados.

Mapa: hover e seleção usam elevação de 8 unidades SVG, sem outline/box-shadow retangular nem destaque de toque nativo. Ao selecionar outro estado, o anterior volta ao plano; teclado mantém foco sobre o contorno geográfico. Preferência de movimento reduzido mantém a seleção sem movimento. Os demais controles preservam foco visível.

## Evidências de publicação — 22/09/2026

- Revisão pública: `b3823fa158a04fa53562f1f8cde1ed745d3904b7`. [CI aprovada](https://github.com/iamnothuman7/nabio-elege/actions/runs/35720728478) em SQLite/Python 3.11, PostgreSQL 14/15/Python 3.12, scanners e artefato.
- 219 testes locais, sem falhas, 23 skips específicos de PostgreSQL; 38 templates compilados, análise estática/formatação aprovadas e nenhuma migration pendente. Histórico Git sem segredos encontrados pelo scanner.
- Staging da revisão exata: 105 requisições HTTPS nos módulos existentes (44 listas/42 formulários, MFA, CSRF, isolamento, arquivos privados e antivírus real), mais 51 requisições nos fluxos de plataforma, cliente e novo usuário. Criação com papel explícito, negação de privilégios globais, acesso cruzado negado, contagens reais em Redis e revogação de sessões aprovados. Contas sintéticas desativadas ao final.
- Rollback compatível ensaiado em staging e retorno à candidata; backup criptografado prévio ao rollout. Sem alterações de banco/schema, dependências, Nginx ou outros projetos. Workers confirmados na nova revisão; staging desligado após os testes.
- Conferência visual de landing/login e painel em viewports desktop/mobile. Painel visual usou exclusivamente fixture sintética local dos mesmos templates, nunca rota de bypass de autenticação em produção. Larguras 320/390/768/1366 sem overflow horizontal na amostra; login 390×844 sem rolagem. Expansão da evolução diária, tamanho de logo e seleção do mapa verificados. Testes em viewport não substituem aparelhos físicos/leitores de tela.
- Domínio público reconferido: TLS válido sem bypass, redirecionamento HTTP→HTTPS, quatro páginas GET/HEAD 200 e 12 recursos HTTPS 200. Rotas administrativas redirecionam visitantes anônimos ao login. Contas proprietária e demo permanecem ativas, sem expiração de vínculo e sem redefinição de senha; primeiro acesso/MFA permanecem sob controle do proprietário.

Esta atualização não declara todos os módulos do produto completos; consulte `implementation-status.md`. Recuperação automática por e-mail, histórico analítico durável, alertas/backup externos, revisão independente e homologação funcional ampla continuam pendentes.
