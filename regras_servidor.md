# Nabio Elege — regras do servidor e operação de produção

**Versão:** 1.0 · **Data:** 17/09/2026  
**Status:** padrão inicial para implantação  
**Escopo:** aplicação web, APIs, banco de dados, arquivos, filas, integrações e rotina de deploy do projeto **Nabio Elege**.

> Este documento é um contrato operacional. Ele descreve como o servidor deve ser configurado e como a equipe deve publicar alterações sem colocar dados, usuários ou a disponibilidade em risco. Os valores entre `<...>` são placeholders e devem ser preenchidos antes da primeira implantação.

## 1. Regras inegociáveis

1. Nunca colocar senhas, tokens, chaves privadas, `SECRET_KEY` ou arquivos `.env` no Git.
2. Produção nunca é alterada diretamente com edição manual de código. Toda mudança deve vir de uma revisão no repositório e de uma versão identificável.
3. Antes de migration, alteração de configuração ou deploy, criar backup verificável do banco e registrar o horário.
4. Nunca executar `reset --hard`, `clean -fd`, `DROP DATABASE`, exclusões em massa ou comandos destrutivos sem uma autorização registrada e um plano de restauração.
5. Não reiniciar o servidor inteiro para publicar a aplicação. Recarregar somente o serviço afetado e de forma graciosa.
6. Migrações devem ser compatíveis com a versão anterior e com a versão nova durante o período de rollout.
7. Dados de clientes, empresas, documentos, pagamentos e logs devem ficar segregados por organização/tenant no servidor e nas consultas.
8. Todo endpoint protegido deve validar autorização no servidor. Ocultar um botão no navegador nunca é uma regra de segurança.
9. Toda integração externa deve ter timeout, retry limitado, logs sem segredos e comportamento seguro quando estiver indisponível.
10. Cada incidente, rollback e alteração de infraestrutura deve ficar registrado no changelog operacional.

## 2. Identidade e nomes do projeto

| Item | Valor inicial | Regra |
| --- | --- | --- |
| Nome público | Nabio Elege | Usar a grafia oficial em títulos, e-mails e telas. |
| Slug técnico | `nabio-elege` | Minúsculas, hífens, sem espaços ou acentos. |
| Diretório da aplicação | `<APP_ROOT>` | Ex.: `/var/www/apps/nabio-elege`. Nunca usar `/tmp` para código ativo. |
| Usuário do serviço | `<APP_USER>` | Usuário sem login interativo e sem privilégio de root. |
| Serviço da aplicação | `<APP_SERVICE>` | Ex.: `nabio-elege-web.service`. |
| Serviço de fila | `<WORKER_SERVICE>` | Preencher apenas se houver tarefas assíncronas. |
| Domínio principal | `elege.nabio.pro` | Ex.: `app.nabioelege.com.br`. |
| Ambiente | `development`, `staging`, `production` | Nunca misturar banco ou secrets entre ambientes. |

O usuário de deploy pode possuir acesso de publicação, mas o processo da aplicação deve executar com permissões mínimas. O acesso root é reservado à administração do sistema operacional e não deve ser usado pela aplicação.

## 3. Ambientes obrigatórios

### Desenvolvimento

- Banco e arquivos locais ou descartáveis.
- `DEBUG=True` somente localmente.
- OAuth, pagamentos, e-mails e webhooks apontam para sandbox/mock.
- Nunca usar cópia não anonimizada do banco de produção.

### Staging

- Replica a topologia de produção com dados sintéticos ou anonimizados.
- `DEBUG=False`, HTTPS e cabeçalhos de segurança ativos.
- Executa migrations, testes de integração, smoke tests e teste de rollback.
- Recebe uma versão antes de produção sempre que houver alteração de banco, autenticação, pagamento ou infraestrutura.

### Produção

- `DEBUG=False`, `ALLOWED_HOSTS` restrito e banco dedicado.
- Secrets carregados pelo ambiente do serviço ou por um secret manager; nunca por arquivo versionado.
- Somente artefatos aprovados, com commit/tag registrado.
- Backups automáticos, logs centralizados e monitoramento de disponibilidade.

