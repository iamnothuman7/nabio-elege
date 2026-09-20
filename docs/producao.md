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
5. Criar release imutável pelo SHA aprovado. Concluir lock de dependências com hashes antes da instalação reproduzível exigida nas regras.
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

Não há declaração de publicação concluída. A CI anterior de PostgreSQL apresentou falha e precisa ser corrigida. Aprovação, staging completo, lock com hashes, restauração, TLS, antivírus e infraestrutura exclusiva precisam de evidências antes de go-live. As pendências funcionais constam em `implementation-status.md`.

Referência: [checklist oficial de deployment do Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
