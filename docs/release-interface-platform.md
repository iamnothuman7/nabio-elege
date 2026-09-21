# Interface e administração da plataforma

Atualização de 21/09/2026 solicitada pelo proprietário. A autorização de publicação consta na conversa; ela não deve ser apresentada como aprovação de um revisor independente no GitHub.

- Login centralizado, compacto por altura, com superfícies translúcidas. Mantém rolagem de segurança quando mensagens, zoom, teclado virtual ou telas excepcionalmente baixas exigirem mais espaço; nenhum campo é cortado.
- Landing preserva composição e identidade: menu flutuante, faixa contínua, escrita inicial do título, flutuação dos cards e transições. Há pausa manual e respeito à preferência de reduzir movimento/transparência. Sem dependência de animação externa.
- Superadministrador da aplicação em `/plataforma/` (alias `/admin/`). Exige conta ativa, staff, superuser, troca de senha e MFA no perfil de produção. Não é o Django Admin e não concede poderes de banco de dados.
- Organizações, campanhas, usuários, criação de clientes, suspensão/reativação e trilha das próprias ações administrativas. O acesso a uma campanha é explícito e auditado; os controles de documentos jurídicos continuam vigentes.
- O comando `bootstrap_product_access` cria somente contas novas e um cliente demo isolado, com dados sintéticos identificados. Recebe senhas distintas por stdin protegido. Não sobrescreve contas nem habilita `LOCAL_DEMO` em produção.

## Publicação e reversão

`infra/update_release.py` aceita somente mudanças sem alteração de schema, dependências ou configuração. Faz backup criptografado no servidor antes da publicação, valida o SHA, preserva a release anterior e os estáticos com hash, troca `current` atomicamente e recarrega apenas os serviços Nabio Elege. A fila e o agendador usam parada graciosa e reinício próprios, pois não suportam recarga de código em processo. Não modifica Nginx, PostgreSQL, Redis compartilhado ou outros projetos.

Produção exige marcador de homologação para o SHA exato. `smoke_staging.py` cobre os fluxos existentes; `smoke_platform.py` cobre criação de clientes, senha, MFA, CSRF, isolamento, acesso explícito e revogação de sessão via HTTPS. Contas sintéticas de homologação são desativadas, não apagadas.

Não há novas migrations. Em falha operacional de ativação, o publicador restaura o link e o manifesto anteriores, sem restaurar ou apagar o banco. Os backups e as chaves permanecem no servidor. Exportação externa e alertas externos ainda precisam de destino/configuração autorizados. A lista de funcionalidades parciais em `implementation-status.md` continua válida; esta release não declara todos os módulos completos nem certificação eleitoral/jurídica.
