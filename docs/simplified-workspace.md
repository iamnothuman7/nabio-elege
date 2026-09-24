# Cadastros simples e ajuda contextual — 24/09/2026

## Alterações

- Ajuda `?` nas telas dos módulos e nos campos com orientação específica: mouse,
  foco de teclado, clique/toque, Escape e fechamento ao sair/rolar. Conteúdo
  escapado pelo template, sem scripts inline ou serviços externos.
- Espaçamento responsivo: formulários de uma ou duas colunas, largura útil maior
  em desktop, campos com altura mínima e tabelas com rolagem interna quando
  necessário. Detalhes avançados permanecem acessíveis, inclusive seus erros.
- Materiais: atalho diário para entrada/saída/devolução, saldo e últimos movimentos.
  Fornecedores permanecem separados; compras, reservas e remessas ficam avançadas.
  Nome basta para criar um material; código gerado e unidade `un` são padrões
  explícitos. Observação opcional; quantidade e material obrigatórios. Um único
  depósito é usado automaticamente; vários exigem escolha. Sem depósito, o
  estoque principal só é criado na primeira movimentação válida. Reservas,
  saldo não negativo, escopo, CSRF e idempotência continuam no servidor.
- Eleitores: nome, cidade, primeira vez votando (desconhecido/sim/não) e título
  opcional. Contatos, responsável e referência ficam em detalhes opcionais.
  Uma única finalidade ativa **já utilizada em cadastros da campanha** pode ser
  reutilizada automaticamente; nenhuma finalidade/base legal é criada ou ativada.
  No primeiro uso, ou havendo várias, a escolha continua explícita. Os campos
  `first_vote` e `voter_title` precisam estar autorizados em `allowed_fields`.
  Título recebe criptografia de campo; nunca vai para listas, mapas, URLs, logs
  ou exportações genéricas. A consulta detalhada respeita atribuição e auditoria.
  Validação do título é apenas de formato (12 dígitos), não consulta oficial.
- A declaração de maioridade do fluxo atual e a solicitação real de cadastro
  continuam necessárias. Sem referência externa, o registro informa apenas a
  declaração do operador e permanece pendente de conferência independente.
  “Cadastro conferido” não significa preferência, intenção ou confirmação de voto.
- Pontos de apoio: latitude/longitude podem ser ambas vazias; par incompleto ou
  fora de faixa é rejeitado. Os locais sem coordenadas permanecem na lista e
  aparecem como pendentes de localização, não como marcadores em `0,0`.
  A confirmação de local público de operação continua necessária.
- Acessos: gestor e plataforma podem selecionar permissões nomeadas, agrupadas
  por área. Nenhuma selecionada implicitamente; dependências precisam ser
  marcadas. Cada acesso ganha um papel individual. Não modifica papéis, senhas
  nem permissões existentes. Delegação é revalidada no servidor como subconjunto
  das permissões do gestor. Algumas capacidades abrangem vários módulos e seus
  rótulos explicitam isso (ex.: projetos/tarefas, estoque/reservas/remessas).
  Novas contas seguem a política atual de troca inicial e MFA; exceções existentes
  de `elege.admin` e `elege.tiago` não são ampliadas nem alteradas.

## Validações locais

- 272 testes Django; 23 específicos de PostgreSQL pulados apenas no SQLite.
- 10 testes Node de interações, incluindo ajudas e regressões do menu/CEP.
- 44 templates compilados; lint de erros críticos e verificação de migrations.
- Navegador com banco SQLite dedicado e dados fictícios: cinco telas
  (materiais, eleitor, material, comitê, equipe) × cinco larguras
  (360/390/820/1024/1920), sem overflow horizontal da página.
- Entrada de estoque no navegador passou de 75 para 80 unidades, com histórico.
- Ajuda por clique/toque e Escape, leitura no desktop, coluna única no celular
  e agrupamento de permissões no tablet. Emulação de dimensões não substitui
  testes em aparelhos físicos e leitores de tela.

## Publicação e retorno seguro

1. Publicar primeiro `9d65102dec71755fe9a8224a11b73d070c3a9ed4`, leitor compatível
   com pontos sem coordenadas, sem alterar o banco.
2. Validar CI e staging da versão final, incluindo PostgreSQL 14/15, isolamento,
   banco migrado e retorno ao leitor compatível.
3. O controlador padrão continua recusando migrations. A opção explícita
   `--registration-expansion` aceita apenas `workspace.0009_simpler_registration`,
   com hash de arquivo fixado, plano exato, leitor compatível ativo, backup
   criptografado verificável e timeouts de lock/comando.
4. A migration adiciona duas colunas nullable e permite coordenadas nulas.
   Não reescreve registros, não muda contas, não aprova finalidades e não apaga
   histórico. Mantém políticas RLS existentes, sem novas tabelas.
5. Se a ativação falhar, voltar somente o código e os assets ao leitor compatível;
   manter as colunas novas, sem desfazer migrations ou restaurar banco sobre dados
   recebidos durante a operação.
6. Produção depende dos gates do projeto, revisão e validação da revisão exata
   em staging. Este documento não é um comprovante de publicação em produção.

## Resultado registrado às 19:20 UTC

- Código: `ee51972561e39857e98496072749dc073adafae4`.
- CI completo aprovado, incluindo PostgreSQL 14/15, segurança e artefato:
  [execução 36046307189](https://github.com/iamnothuman7/nabio-elege/actions/runs/36046307189).
- Staging: migration aplicada; RLS, dependências e revisão dos workers conferidos.
  Regressão HTTPS: 105 requisições gerais + 51 plataforma + 17 acesso direto.
  Teste extra: 116 requisições, incluindo material apenas com nome, depósito
  automático, entrada/saída, reenvio idempotente, saldo insuficiente, ponto sem
  coordenadas e criação de acesso com uma única permissão.
- A primeira tentativa do teste extra usou `municipality` como tipo de território,
  opção inexistente. Corrigida apenas a massa de teste para `operation`; a versão
  da aplicação não precisou mudar. O teste extra completo então passou.
- Rollback de código ao leitor `9d65102` e retorno a `ee51972` verificados no
  staging, com os workers nas respectivas revisões. Um ponto sem coordenadas foi
  lido com isolamento nas duas versões, sem mudar os dados ou desfazer a migration.
- Backup criptografado final do staging: `20260924T192045Z-complete`, no servidor.
- Staging desligado após os testes. Nenhum serviço de outro projeto ou Nginx
  alterado. Produção continua em `2de3282a04a3c1473824c41338a828830193c3aa`, saudável;
  contas existentes preservadas. A aprovação da revisão para produção foi solicitada.

Para a futura publicação, promover primeiro o leitor compatível em produção,
usando o comprovante arquivado de staging da revisão `9d65102`. A validação atual
`application-validated.json` refere-se a `ee51972`; não deve ser apresentada como
validação de outro SHA nem dispensar o gate. Preservar os dois comprovantes e
registrar qualquer seleção do comprovante histórico antes de executar o rollout.
Depois promover `ee51972` com a opção explícita de expansão, novo backup e
verificações pós-publicação. Não usar o procedimento antigo de aplicação apenas
diretamente sobre `2de3282`, pois ele não contém o leitor compatível.
