# Estado de implementação

Atualizado em 2026-09-20. “Parcial” significa que há interface ou fluxo executável, mas o módulo ainda não atende todos os requisitos e critérios de aceite da especificação v1.0. A demonstração contém dados fictícios e não está homologada para produção.

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

O mapa utiliza apenas comitês e outros pontos operacionais declarados públicos. Ele não mostra domicílios, contatos ou preferências individuais. Cabos eleitorais são gerenciados como equipe: vínculo operacional, território, base, treinamento e escala; não recebem perfis ou pontuações de persuasão de eleitores.

Os dados de demonstração não indicam candidatura, partido, número ou data eleitoral reais. Fortaleza é uma região ilustrativa inicial, editável pelo usuário.

## Bloqueios para piloto com dados reais

- Provisionar HTTPS, segredos independentes, PostgreSQL, Redis, workers, armazenamento privado, backups e ClamAV real. A demonstração SQLite não serve como produção.
- Implementar e homologar RLS no PostgreSQL; ampliar testes concorrentes. Dois testes concorrentes de estoque passaram no PostgreSQL real (saída concorrente e recebimento idempotente), mas não representam uma auditoria completa de concorrência.
- Completar confirmação de canais, governança de finalidades, treinamento e direitos de privacidade; implementar retenção, bloqueio legal e descarte também em backups.
- Homologar orçamento comprometido, alçadas, documentos obrigatórios, arrecadação, regras contábeis e formatos oficiais com responsáveis qualificados. Não há certificação ou transmissão ao TSE.
- Homologar o novo controle de acesso por caso jurídico e completar cotações e versionamento de dados bancários. Transferências em trânsito e expiração de reservas já estão implementadas; a homologação ampla de concorrência permanece necessária.
- Dimensionar mapas para o tráfego previsto e selecionar provedor de tiles apropriado; o mapa demonstrativo depende de serviços externos.
- Concluir exportações assíncronas volumosas, armazenamento de auditoria externo e monitoramento operacional.
- Executar testes de carga, restauração, segurança e acessibilidade e homologar os dois ciclos completos da especificação.

## Evidências e limites da validação

### Continuação: contas, jurídico e cadeia de entrega

- Troca de senha exige senha atual, validação da nova senha e segundo fator fresco quando já habilitado. Revoga outras sessões, limita tentativas e registra auditoria sem segredos. O operador inicial deve trocar a senha antes de acessar campanhas e, em produção, cadastrar MFA.
- `bootstrap_operator` cria organização, campanha, papel e vínculo somente quando os alvos não existem, com permissões especificadas individualmente, sem staff/superusuário. Não imprime a senha nem aceita senha em argumento de comando.
- Cada caso jurídico exige uma concessão além do papel da campanha. Administradores de acesso podem conceder/revogar, mas não remover o último administrador ativo. Documento associado a vários casos exige acesso a todos eles. A migration inicial preserva apenas autor/responsável ativos dos casos existentes; casos sem esses vínculos ficam inacessíveis até regularização administrativa revisada.
- Instalação de produção usa `requirements-production.lock`, com 34 dependências fixadas (uma condicional para Windows), hashes de wheels do PyPI e proibição de builds de código-fonte. A CI recusa divergência entre entradas e lock.
- CI ampliada com análise estática, formato dos novos módulos, auditoria de dependências, Gitleaks no histórico, compilação de templates, collectstatic e artefato de código por SHA após os testes. As únicas exceções do scanner são fingerprints históricos das chaves intencionais de teste/demo, nunca caminhos inteiros.
- Todos os campos expostos pelos módulos têm rótulos explícitos em português; um teste impede a inclusão de campos sem tradução. A administração jurídica exige escolher a pessoa, sem selecionar um destinatário automaticamente.

Validação local desta entrega: **123 testes, nenhum erro, dois testes concorrentes ignorados no SQLite**; 26 templates compilados; migrations aplicadas apenas à demonstração, após backup. A auditoria das dependências fixadas não encontrou vulnerabilidades conhecidas, e o scanner de segredos passou com as exceções históricas documentadas. Esses resultados são verificações pontuais, não uma certificação de segurança.

O commit principal desta entrega é `b4a6270c1ecfc5959a16846abc376650017b757c`. O envio ao GitHub foi tentado, mas está bloqueado pela ausência de credencial de autenticação neste computador. **A nova CI ainda não foi executada e esta versão não foi validada no PostgreSQL.** Não houve alteração do banco, dos serviços ou da configuração de produção nesta etapa.

Essas mudanças ainda precisam de revisão independente e staging completo. Controle por caso na aplicação não substitui RLS no PostgreSQL, que continua pendente.

### Evidência da entrega anterior — não substitui a validação atual

A continuação acrescentou 18 testes de distribuição/estoque, outro teste concorrente, seis testes de proteção de implantação e cinco verificações do provisionamento isolado. A falha anterior de PostgreSQL foi reproduzida e corrigida no encerramento do stream pelo cliente de testes. A versão `fae5f0b2569427251e154641fb30421dbfda60a3` passou nos 92 testes do QA PostgreSQL 14 e na [CI SQLite/PostgreSQL 14/PostgreSQL 15](https://github.com/iamnothuman7/nabio-elege/actions/runs/35541254447). Os dois testes concorrentes são ignorados somente na combinação SQLite.

O roteiro adaptado e as evidências públicas estão em `producao.md`. O inventário e o detalhamento operacional permanecem fora do Git. A restauração de schema/dados sintéticos de QA foi verificada em banco novo; não equivale à recuperação completa de produção. Não há serviço público do Nabio Elege ativado.

Há testes automatizados para páginas dos módulos, isolamento, permissões, aprovação independente, idempotência, versões concorrentes, estoque, compras, finanças, formulários, documentos, MFA, mapas e cadastros voluntários. As verificações de antivírus em testes usam simulação; é necessário testar uma instalação real. A interface e os tiles foram conferidos em navegador desktop e em viewport móvel. Revisão independente, staging, homologação de segurança e demais critérios das regras de produção continuam necessários; testes verdes não certificam o sistema inteiro.

## Próximas etapas, na ordem de liberação

1. Autenticar o GitHub, enviar a branch e validar a CI desta versão em SQLite/PostgreSQL 14/PostgreSQL 15; abrir PR para revisor independente identificado pelo responsável do projeto.
2. Completar RLS e demais lacunas de segurança, privacidade e regras de negócio relacionadas acima; registrar os critérios de aceite e as evidências por módulo.
3. Provisionar e homologar staging isolado, inclusive antivírus real, filas, arquivos privados, recuperação integral e rollback. A evidência anterior de banco sintético não cobre esse aceite.
4. Obter a aprovação exigida, confirmar domínio e recursos exclusivos e só então realizar a implantação de produção. Nenhum serviço de outro projeto pode ser alterado por essa entrega.
