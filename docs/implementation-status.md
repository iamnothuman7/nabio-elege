# Estado de implementação

Atualizado em 2026-09-22. “Parcial” significa que há interface ou fluxo executável, mas o módulo ainda não atende todos os requisitos e critérios de aceite da especificação v1.0. A demonstração contém dados fictícios; a publicação no domínio de produção não equivale a homologação integral para dados reais.

**Estado operacional vigente:** domínio público com HTTPS/HSTS, infraestrutura isolada e contas de plataforma/demo disponíveis na revisão `b3823fa`, com criação de usuários adicionais, métricas operacionais de landing/clientes e filtros de atividade. CI, staging, antivírus real e rollback compatível passaram; consulte [as evidências atuais](superadmin-usage.md). A infraestrutura antes listada como não provisionada nos registros históricos abaixo já foi instalada e validada conforme [produção](producao.md). Permanecem as lacunas funcionais, revisão independente, homologação para dados reais, recuperação automática por canal verificado, histórico analítico durável, backup/alertas externos e testes amplos de carga/acessibilidade. Os registros históricos não devem ser interpretados como estado operacional atual.

| Módulo | Estado | Entrega disponível |
| --- | --- | --- |
| M01 Campanhas e organizações | Parcial | Tenant, fases, vínculos, convites, MFA, troca de senha com revogação de sessões e bootstrap de operador com permissões explícitas |
| M02 Central de comando | Parcial | Painel eleitoral, candidatura, territórios e mapa operacional interativo |
| M03 Projetos e tarefas | Parcial | CRUD, dependências, evidência e transições de execução |
| M04 Financeiro e orçamento | Parcial | Versões de orçamento, linhas, aprovação independente, obrigações, pagamentos, estornos e conciliação |
| M05 Arrecadação | Parcial | Cadastro de recebimentos financeiros e estimáveis; regras completas pendentes |
| M06 Contabilidade | Parcial | Manifesto com hash, revisão, exportação JSON e protocolo de entrega externa |
| M07 Compras e fornecedores | Parcial | Itens, solicitação, pedido aprovado, obrigação canônica e recebimento parcial em estoque |
| M08 Jurídico | Parcial | Casos, responsáveis, revisão e concessões por caso; bloqueios propagados a documentos, seletores, ocorrências e auditoria |
| M09 Calendário regulatório | Parcial | Prazos e acompanhamento manual; sem sincronização normativa |
| M10 Estoque | Parcial | Entradas/saídas, reservas com expiração automática, transferências em trânsito, recebimento parcial e devolução com conferência independente |
| M11 Patrimônio | Parcial | Bens e custódias com prevenção de conflito de período |
| M12 Logística | Parcial | Viagens, responsáveis e prevenção de sobreposição de recursos |
| M13 Equipes | Parcial | Papéis, revogação, cabos eleitorais, voluntários, treinamento, escalas e presença |
| M14 Pessoas | Parcial | Contatos cifrados, cadastro voluntário de eleitores, finalidade, comprovação, responsável e revisão |
| M15 Agenda e eventos | Parcial | Eventos e ações de rua por território/comitê, equipe necessária e checklist |
| M16 Resultados públicos | Parcial | Importação CSV agregada com métricas permitidas, validação e rastreabilidade |
| M17 Comunicação | Parcial | Conteúdo editorial, revisão segregada e referência da publicação externa |
| M18 Estúdio | Parcial | Acervo de marca e revisão; pipeline completo de produção pendente |
| M19 Atendimento | Parcial | Recepção pública/assistida, protocolo, responsável, acesso restrito e acompanhamento |
| M20 Propostas | Parcial | Cadastro, responsável, prazo e revisão |
| M21 Documentos | Parcial | Upload privado, validação de tipo, hash, ClamAV fail-closed e download autorizado |
| M22 Dia da eleição | Parcial | Escalas, conflitos de horário e registro de ocorrências |
| M23 Relatórios e auditoria | Parcial | CSV protegido contra fórmulas, auditoria de aplicação e outbox/inbox |
| M24 Encerramento | Parcial | Checklist, bloqueios de fechamento e arquivo somente leitura; retenção integral pendente |
| M25 Formulários por link | Parcial | Construtor controlado, versão/aviso, revisão independente, publicação, links, pausa e envio idempotente |

## Escopo eleitoral implementado