## 4. Topologia recomendada

```text
Internet
   │ HTTPS 443
   ▼
Nginx / proxy reverso
   ├── arquivos estáticos e mídia pública permitida
   └── socket privado → aplicação Nabio Elege
                         ├── PostgreSQL (dados transacionais)
                         ├── Redis (cache/fila, se usado)
                         ├── worker/scheduler (tarefas assíncronas)
                         └── provedor externo (e-mail, pagamento, mapas etc.)
```

Regras de rede:

- Expor publicamente apenas 80/443. Redirecionar 80 para 443.
- SSH deve ser restrito por firewall a IPs administrativos ou VPN sempre que possível.
- PostgreSQL, Redis, sockets e painéis administrativos não podem escutar na interface pública.
- O proxy deve encaminhar somente os cabeçalhos necessários e limitar tamanho de corpo, timeout e taxa de requisições.
- Arquivos de mídia enviados por usuários nunca devem ser executados como código pelo servidor web.

## 5. Sistema operacional e acesso SSH

### Conta e autenticação

- Usar chaves SSH Ed25519 individuais; não compartilhar uma chave entre desenvolvedores.
- Desativar login SSH por senha e login root direto depois de validar o acesso por chave.
- Cada pessoa deve ter um usuário nominal, grupo de deploy e permissão mínima.
- Remover chaves de pessoas que saíram do projeto no mesmo dia.
- Exigir MFA no provedor, no repositório e no painel de infraestrutura.

Exemplo de política em `/etc/ssh/sshd_config` (validar no staging antes):

```text
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
X11Forwarding no
AllowGroups nabio-deploy nabio-ops
```

Após modificar SSH, testar uma segunda sessão antes de fechar a sessão atual:

```bash
sudo sshd -t
sudo systemctl reload ssh
ssh -o BatchMode=yes <APP_USER>@<SERVER_HOST> 'id && hostname'
```

### Atualizações do sistema

- Aplicar atualizações de segurança em janela planejada.
- Reinicializar somente quando necessário e avisar os responsáveis antes.
- Manter relógio sincronizado via NTP.
- Não instalar pacotes diretamente em produção sem registrar nome, versão e motivo.
- Usar `unattended-upgrades` ou processo equivalente apenas para atualizações testadas pela política da equipe.

## 6. Estrutura de diretórios

Exemplo para um servidor Linux:

```text
/var/www/apps/nabio-elege/
├── releases/                 # versões imutáveis por commit
├── current -> releases/...   # symlink da versão ativa
├── shared/
│   ├── .env                  # fora do Git, somente APP_USER
│   ├── media/                # arquivos persistentes
│   ├── staticfiles/          # resultado do collectstatic
│   └── logs/
└── backups/                  # preferencialmente em volume separado
```

Regras de permissão:

- Código: `root:<APP_GROUP>` e somente leitura para o processo quando possível.
- `.env`: `0600`, proprietário `<APP_USER>` ou usuário de secrets.
- `media/`: gravável apenas por uma rotina de upload controlada; nunca pelo Nginx diretamente sem necessidade.
- `staticfiles/`: somente leitura para o processo web depois do build.
- Backups: `0600`, acesso ao grupo de operações, criptografia em repouso e cópia fora do servidor.

## 7. Variáveis de ambiente e segredos

O projeto deve ter `.env.example` sem valores reais. Em produção, usar o ambiente do systemd, Vault, Doppler, AWS Secrets Manager, 1Password Secrets Automation ou solução equivalente.

Variáveis mínimas recomendadas:

```dotenv
APP_ENV=production
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<gerar-uma-chave-longa-e-unica>
DJANGO_ALLOWED_HOSTS=elege.nabio.pro
DJANGO_CSRF_TRUSTED_ORIGINS=https://elege.nabio.pro
DATABASE_URL=postgresql://<DB_USER>:<DB_PASSWORD>@<DB_HOST>:5432/<DB_NAME>
REDIS_URL=redis://<REDIS_HOST>:6379/0
EMAIL_HOST=<SMTP_HOST>
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<SUPPORT_EMAIL>
EMAIL_HOST_PASSWORD=<SMTP_SECRET>
SENTRY_DSN=<opcional>
```

