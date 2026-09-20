# Implantação isolada — Nabio Elege

Roteiro público adaptado ao Nabio Elege. O inventário com IP, portas/PIDs de outros projetos, serviços e resultados do servidor fica exclusivamente no registro operacional privado, fora do Git. Consulte também `regras_servidor.md` e `implementation-status.md`.

## Isolamento obrigatório

- Usar o `origin` deste repositório, nunca o repositório de outro projeto.
- Criar usuário sem login interativo, diretório, serviços, banco, papéis PostgreSQL, cache/fila e credenciais exclusivos do Nabio Elege.
- Preencher `APP_ROOT`, `APP_USER`, `APP_SERVICE`, `WORKER_SERVICE`, `DEPLOY_DOMAIN` e `APP_PORT` no inventário privado após auditoria somente leitura.
- Selecionar porta apenas depois de conferir processos, systemd, containers, Nginx e configurações de projetos. Escutar em 127.0.0.1; não abrir porta interna no firewall.
- Não alterar ou reiniciar outros aplicativos, bancos, contas, certificados, configurações ou portas. Se encontrar conflito, parar e investigar.
- Não publicar uploads privados por alias Nginx. Não registrar segredos nem dados pessoais em logs.

## Estrutura de cada ambiente

Cada ambiente deve possuir diretório exclusivo com `releases/<sha>`, link `current` e `shared/{media,staticfiles,logs,backups}`. A configuração fica fora da release, com permissão restritiva. Não compartilhar segredos, bancos ou documentos entre QA, staging e produção.

O processo web não pode rodar como root. O Redis deve possuir instância/credenciais próprias; usar outro número de database em instância compartilhada não fornece isolamento de credenciais.

## Configuração real da aplicação

Stack: Django, templates, Django Ninja, PostgreSQL, Celery e Redis. Usar Gunicorn fixado em `requirements-production.txt`, nunca `runserver` ou `local_settings.py` em produção.

Usar `DJANGO_SETTINGS_MODULE=nabio_elege.production_settings`. Esse perfil não lê `.env` do checkout. Fornecer pelo ambiente do serviço:

