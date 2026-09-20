# Nabio Elege

Central operacional de campanha eleitoral em Python/Django: candidatura, território, comitês, equipe de campo, agenda e gestão administrativa. A referência funcional é `docs/product/Nabio_Elege_Documentacao_v1_0.pdf`.

## O que já pode ser utilizado na demonstração

- Painel eleitoral responsivo com identidade da candidatura, agenda de rua e indicadores operacionais.
- Mapa interativo com camadas de comitês, pontos de apoio, eventos e logística, filtro territorial e acesso aos registros.
- Territórios, cabos eleitorais, voluntários, treinamento, ações de rua, escalas e registro de presença.
- Cadastro voluntário de eleitores, com nome e contatos cifrados, finalidade, responsável, comprovação e revisão independente. Não há perfilamento político, intenção de voto ou localização residencial no mapa.
- Projetos, tarefas com dependências, agenda, patrimônio, custódia, logística, jurídico, prazos, propostas, comunicação e estúdio.
- Orçamentos versionados, obrigações, aprovação segregada, pagamentos registrados, conciliação, compras com recebimento parcial, estoque e reservas.
- Formulários públicos versionados, revisão independente, links, recibos, processamento e atendimento.
- Documentos privados com quarentena e integração ClamAV, relatórios CSV, manifesto contábil verificável e auditoria.
- Equipes e permissões por campanha, convites, revogação, login limitado por tentativas, MFA TOTP e códigos de recuperação.

**Esta é uma versão funcional de desenvolvimento, não uma certificação de atendimento integral da especificação nem uma liberação para produção.** Consulte o [estado por módulo](docs/implementation-status.md) e a [lista de homologação](docs/acceptance-checklist.md).

## Demonstração local no Windows

Requisito: Python 3.11. Não precisa de PostgreSQL/Redis para a demonstração isolada.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\start-local.ps1 -PrepareDemo
```

O script pede uma senha de demonstração e prepara as contas `demo.gestor` e `demo.revisor`, necessárias para testar aprovação por uma segunda pessoa. A preparação pode ser repetida, mas redefine a senha dessas contas. Para iniciar novamente preservando os cadastros:

```powershell
.\scripts\start-local.ps1
```

Acesse <http://127.0.0.1:8020>. Os dados de Fortaleza, pessoas, equipes e endereços são **fictícios e ilustrativos**, não representam uma campanha real. A candidatura e os territórios podem ser editados pela interface.

`local_settings.py` usa `demo.sqlite3`, chaves conhecidas de desenvolvimento, cache em memória e MFA não obrigatório. Está restrito a hosts de loopback. Nunca publique esse perfil nem insira dados reais nele. A configuração normal exige MFA por padrão.

O mapa usa [Leaflet 1.9.4](https://leafletjs.com/examples/quick-start/) com integridade SRI e tiles do OpenStreetMap, exigindo internet. A atribuição permanece visível e não há download em massa/offline. Antes de disponibilizar publicamente, dimensione e configure um provedor compatível com a [política dos tiles OSM](https://operations.osmfoundation.org/policies/tiles/); o serviço comunitário não oferece SLA. A lista de pontos continua disponível se o mapa externo não carregar.

## Ambiente integrado de desenvolvimento

1. Copie `.env.example` para `.env` e configure segredos independentes.
2. Inicie PostgreSQL e Redis com `docker compose up -d`.
3. Instale `requirements.txt` em um ambiente virtual.
4. Execute `python manage.py migrate` e `python manage.py runserver`.
5. Execute `celery -A nabio_elege worker -l info` e `celery -A nabio_elege beat -l info` para processamento assíncrono.
6. Disponibilize ClamAV e configure o armazenamento privado; arquivos sem verificação positiva não são liberados para download.

Saúde pública: `/api/healthz`. A API de campanha usa sessão, CSRF e permissões explícitas; a interface principal não depende do Django Admin.

## Verificação

```powershell
python manage.py check --settings=nabio_elege.test_settings
python manage.py makemigrations --check --dry-run --settings=nabio_elege.test_settings
python manage.py test --settings=nabio_elege.test_settings
```

Os testes locais usam SQLite isolado. O cenário concorrente de estoque é executado somente no PostgreSQL; a CI contém matriz SQLite/PostgreSQL. Para rodar a variante PostgreSQL, configure `TEST_DATABASE_URL` para um banco exclusivo de testes e use `--settings=nabio_elege.postgres_test_settings`. Isso não substitui RLS, carga e homologação de concorrência de todos os fluxos.

## Limites importantes

- Não há envio de mensagens em massa, compra de listas, pontuação de eleitores ou segmentação de persuasão política.
- O mapa mostra pontos operacionais declarados públicos, nunca a localização de eleitores.
- Aprovar um cadastro assistido não equivale a verificar automaticamente e-mail/telefone.
- O sistema registra pagamentos e entrega contábil externa; não movimenta dinheiro nem transmite automaticamente ao TSE.
- Resultados públicos são agregados e importados por CSV controlado; não há integração automática com bases oficiais.
- Auditoria é protegida na aplicação, mas ainda não é um armazenamento WORM externo.
- `.env`, bases locais, documentos privados e chaves não devem ser versionados.

Consulte `regras_servidor.md` e as pendências documentadas antes de qualquer implantação real.