Regras para secrets:

- Gerar segredos diferentes para development, staging e production.
- Rotacionar secrets após vazamento, saída de colaborador ou suspeita de acesso.
- Não imprimir o ambiente completo em logs, endpoints de diagnóstico ou tickets.
- Mascarar tokens, e-mails sensíveis, CPF, telefone, Authorization e cookies nos logs.
- Nunca enviar token de servidor ao navegador; o front-end recebe apenas chaves públicas necessárias.

## 8. Banco de dados

PostgreSQL é o banco recomendado para produção. SQLite pode ser usado somente em desenvolvimento ou testes isolados.

Regras de aplicação:

- Toda alteração de schema passa por migration versionada e revisão.
- Não editar tabelas manualmente para corrigir dados sem script auditável.
- Operações destrutivas exigem backup, contagem afetada, aprovação e plano de reversão.
- Usar transações para operações que alteram mais de uma entidade.
- Criar índices para filtros e relacionamentos de alto volume; medir antes/depois.
- Toda consulta multi-tenant deve filtrar pela organização/contexto do usuário no servidor.
- Dados de pagamento não devem ser armazenados quando o provedor oferecer tokenização.
- Retenção e exclusão de dados devem seguir a política de privacidade e a LGPD.

### Backup mínimo

- Backup lógico diário do PostgreSQL.
- Backup incremental ou snapshot conforme o provedor.
- Retenção sugerida: 7 diários, 4 semanais e 12 mensais.
- Uma cópia fora do servidor e, preferencialmente, em outra região.
- Teste de restauração mensal em ambiente isolado.
- Registrar checksum e tamanho para detectar backup incompleto.

Exemplo de backup (ajustar o secret manager e o caminho):

```bash
set -euo pipefail
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
pg_dump --format=custom --no-owner --no-privileges \
  --dbname="$DATABASE_URL" \
  --file="/var/backups/nabio-elege/db-$STAMP.dump"
sha256sum "/var/backups/nabio-elege/db-$STAMP.dump" \
  > "/var/backups/nabio-elege/db-$STAMP.dump.sha256"
```

Restauração nunca deve sobrescrever produção diretamente. Primeiro restaurar em banco temporário, validar migrations, contagens e fluxos críticos, e somente então executar um procedimento de recuperação aprovado.

## 9. Deploy seguro e sem indisponibilidade desnecessária

### Pré-requisitos

- Pull request aprovado e CI verde.
- Commit ou tag registrada.
- Changelog com impacto, migration, variáveis novas e rollback.
- Backup recente verificado.
- Janela e responsáveis definidos para alterações de alto risco.
- Staging validado quando houver banco, autenticação, pagamento ou infraestrutura.

### Fluxo recomendado

```bash
set -euo pipefail
cd <APP_ROOT>

# 1. Capturar versão e estado sem modificar o banco.
git fetch --prune origin
git rev-parse HEAD
git status --short

# 2. Criar release imutável a partir do commit aprovado.
export RELEASE="$(git rev-parse --short origin/main)-$(date -u +%Y%m%d%H%M%S)"
git worktree add "releases/$RELEASE" "origin/main"
cd "releases/$RELEASE"

# 3. Instalar dependências reproduzíveis.
<PYTHON> -m pip install --require-hashes -r requirements.txt

# 4. Validar antes de ativar.
<PYTHON> manage.py check --deploy
<PYTHON> manage.py test
<PYTHON> manage.py collectstatic --noinput

# 5. Migrations somente depois do backup.
<PYTHON> manage.py migrate --plan
<PYTHON> manage.py migrate --noinput

# 6. Ativação atômica e reload gracioso.
ln -sfnT "<APP_ROOT>/releases/$RELEASE" "<APP_ROOT>/current"
sudo systemctl reload <APP_SERVICE>
sudo systemctl reload nginx
```

Se o serviço não suportar `reload`, configurar `ExecReload` para recarregar workers de forma graciosa. `restart` só deve ser usado quando documentado e em janela controlada.

