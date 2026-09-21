# Interface e administração da plataforma

Atualização de 21/09/2026 solicitada pelo proprietário. A autorização de publicação consta na conversa; ela não deve ser apresentada como aprovação de um revisor independente no GitHub.

Registro da entrega `4067669`. A revisão pública atual é `4f1980b`; a atualização posterior acrescentou [mapa interativo e HSTS](landing-map-https.md) e retirou, a pedido do proprietário, o botão de pausa das animações. Contas e funcionalidades desta entrega foram preservadas.

## Resultado publicado

Revisão em produção: `4067669ace32c3f8b46ee61172ca8f887e127f19`, em [elege.nabio.pro](https://elege.nabio.pro/). [CI aprovada](https://github.com/iamnothuman7/nabio-elege/actions/runs/35635851080): SQLite/Python 3.11, PostgreSQL 14 e 15/Python 3.12, scanners e artefato. A suíte tem 202 testes; 23 exclusivos de PostgreSQL são ignorados na execução SQLite. A varredura local do histórico Git também não encontrou segredos.

- Homologação: 105 requisições HTTPS nos fluxos existentes (44 listas, 42 formulários, senha/MFA, CSRF, isolamento, upload/download e ClamAV real), mais 34 requisições HTTPS de administração/clientes. Ambas as baterias passaram na revisão exata.
- Rollback compatível ensaiado em staging, com verificação da revisão realmente carregada pelos workers, seguido de retorno à candidata. Sem reversão de migrations.
- Publicação com backup criptografado prévio; sem migrations, novos pacotes globais ou alterações dos outros vhosts/serviços. As dependências reutilizadas correspondem ao mesmo lock com hashes da release anterior.
- Produção: `/healthz/` respondeu `200` com `status=ok`, e `/entrar/` respondeu `200` inclusive via HEAD. Os dois novos logins foram validados por HTTPS e encerrados, preservando a troca inicial obrigatória e o cadastro de MFA pelo próprio usuário. Credenciais foram devolvidas somente na conversa, nunca neste repositório.
- Visual: login sem rolagem em 1366×768, 1280×720, 1024×768, 768×1024, 390×844 e 375×667. A tela 320×568 preserva rolagem vertical para não cortar controles. Nenhum vazamento horizontal observado. Desktop e 375×667 foram reconferidos no domínio público.
- Landing: quatro breakpoints entre 320 e 1366 px sem vazamento horizontal; abas testadas por clique e teclado, pausa/retomada das animações funcionando, sem erros no console na amostra. Redução de movimento/transparência tem fallbacks em CSS/JS e regressões de código; não foi realizada auditoria em aparelhos físicos ou leitor de tela.

## Alterações

- Login centralizado, compacto por altura, com superfícies translúcidas. Mantém rolagem de segurança quando mensagens, zoom, teclado virtual ou telas excepcionalmente baixas exigirem mais espaço; nenhum campo é cortado.
- Landing preserva composição e identidade: menu flutuante, faixa contínua, escrita inicial do título, flutuação dos cards e transições. Há pausa manual e respeito à preferência de reduzir movimento/transparência. Sem dependência de animação externa.
- Superadministrador da aplicação em `/plataforma/` (alias `/admin/`). Exige conta ativa, staff, superuser, troca de senha e MFA no perfil de produção. Não é o Django Admin e não concede poderes de banco de dados.
- Organizações, campanhas, usuários, criação de clientes, suspensão/reativação e trilha das próprias ações administrativas. O acesso a uma campanha é explícito e auditado; os controles de documentos jurídicos continuam vigentes.
- O comando `bootstrap_product_access` cria somente contas novas e um cliente demo isolado, com dados sintéticos identificados. Recebe senhas distintas por stdin protegido. Não sobrescreve contas nem habilita `LOCAL_DEMO` em produção.

## Publicação e reversão

`infra/update_release.py` aceita somente mudanças sem alteração de schema, dependências ou configuração. Faz backup criptografado no servidor antes da publicação, valida o SHA, preserva a release anterior e os estáticos com hash, troca `current` atomicamente e recarrega apenas os serviços Nabio Elege. A fila e o agendador usam parada graciosa e reinício próprios, pois não suportam recarga de código em processo. Não modifica Nginx, PostgreSQL, Redis compartilhado ou outros projetos.

Produção exige marcador de homologação para o SHA exato. `smoke_staging.py` cobre os fluxos existentes; `smoke_platform.py` cobre criação de clientes, senha, MFA, CSRF, isolamento, acesso explícito e revogação de sessão via HTTPS. Contas sintéticas de homologação são desativadas, não apagadas.

Não há novas migrations. Em falha operacional de ativação, o publicador restaura o link e o manifesto anteriores, sem restaurar ou apagar o banco. Os backups e as chaves permanecem no servidor. Exportação externa e alertas externos ainda precisam de destino/configuração autorizados. A lista de funcionalidades parciais em `implementation-status.md` continua válida; esta release não declara todos os módulos completos nem certificação eleitoral/jurídica.
