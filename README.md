# Nabio Elege

Plataforma administrativa para campanhas políticas, implementada como monólito modular em Python e Django. A fonte funcional é `docs/product/Nabio_Elege_Documentacao_v1_0.pdf`.

## Estado atual

O marco R0 e as primeiras fatias verticais de R1 estão implementados. A base já contém:

- organizações e campanhas isoladas;
- vínculos, papéis e permissões por campanha;
- auditoria imutável e outbox/inbox transacional;
- documentos privados modelados com quarentena e versões;
- finalidades, avisos, formulários e versões publicáveis;
- pessoas, contatos, manifestações, supressões e atendimentos;
- obrigações, aprovações, pagamentos e alocações com valores em centavos;
- API Django Ninja autenticada por sessão;
- recebimento público e assistido com payload cifrado, idempotência e recibo opaco;
- processamento assíncrono de submissão até atendimento;
- projetos, dependências de tarefas e estoque transacional;
- contas bancárias, extratos, alocação de pagamentos e conciliação parcial;
- testes negativos de isolamento e invariantes críticas.

Esta versão ainda não está liberada para dados reais ou produção.

## Desenvolvimento local

Requisitos: Python 3.11, Docker e Docker Compose.

1. Copie `.env.example` para `.env` e substitua todos os valores locais.
2. Inicie PostgreSQL e Redis com `docker compose up -d`.
3. Crie e ative um ambiente virtual.
4. Instale as dependências com `python -m pip install -r requirements.txt`.
5. Aplique as migrações com `python manage.py migrate`.
6. Inicie a API com `python manage.py runserver`.

Para processamento assíncrono, execute também `celery -A nabio_elege worker -l info` e `celery -A nabio_elege beat -l info`.

A documentação interativa fica em `/api/docs`; a verificação pública de saúde fica em `/api/healthz`.

## Testes

```powershell
python manage.py test --settings=nabio_elege.test_settings
python manage.py check --settings=nabio_elege.test_settings
python manage.py makemigrations --check --dry-run --settings=nabio_elege.test_settings
```

Os testes usam SQLite isolado e dados fictícios. A validação de PostgreSQL, RLS, concorrência e upload real será adicionada antes de qualquer piloto.

As chaves de criptografia devem ser independentes por ambiente. Gere uma chave Fernet com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` e mantenha o resultado somente no gerenciador de segredos.

## Segurança

- Nunca versione `.env`, senhas, tokens, chaves privadas ou bases reais.
- O identificador de campanha nunca substitui autorização.
- Escritas críticas exigem transação, versão e evento de auditoria.
- Publicação de formulário é imutável; correções geram nova versão.
- O criador de uma obrigação não pode fazer sua aprovação final.
- O sistema não inicia pagamentos e não utiliza WhatsApp Business Platform neste caso de uso.

Consulte também `regras_servidor.md` antes de implantar.