- `APP_ENV`: staging ou production.
- `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` (Fernet), `BLIND_INDEX_KEY`, `RECEIPT_TOKEN_KEY`: quatro valores fortes, independentes e exclusivos.
- `DATABASE_URL`: PostgreSQL exclusivo, papel sem superusuário.
- `REDIS_URL`, `CACHE_URL`: Redis exclusivo, autenticado e com timeouts.
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`: hosts exatos e HTTPS. Estes nomes não usam prefixo DJANGO.
- `MEDIA_ROOT` e `STATIC_ROOT`: diretórios persistentes fora da release, separados e não aninhados. Os documentos ficam em `MEDIA_ROOT/private`.
- `CLAMAV_HOST`, `CLAMAV_PORT`: antivírus privado, sem exposição pública.
- `TRUST_PROXY_HEADERS`: habilitar somente quando o proxy sobrescrever o cabeçalho de protocolo e a porta interna não estiver publicamente acessível.
- `SECURE_HSTS_SECONDS`: manter zero até confirmar HTTPS. Não habilitar includeSubDomains/preload automaticamente.

HTTPS, cookies seguros e MFA são obrigatórios no perfil de produção. As verificações de deployment recusam SQLite, cache local, segredos conhecidos de demonstração, hosts coringa e mistura entre arquivos públicos/privados. Essas verificações não substituem auditoria de segurança.

## Etapas e critérios de avanço

1. Inspecionar local e servidor sem modificações. Guardar inventário e baseline dos outros aplicativos em registro privado.
2. Executar testes SQLite/PostgreSQL, revisão por pull request e CI verde. Registrar SHA completo e aprovação. Um push não é uma aprovação de produção.
3. Validar staging separado, com dados sintéticos, HTTPS, uploads/antivírus, filas, backup/restauração e rollback. Teste isolado de banco não equivale a staging completo.
4. Revalidar porta, nomes e DNS. Criar somente recursos próprios. Instalar apenas dependências necessárias, sem upgrades globais.
5. Criar release imutável pelo SHA aprovado. Executar `python infra/check_dependency_lock.py` e instalar com `python -m pip install -r requirements-production.lock`. O lock força hashes, índice oficial e wheels; nenhuma instalação global.
6. Criar backup específico antes de alterações/migrations. Registrar UTC, SHA, tamanho e checksum. Conferir com pg_restore e testar restauração em banco isolado; nunca sobrescrever um banco existente.
7. Executar `check --deploy`, `makemigrations --check --dry-run`, testes e `collectstatic --noinput`. Conferir `migrate --plan` antes de aplicar.
8. Executar `manage.py check_runtime --settings=nabio_elege.production_settings`. Verificar também workers/scheduler e suas filas.
9. Ativar somente os serviços próprios sem root, conferir bind/PID/propriedade e trocar `current` atomicamente. Recarregar graciosamente apenas o serviço afetado.
10. Criar apenas o site Nginx do Nabio Elege. Executar `nginx -t` antes de reload. Não alterar sites existentes.
11. Com DNS correto e conta ACME autorizada, emitir certificado exclusivo. Validar cadeia, nome, validade, redirecionamento e renovação desse certificado, sem tocar nos demais.
12. Criar operador inicial com credencial exclusiva, troca obrigatória, MFA e vínculo/papel explícito. `is_superuser` não concede acesso às campanhas; `/admin/` não é a interface do produto.
13. Verificar login/logout, isolamento, fluxos principais, desktop/celular, console, uploads e saúde interna/externa. Repetir baseline dos outros projetos e registrar o resultado.

## Saúde e manutenção

`/healthz/` é liveness mínimo, sem consulta ao banco ou exposição de infraestrutura. O comando `check_runtime` verifica banco, migrations, cache, broker e ClamAV, apresentando somente nomes dos componentes e resultado. Ele não certifica worker ativo, segurança ou backup.

Celery Beat agenda expiração de reservas a cada 60 segundos. Alternativa explícita: `manage.py expire_stock_reservations`, com o perfil correto. A rotina é idempotente e não modifica campanhas arquivadas ou organizações suspensas.

Monitorar serviços, filas/outbox, latência, erros, espaço em disco, backups e validade TLS. Não encaminhar logs a provedores externos sem a governança exigida.

## Rollback

Manter a release anterior e registrar o destino de `current` antes da ativação. Em falha, restaurar atomicamente o link para uma release compatível e recarregar somente o serviço próprio; repetir os testes de saúde. Não reverter migrations cegamente nem restaurar banco por cima de produção. Preferir correção compensatória com procedimento aprovado e preservar evidências.

## Estado desta preparação

Não há declaração de publicação concluída. A falha anterior de PostgreSQL foi reproduzida e corrigida: o teste de download fechava a resposta diretamente, encerrando a conexão da transação de teste; agora consome e verifica o stream pelo cliente de testes do Django.

Evidências de 2026-09-20 para `fae5f0b2569427251e154641fb30421dbfda60a3`:

- [CI aprovada nas três combinações](https://github.com/iamnothuman7/nabio-elege/actions/runs/35541254447): SQLite/Python 3.11, PostgreSQL 14/Python 3.12 e PostgreSQL 15/Python 3.12. A suíte tem 92 testes; os dois testes concorrentes são exclusivos de PostgreSQL.
- QA PostgreSQL: os 92 testes passaram, sem skips. A validação permaneceu isolada e sem publicação pública da aplicação; os detalhes operacionais estão exclusivamente no registro privado.
- O ensaio de backup/restauração em QA passou. Trata-se de schema/dados sintéticos, não de recuperação integral de produção, arquivos privados, segredos ou cópia externa. Caminhos, tamanhos, checksums e inventário não são publicados neste relatório.
- A demonstração local recebeu a migration 0005 após backup próprio. Nenhum banco preexistente foi apagado ou sobrescrito. Os auxiliares temporários de autenticação foram removidos após o uso.

`infra/validate_isolated.py --commit <sha-completo>` provisiona QA uma única vez. `--existing` valida outra revisão em um banco novo por SHA, recusando alvos existentes e preservando evidências; não usar como ferramenta de produção. O script deliberadamente não apaga bancos de testes.

A branch `codex/inventory-production-readiness` está publicada. O PR ainda precisa ser aberto e aprovado por revisor independente; push e CI não equivalem a aprovação. O código agora inclui lock com hashes, scanners e validação de templates/assets. Staging completo, restauração completa, rollback, TLS, antivírus, monitoramento e infraestrutura exclusiva de produção continuam pendentes. As pendências funcionais constam em `implementation-status.md`.

## Primeiro operador e atualização de segurança

Depois de backup, revisão e migrations, executar `manage.py bootstrap_operator` no ambiente correto. O comando exige `--tenant-name`, `--tenant-slug`, `--campaign-name`, `--campaign-code`, `--election-id`, `--office-code`, `--jurisdiction-code`, `--username` e um ou mais `--permission CODIGO`. Escolher os códigos aprovados para aquela função; não copiar todos indiscriminadamente.

A senha inicial é solicitada sem eco, com confirmação, validação e mínimo de 12 caracteres. A opção `--password-stdin` existe para integração com entrada protegida de um gerenciador de segredos; nunca colocar senha em shell history, argumento, arquivo versionado ou relatório. O comando recusa organização/usuário existente e não cria privilégios staff/superuser. O primeiro login leva a `/senha/`, depois ao MFA exigido pelo perfil de produção. Não criar contas reais antes de definir seus responsáveis e permissões.

As migrations 0006/0007 são aditivas. A 0007 limita os casos existentes ao autor/responsável com vínculo ativo, sem conceder acesso geral ao jurídico. Conferir a atribuição antes de liberar o ambiente; casos órfãos permanecem negados. Não fazer rollback para código anterior ao controle por caso com dados sensíveis: essa versão antiga não aplica a nova proteção. Usar correção adiante ou uma release compatível que mantenha o controle.

A CI produz um arquivo de código rastreado por Git e checksum somente após testes e scanners. Isso não publica a aplicação nem contém configuração privada, banco ou uploads. A auditoria de dependências procura vulnerabilidades conhecidas; não certifica ausência de falhas.

Referência: [checklist oficial de deployment do Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
