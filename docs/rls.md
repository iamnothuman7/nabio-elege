# Isolamento PostgreSQL — implementação e limites

Atualizado em 2026-09-21. Implementado e testado localmente; **não homologado para produção**.

## O que a migration protege

`core.0002_campaign_rls` habilita e força Row Level Security em 73 tabelas de dados de campanha. As políticas verificam organização/campanha ou os pais protegidos de registros dependentes. Na ausência de contexto, o papel restrito não enxerga esses dados. A auditoria tem políticas separadas de leitura e inclusão, sem política de alteração ou exclusão.

O middleware resolve a campanha no servidor e verifica o vínculo autenticado antes de configurar os parâmetros locais da transação. Cabeçalhos de organização/campanha não definem o escopo. O contexto é restaurado em chamadas aninhadas, falhas e reutilização da conexão; streams síncronos revalidam o vínculo entre blocos. Workers recebem o identificador de campanha explicitamente. SQLite mantém limites de transação, mas **não oferece RLS**.

Metadados de identidade/roteamento permanecem fora dessa fronteira: organizações, campanhas, permissões, papéis, vínculos, perfis de segurança, limitadores de login e inbox. As tabelas do Django de autenticação e sessões também não têm RLS de campanha. Links públicos e convites têm exceções de leitura por token exato e válido para resolver a campanha. Não existem consultas públicas gerais às campanhas.

RLS não substitui autorização por endpoint, titular, finalidade ou caso jurídico. A aplicação continua verificando essas condições e a coerência das relações. Parâmetros de sessão não são uma barreira contra execução arbitrária de SQL por um invasor; prevenir injeção e proteger credenciais continuam obrigatórios. O plano atual não certifica resistência a canais laterais, vazamento por constraints, carga, streams assíncronos ou todas as formas de concorrência.

## Papéis separados e verificação

- O papel de migrations é proprietário das tabelas e nunca deve ser usado pelo web/worker.
- O papel de execução recebe apenas os privilégios necessários de conexão, uso do schema/sequências e DML. Não pode ser proprietário, membro do proprietário, superusuário, `BYPASSRLS`, `CREATEROLE`, `CREATEDB`, nem herdar associação a papéis com esses poderes.
- Não conceder `CREATE` no schema público nem `TRUNCATE` nas tabelas protegidas ao papel de execução. Rever o privilégio `CREATE` de `PUBLIC` em instalações antigas, somente no banco exclusivo da aplicação.
- Executar `manage.py check_rls` conectado com o papel real de web/worker. O comando falha fechado e também integra `check_runtime`. Verifica configuração, nomes das políticas e privilégios; **não faz uma auditoria independente das expressões SQL**.
- A suíte geral cria fixtures com privilégios de teste. Os 21 testes PostgreSQL de isolamento trocam explicitamente para um papel temporário sem privilégios de bypass. Não confundir os dois contextos nem conceder poderes de teste ao serviço de produção.

## Rollout e rollback

Não aplicar esta migration no meio de uma implantação gradual de código antigo: a versão antiga não configura o contexto de banco e deixará de ler/escrever dados. Preparar uma release de compatibilidade e homologar o rollout antes de liberar o serviço com dados reais. A implantação de primeira instalação deve ocorrer antes da abertura ao público.

Antes de ativar, registrar backup/restauração verificados, drenar filas antigas e conciliar mensagens. O processamento de submissão passa a receber dois argumentos: submissão e campanha. Mensagens antigas sem campanha são recusadas em PostgreSQL; reprocessar pelo outbox reconciliado, não abrir acesso global ao banco. Todos os workers e comandos administrativos precisam de contexto explícito.

A migration é intencionalmente irreversível. Não remover RLS nem voltar a uma release incompatível como rollback. Usar correção adiante ou release compatível aprovada, preservando políticas e evidências.

## Como testar com segurança

Usar cluster PostgreSQL **exclusivo de testes**, restrito ao loopback ou à rede interna de CI, sem dados reais. A conta de testes precisa criar banco/papéis temporários; nunca usar o cluster compartilhado de produção para isso. A CI configura PostgreSQL 14 e 15 isolados; a execução local desta etapa utilizou PostgreSQL 17.10.

Configurar `TEST_DATABASE_URL` e, quando necessário, `TEST_DATABASE_NAME` exclusivos. Executar:

```text
python manage.py test --settings=nabio_elege.postgres_test_settings --noinput --keepdb
```

Com `--keepdb`, uma suíte completa pode limpar seeds de permissões por causa de testes transacionais. Para repetir a suíte completa, preferir um banco sintético novo de nome explícito; preservar o anterior como evidência, sem apagá-lo automaticamente. O comando de teste precisa conseguir criar esse banco se ainda não existir.

`infra/validate_isolated.py` é um provisionador legado, agora bloqueado antes de qualquer efeito. Ele não separava o proprietário dos privilégios exigidos pela nova suíte. Não elevar o papel de QA no servidor compartilhado para contornar esse bloqueio. O provisionamento definitivo de staging com dois papéis permanece pendente.

Referências: [Row Security Policies do PostgreSQL](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) e [transações do Django](https://docs.djangoproject.com/en/5.2/topics/db/transactions/).