O cadastro de eleitores é voluntário e administrativo, não uma lista comprada nem uma base de intenção de voto. Os registros manuais entram pendentes, com finalidade e evidência; revisão não substitui a confirmação externa do canal. Nomes e contatos ficam cifrados e o acesso é limitado ao responsável ou a uma permissão global explícita da campanha. A busca exata de contato utiliza POST para não expor o dado em URLs.

O mapa navega por Brasil, regiões, UFs e municípios, com limites simplificados e distritos da API do IBGE. Bairros e comunidades podem ser desenhados pela equipe, com fonte e confirmação de área pública; não são apresentados como uma base oficial nacional completa. Os pontos operacionais são comitês e outros locais declarados públicos. Não aparecem domicílios, contatos ou preferências individuais. Cabos eleitorais são gerenciados como equipe: vínculo operacional, território, base, treinamento e escala; não recebem perfis ou pontuações de persuasão de eleitores.

Os dados de demonstração não indicam candidatura, partido, número ou data eleitoral reais. Fortaleza é uma região ilustrativa inicial, editável pelo usuário.

## Bloqueios para piloto com dados reais

- Provisionar HTTPS, segredos independentes, PostgreSQL, Redis, workers, armazenamento privado, backups e ClamAV real. A demonstração SQLite não serve como produção.
- Homologar o RLS já implementado em 73 tabelas PostgreSQL, configurar papéis separados e ampliar testes concorrentes. A suíte de isolamento passou com papel restrito no PostgreSQL 17.10; isso não substitui revisão independente nem validação da topologia de produção. Ver `rls.md` para limites e incompatibilidade de rollout com código antigo.
- Configurar e homologar recuperação de senha por canal verificado. A tela de ajuda não simula envio de e-mail e não existe recuperação automática nesta versão. Homologar também os limitadores de acesso atrás do proxy real.
- Completar confirmação de canais, governança de finalidades, treinamento e direitos de privacidade; implementar retenção, bloqueio legal e descarte também em backups.
- Homologar orçamento comprometido, alçadas, documentos obrigatórios, arrecadação, regras contábeis e formatos oficiais com responsáveis qualificados. Não há certificação ou transmissão ao TSE.
- Homologar o novo controle de acesso por caso jurídico e completar cotações e versionamento de dados bancários. Transferências em trânsito e expiração de reservas já estão implementadas; a homologação ampla de concorrência permanece necessária.
- Dimensionar mapas para o tráfego previsto e selecionar provedor de tiles apropriado; o mapa demonstrativo depende de serviços externos.
- Concluir exportações assíncronas volumosas, armazenamento de auditoria externo e monitoramento operacional.
- Executar testes de carga, restauração, segurança e acessibilidade e homologar os dois ciclos completos da especificação.

## Evidências e limites da validação

### Identidade oficial — 2026-09-21

- Logo fornecida pelo proprietário incorporada sem alteração do PNG; hash e dimensões protegidos por teste. Versão colorida sobre branco, versão inteiramente branca por CSS sobre verde, com transparência e proporção preservadas.
- Verdes extraídos do arquivo: `#117444` e `#42B04A`. Tokens comuns aplicados à landing page, acesso, painel e formulários públicos. Símbolo original enquadrado para os elementos decorativos 3D; nenhum lettering foi recriado.
- Seis novos testes verificam o ativo, variantes, nome acessível, integração nos templates e contraste dos principais pares de texto. A suíte SQLite executou **184 testes, sem falhas, com 23 skips exclusivos de PostgreSQL**. Compilados **29 templates** e verificado o empacotamento dos dois novos arquivos estáticos; análise estática aprovada.
- Login e landing page inspecionados em navegador desktop e em largura móvel; carregamento da imagem, variantes de cor e interação das abas conferidos. Isso não substitui auditoria completa de acessibilidade ou homologação do painel autenticado.
- Regras de aplicação documentadas em `docs/identidade-visual.md`. Esta entrega visual não altera os bloqueios de produção nem declara conclusão dos módulos parciais.

### Publicação no Git e preparação de produção — 2026-09-21