### Smoke test pós-deploy

Verificar de uma máquina externa e no servidor:

```bash
curl --fail --silent --show-error --location \
  --max-time 15 "https://elege.nabio.pro/healthz/"
curl --fail --silent --show-error --head \
  --max-time 15 "https://elege.nabio.pro/"
sudo systemctl is-active <APP_SERVICE>
sudo systemctl is-active nginx
```

O endpoint `/healthz/` deve retornar somente status operacional, sem dados internos, secrets ou informações de banco. Para dependências, separar `liveness` (processo vivo) de `readiness` (pronto para receber tráfego).

### Rollback

Rollback deve ser rápido, reversível e registrado:

```bash
set -euo pipefail
cd <APP_ROOT>
PREVIOUS="$(readlink -f current)"
ln -sfnT "<APP_ROOT>/releases/<KNOWN_GOOD_RELEASE>" current
sudo systemctl reload <APP_SERVICE>
curl --fail --silent --show-error --max-time 15 "https://elege.nabio.pro/healthz/"
printf 'Anterior: %s\nAtual: %s\n' "$PREVIOUS" "$(readlink -f current)"
```

Não fazer rollback cego de migrations incompatíveis. Quando uma migration já foi executada, preferir uma migration compensatória; restaurar banco somente no procedimento de desastre.

## 10. Nginx, HTTPS e cabeçalhos

- TLS válido e renovação automática monitorada.
- Redirecionar HTTP para HTTPS.
- HSTS somente depois de confirmar que todos os subdomínios obrigatórios usam HTTPS.
- Configurar `Content-Security-Policy` progressivamente, iniciando em `Report-Only`.
- Ativar `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` mínima e proteção contra framing.
- Definir `client_max_body_size` conforme uploads reais; não deixar ilimitado.
- Não armazenar tokens ou dados pessoais em query strings.
- Separar cache de assets versionados de respostas HTML e dados privados.

Cookies de sessão devem usar `Secure`, `HttpOnly` e `SameSite=Lax` (ou `Strict` quando compatível). Cookies de terceiros somente com finalidade e consentimento válidos.

## 11. Autenticação, autorização e LGPD

- Senhas armazenadas somente com hash adaptativo do framework; nunca reversíveis.
- Login com rate limit, bloqueio progressivo e logs de tentativa sem senha.
- Verificação de e-mail quando a conta der acesso a dados ou operações sensíveis.
- MFA obrigatório para administradores e recomendado para gestores.
- Sessões revogáveis após troca de senha, logout global ou alteração de privilégio.
- Permissões avaliadas no backend por organização, unidade, cargo e ação.
- Auditoria para login, exportação, alteração de permissão, pagamentos, documentos, exclusões e integrações.
- Minimizar dados coletados, informar finalidade, definir retenção e atender solicitação de titular.
- Nunca expor CPF, telefone, e-mail ou documentos em logs, URLs ou respostas públicas sem necessidade.

## 12. Filas, tarefas e integrações

- Toda tarefa assíncrona deve ser idempotente: reprocessar não pode duplicar cobrança, envio ou cadastro.
- Usar `timeout`, retry com backoff e limite de tentativas.
- Enviar eventos importantes para uma fila/outbox antes de chamar sistemas externos.
- Webhooks devem validar assinatura, registrar `event_id`, rejeitar duplicatas e responder rapidamente.
- Não bloquear uma requisição web esperando um provedor lento; usar tarefa assíncrona quando possível.
- Chaves de sandbox e produção nunca se misturam.
- Registrar request id/correlation id, status e duração; nunca corpo contendo segredo.

## 13. Logs, métricas e alertas

Logs estruturados em JSON, com UTC, `request_id`, serviço, versão, rota, status e duração.

Alertas mínimos:

- aplicação fora do ar ou `/healthz/` falhando;
- erro HTTP 5xx acima do limite definido;
- aumento de latência p95/p99;
- fila acumulada ou worker parado;
- disco, memória ou CPU próximos do limite;
- certificado TLS próximo do vencimento;
- backup ausente, inválido ou sem espaço;
- tentativas de login anômalas e alterações administrativas incomuns.

