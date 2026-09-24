# Navegação e territórios — 24/09/2026

## Fluxo simplificado

- No desktop com mouse, a barra lateral mostra o símbolo oficial e os ícones.
  Passar o mouse expande; sair recolhe sem deslocar o conteúdo. O teclado também
  expande ao focar um item. Escape retorna ao conteúdo. No celular, o botão de menu
  abre a gaveta, com fechamento por botão, toque externo ou Escape.
- A posição de rolagem e os grupos abertos são lembrados nesta aba, por conta e
  campanha, em `sessionStorage`. Nenhum dado de formulário é armazenado ali.
- Territórios: CEP preenche município, UF, código IBGE e bairro quando retornado.
  Sem CEP: escolher UF, digitar cidade e rua, consultar e selecionar um resultado.
  Informações digitadas manualmente são preservadas na consulta automática;
  clicar explicitamente em um resultado permite substituí-las.
- Mapa: **Estado / DF → Município → Cadastrar território nesta cidade**.
  Selecionar a cidade aproxima o mapa, mas não grava dados. O atalho abre um novo
  cadastro com município, UF e código IBGE preenchidos. O mapa acessado pelo
  formulário abre em outra aba para preservar os dados ainda não salvos.
- Filtro regional, lista alternativa, distritos e desenho ficam em seções
  opcionais. Os campos técnicos do território também ficam recolhidos.

## O que continua separado e por quê

**Território** é uma área de atuação (bairro, comunidade ou região).
**Comitê/ponto de apoio** é um local público com endereço e coordenadas.
Um território pode ter vários pontos; misturá-los criaria ambiguidade.
Selecionar um município, cadastrar um território e desenhar um contorno são ações
distintas. Nenhum módulo ou dado foi apagado para simplificar a apresentação.

## Fontes e limites

[ViaCEP](https://viacep.com.br/): referência postal, não geocodificação nem
delimitação de bairros. Busca por rua exige UF, cidade e pelo menos três
caracteres nos nomes. O código IBGE retornado identifica o município; não é um
identificador de bairro. CEP não fornece contorno ou localização individual.

Consulta autenticada por POST com CSRF e permissão territorial; somente CEP ou
UF/cidade/rua são enviados ao provedor, nunca IDs da campanha ou dados de pessoas.
Host fixo HTTPS, sem redirects, timeout de 5 s, resposta de até 96 KiB/50 resultados,
campos em allowlist e cache de referências públicas. Limites: 20 consultas/minuto
por usuário e 120/minuto por instalação. Falhas não impedem cadastro manual.

[IBGE](https://servicodados.ibge.gov.br/api/docs/localidades): referências
administrativas e limites simplificados. Os seletores são carregados separadamente
dos contornos, para uma falha de limites não inutilizar uma lista já disponível.
Contornos da equipe continuam identificados como não oficiais.

[Leaflet 1.9.4](https://leafletjs.com/download.html) passou a ser servido localmente,
com arquivos originais, licença e hashes conferidos. Scripts/estilos externos foram
retirados da política do mapa. Os mosaicos continuam no OpenStreetMap, portanto
não se trata de um mapa offline.

## Verificações da revisão

- 249 testes Django locais: aprovados, com 23 exclusivos de PostgreSQL ignorados
  no SQLite. A matriz PostgreSQL deve aprovar o mesmo commit antes da publicação.
- 7 testes Node sem dependências: rolagem/restauração/BFCache/storage indisponível,
  preenchimento, preservação, código IBGE obsoleto e resposta atrasada.
- 41 templates compilados, sintaxe JavaScript, Ruff fatal e ausência de migrations.
- Navegador com dados sintéticos: clique direto manteve rolagem 328 → 328;
  barra 76/280 px; menu móvel e Escape; formulário sem transbordamento horizontal
  em 320 e 390 px; consultas reais de CEP e rua da Praça da Sé; seleção de São Paulo
  e contorno oficial no mapa. Nenhum cadastro de teste criado em produção.

Esta revisão não certifica todos os módulos do produto. O status de publicação
é registrado separadamente após CI, staging e verificações em produção.

## Publicação verificada

Em 24/09/2026 às 17:48 UTC, produção ficou ativa em
`2de3282a04a3c1473824c41338a828830193c3aa`.

- [CI aprovada](https://github.com/iamnothuman7/nabio-elege/actions/runs/36035878951):
  SQLite, PostgreSQL 14/15, testes de interação, segurança e artefato.
- Homologação HTTPS: 105 verificações gerais (44 listas/42 formulários), 51 de
  plataforma e 17 de acesso direto. Ensaio adicional repetiu os fluxos gerais e
  confirmou ViaCEP real por CEP/rua, rejeição de CSRF/entrada inválida e três scripts
  locais do mapa/menu. Contas de QA encerradas; nenhum dado real usado nos ensaios.
- Retorno à release anterior e reativação da nova ensaiados em homologação, com
  diretório dos workers verificado; sem reversão de banco.
- Backups cifrados verificados antes e depois; nenhum backup ou segredo exportado.
- Produção: banco, RLS, cache, fila, antivírus, workers e versão ativos conferidos.
  Contas existentes preservadas, sem alteração de senha ou permissão.
- TLS 1.3 e certificado do domínio válidos; GET/HEAD das quatro páginas públicas,
  12 recursos e redirecionamento HTTP→HTTPS aprovados. Administração anônima negada.
- Sem migrations, alteração de Nginx ou reinício do servidor; serviços alheios
  preservados. Homologação desligada ao final. Evidências detalhadas ficam privadas
  no servidor, sem dados de clientes no repositório.