- O envio ao GitHub foi concluído selecionando explicitamente a conta já autorizada para este repositório. A branch `codex/inventory-production-readiness` foi publicada e o [PR #1](https://github.com/iamnothuman7/nabio-elege/pull/1) está aberto para revisão independente. Não houve merge nem autoaprovação.
- A [CI do commit 8386270](https://github.com/iamnothuman7/nabio-elege/actions/runs/35598541670) passou em SQLite/Python 3.11, PostgreSQL 14/15/Python 3.12, scanners e artefato de release. Cada nova revisão do PR precisa passar novamente pelos mesmos checks.
- Acrescentada identificação de origem por proxy explícito: `X-Real-IP` só é aceito de IPs exatos configurados, sem confiar em cadeias `X-Forwarded-For`. Limitadores de login e formulário continuam ativos. Cabeçalhos de segurança e `no-store` também cobrem bloqueios e redirecionamentos.
- Os 12 testes novos de proxy passaram; a suíte local chegou a **178 testes com 23 skips de PostgreSQL**, sem erros. Novamente verificados 28 templates, análise estática e ausência de migrations pendentes. O fragmento Nginx é um exemplo revisável, não uma configuração instalada.
- Nova auditoria SSH somente leitura confirmou ausência dos ambientes web de produção/staging do Nabio Elege, falha na validação TLS do domínio e antivírus próprio ainda não confirmado. Os serviços dos outros projetos continuaram ativos, sem reinício ou alteração. Inventário privado permanece fora do Git.

**Bloqueios de liberação:** indicar revisor e obter aprovação independente do PR; completar staging com TLS, filas, antivírus, papéis separados, restauração e rollback; homologar os requisitos funcionais/privacidade pendentes abaixo. Acesso SSH e CI verde não equivalem a produto completo nem autorizam ignorar essas etapas.

### Continuação: login, apresentação, mapa nacional e isolamento

- Landing page pública em `/produto/` e na página inicial anônima, com composição 3D em CSS, respeito à redução de movimento, abas por teclado, perguntas frequentes e avisos explícitos de produto em desenvolvimento. Não inclui preços, clientes ou certificações fictícias.
- Login redesenhado em `/entrar/`, responsivo, com mostrar/ocultar senha, aviso de Caps Lock, usuário preservado após erro, senha nunca devolvida e mensagens genéricas. Mantém CSRF, limites de tentativas, troca obrigatória, MFA, convites e revogação de sessões. `/ajuda-acesso/` esclarece os limites da recuperação.
- Navegação nacional com seleção de região/UF/município, busca local, camadas, ampliação e desenho de áreas públicas. Geometrias são limitadas a 200 vértices, validadas contra cruzamentos e gravadas com idempotência e permissão de campanha. O proxy IBGE tem URLs fixas, cache público, timeout, limites de tamanho comprimido/descomprimido e recusa redirecionamentos.
- RLS habilitado e forçado, contexto transacional no servidor, roteamento público por token e workers com campanha explícita. Auditoria jurídica da API agora respeita a mesma visibilidade por caso da interface. Implementação de isolamento registrada no commit `993417b`.
- **166 testes passaram em PostgreSQL 17.10/Python 3.11**, em cluster local exclusivo e bancos sintéticos novos. A mesma suíte passou em SQLite com **23 skips esperados** (21 de RLS e dois de concorrência). Compilação de **28 templates**, `collectstatic` de 146 arquivos, análise estática, sintaxe dos quatro scripts JavaScript novos/alterados e ausência de migrations pendentes também verificadas.
- Consulta real ao IBGE conferiu 27 UFs, 184 municípios/limites no Ceará e limite/distritos de Fortaleza. Login e landing page conferidos visualmente em desktop e celular; alternância de senha, erro, limpeza da senha e abas por teclado verificados. A inspeção visual autenticada do novo mapa continua pendente: a sessão local anterior expirou e não foi substituída sem o usuário.
- Backup local antes de aplicar `core.0002` e `workspace.0008` à demonstração SQLite. Nenhum recurso de produção foi alterado. O provisionador legado de QA está bloqueado antes de efeitos; não elevar privilégios de uma conta no servidor compartilhado para executar testes de RLS.

A recuperação automática por e-mail, revisão independente, staging completo e critérios de produção continuam pendentes. A validação local não autoriza publicação de dados reais. O bloqueio de envio ao GitHub foi resolvido na etapa registrada acima.

### Continuação: contas, jurídico e cadeia de entrega

- Troca de senha exige senha atual, validação da nova senha e segundo fator fresco quando já habilitado. Revoga outras sessões, limita tentativas e registra auditoria sem segredos. O operador inicial deve trocar a senha antes de acessar campanhas e, em produção, cadastrar MFA.
- `bootstrap_operator` cria organização, campanha, papel e vínculo somente quando os alvos não existem, com permissões especificadas individualmente, sem staff/superusuário. Não imprime a senha nem aceita senha em argumento de comando.
- Cada caso jurídico exige uma concessão além do papel da campanha. Administradores de acesso podem conceder/revogar, mas não remover o último administrador ativo. Documento associado a vários casos exige acesso a todos eles. A migration inicial preserva apenas autor/responsável ativos dos casos existentes; casos sem esses vínculos ficam inacessíveis até regularização administrativa revisada.
- Instalação de produção usa `requirements-production.lock`, com 34 dependências fixadas (uma condicional para Windows), hashes de wheels do PyPI e proibição de builds de código-fonte. A CI recusa divergência entre entradas e lock.
- CI ampliada com análise estática, formato dos novos módulos, auditoria de dependências, Gitleaks no histórico, compilação de templates, collectstatic e artefato de código por SHA após os testes. As únicas exceções do scanner são fingerprints históricos das chaves intencionais de teste/demo, nunca caminhos inteiros.
- Todos os campos expostos pelos módulos têm rótulos explícitos em português; um teste impede a inclusão de campos sem tradução. A administração jurídica exige escolher a pessoa, sem selecionar um destinatário automaticamente.

Validação histórica anterior ao RLS: **123 testes, nenhum erro, dois testes concorrentes ignorados no SQLite**; 26 templates compilados; migrations aplicadas apenas à demonstração, após backup. A auditoria das dependências fixadas não encontrou vulnerabilidades conhecidas, e o scanner de segredos passou com as exceções históricas documentadas. Esses resultados são verificações pontuais, não uma certificação de segurança.

O commit principal da entrega anterior é `b4a6270c1ecfc5959a16846abc376650017b757c`. Naquela etapa, o envio ao GitHub estava bloqueado pela seleção de credencial. Os testes PostgreSQL locais e a nova CI foram executados nas continuações acima. Não houve alteração do banco, dos serviços ou da configuração de produção nessas etapas.

Essas mudanças ainda precisam de revisão independente e staging completo. Controle por caso na aplicação complementa o RLS PostgreSQL; nenhum deles constitui homologação integral do produto.

### Evidência da entrega anterior — não substitui a validação atual

A continuação acrescentou 18 testes de distribuição/estoque, outro teste concorrente, seis testes de proteção de implantação e cinco verificações do provisionamento isolado. A falha anterior de PostgreSQL foi reproduzida e corrigida no encerramento do stream pelo cliente de testes. A versão `fae5f0b2569427251e154641fb30421dbfda60a3` passou nos 92 testes do QA PostgreSQL 14 e na [CI SQLite/PostgreSQL 14/PostgreSQL 15](https://github.com/iamnothuman7/nabio-elege/actions/runs/35541254447). Os dois testes concorrentes são ignorados somente na combinação SQLite.

O roteiro adaptado e as evidências públicas estão em `producao.md`. O inventário e o detalhamento operacional permanecem fora do Git. A restauração de schema/dados sintéticos de QA foi verificada em banco novo; não equivale à recuperação completa de produção. Não há serviço público do Nabio Elege ativado.

Há testes automatizados para páginas dos módulos, isolamento, permissões, aprovação independente, idempotência, versões concorrentes, estoque, compras, finanças, formulários, documentos, MFA, mapas e cadastros voluntários. As verificações de antivírus em testes usam simulação; é necessário testar uma instalação real. A interface e os tiles foram conferidos em navegador desktop e em viewport móvel. Revisão independente, staging, homologação de segurança e demais critérios das regras de produção continuam necessários; testes verdes não certificam o sistema inteiro.

## Próximas etapas, na ordem de liberação

1. Indicar revisor independente para o PR #1 e obter sua aprovação sobre a revisão final, mantendo CI verde em SQLite/PostgreSQL 14/PostgreSQL 15.
2. Homologar o RLS implementado e completar as demais lacunas de segurança, privacidade e regras de negócio relacionadas acima; registrar os critérios de aceite e as evidências por módulo.
3. Provisionar e homologar staging isolado, inclusive antivírus real, filas, arquivos privados, recuperação integral e rollback. A evidência anterior de banco sintético não cobre esse aceite.
4. Obter a aprovação exigida, confirmar domínio e recursos exclusivos e só então realizar a implantação de produção. Nenhum serviço de outro projeto pode ser alterado por essa entrega.