Nunca enviar logs de produção para um serviço sem contrato de tratamento de dados. Definir retenção e acesso por função.

## 14. CI/CD e fluxo da equipe

Cada pull request deve executar, no mínimo:

1. lint/format;
2. verificação de sintaxe;
3. testes unitários e de integração;
4. verificação de migrations (`makemigrations --check` quando aplicável);
5. build de assets;
6. scanner de secrets e dependências;
7. verificação de templates e arquivos estáticos;
8. criação de artefato versionado.

Regras de Git:

- `main`/`production` protegida, sem push forçado.
- Pull request obrigatório e pelo menos uma revisão para código de produção.
- Commits pequenos e descritivos; não misturar refatoração com migration arriscada.
- Branches temporárias devem ser excluídas após merge.
- Antes de publicar, conferir `git diff`, lista de arquivos e origem/destino do deploy.
- Nunca fazer deploy integral de uma pasta local em servidor compartilhado; publicar somente o artefato aprovado.

## 15. Procedimento de incidente

1. Confirmar impacto e abrir registro com horário UTC, sintomas e versão ativa.
2. Preservar logs, métricas e evidências; não apagar dados para “limpar” o problema.
3. Mitigar: pausar fila, desativar feature flag ou voltar para a última versão estável.
4. Proteger dados: revogar token, bloquear conta ou limitar endpoint se houver suspeita de segurança.
5. Comunicar responsáveis e usuários afetados conforme a gravidade.
6. Recuperar e validar com smoke tests.
7. Fazer análise de causa raiz, registrar ações preventivas e atualizar este documento.

Se houver suspeita de vazamento, considerar todos os secrets afetados até provar o contrário: revogar, gerar novos, revisar acessos e preservar a evidência.

## 16. Checklist antes do primeiro go-live

- [ ] Domínio, DNS e TLS configurados.
- [ ] Firewall com somente portas necessárias.
- [ ] SSH por chave, sem root/senha direta.
- [ ] Usuário do serviço sem privilégio administrativo.
- [ ] `.env` criado fora do Git, com permissões `0600`.
- [ ] Banco de produção separado e com migrations aplicadas em staging.
- [ ] Backup e restauração testados.
- [ ] `DEBUG=False`, hosts e origens CSRF restritos.
- [ ] Cookies, CSRF, headers e rate limits revisados.
- [ ] E-mail, pagamentos, OAuth e webhooks em credenciais de produção corretas.
- [ ] `collectstatic` e cache de assets versionados.
- [ ] `/healthz/`, logs, métricas e alertas funcionando.
- [ ] Teste de conta, recuperação, autorização por tenant e logout global.
- [ ] Plano de rollback documentado e testado.
- [ ] Responsável de plantão e janela de mudança definidos.

## 17. Registro de alterações do servidor

Manter uma tabela em cada publicação:

| Data UTC | Versão/commit | Responsável | Banco/migration | Backup | Resultado | Rollback |
| --- | --- | --- | --- | --- | --- | --- |
| `<AAAA-MM-DD HH:MM>` | `<sha/tag>` | `<nome>` | `<sim/não; ID>` | `<arquivo/checksum>` | `<ok/falha>` | `<não / versão>` |

## 18. Valores que precisam ser definidos para o Nabio Elege

Antes de executar a primeira instalação, preencher em um cofre de secrets ou inventário privado:

- `elege.nabio.pro` e subdomínios;
- `<SERVER_HOST>` e provedor/região;
- `<APP_ROOT>`, `<APP_USER>`, `<APP_SERVICE>` e `<WORKER_SERVICE>`;
- versão de Python/Node e comandos de build;
- `DATABASE_URL`, política de pool e retenção;
- provedor de e-mail;
- integrações de pagamento, mapas, armazenamento e OAuth;
- responsável técnico, canal de incidentes e janela de deploy;
- limites de upload, rate limit e retenção de logs;
- política de retenção/exclusão de dados e encarregado LGPD.

**Regra final:** se uma mudança não puder ser explicada, revisada, monitorada e desfeita, ela ainda não está pronta para produção.
