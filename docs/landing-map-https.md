# Mapa 3D público e HTTPS — 21/09/2026

- A seção “Um mapa que faz parte do trabalho” usa malhas simplificadas das 27 UFs do IBGE, obtidas em 21/09/2026. [Documentação oficial da API](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3). Fonte da geometria: `/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF`; nomes e regiões: `/api/v1/localidades/estados?orderBy=nome`.
- Geometria estática local em `landing_brazil_geometry.html`, projetada em Mercator e arredondada em décimos de unidade SVG para apresentação. São limites simplificados, não dados cadastrais ou topografia. As camadas de profundidade são ilustrativas. Sem dados de eleitores, rastreamento ou requisição ao IBGE durante a navegação da landing.
- Seleção por estado, destaque da região, teclado, arraste e controles de rotação/reset. O seletor oferece alternativa para UFs pequenas. Sem JavaScript, o desenho e a fonte continuam disponíveis; com redução de movimento, a seleção é mantida e a rotação visual fica desabilitada.
- A pedido do responsável, o botão visível de pausa foi retirado do carrossel. O movimento permanece automático e contínuo quando a página está visível, respeitando a preferência de redução de movimento do dispositivo.
- GET e HEAD das páginas públicas suportados. A verificação externa em 21/09/2026 confirmou TLS 1.3, certificado Let's Encrypt YR2 para `elege.nabio.pro`, válido de 21/09/2026 a 20/12/2026, e redirecionamento HTTP → HTTPS. Não foi reproduzido erro de certificado.
- O vhost HTTPS exclusivo declara HSTS por 24 horas, sem `includeSubDomains` ou `preload`. Configuração aplicada após backup, verificação de hash do vhost e `nginx -t`, com reload gracioso. Não altera certificados ou sites de outros projetos. Reforço de HTTPS não equivale a certificação de segurança completa do produto.

## Publicação e validação

- Revisão `4f1980bf3d38a01ec8b3317784332176c190bf5d` publicada em [elege.nabio.pro](https://elege.nabio.pro/) em 21/09/2026, com auditoria final às 18:48 UTC. [CI aprovada](https://github.com/iamnothuman7/nabio-elege/actions/runs/35640087951): SQLite/Python 3.11, PostgreSQL 14 e 15/Python 3.12, segurança e artefato.
- Suíte local: 205 testes executados, sem falhas, 23 skips exclusivos de PostgreSQL. Análise estática, formato dos arquivos Python alterados, sintaxe JavaScript e histórico Git sem segredos encontrados. Nenhuma migration nova.
- Staging da revisão exata: 105 requisições HTTPS de módulos (44 listas e 42 formulários, autenticação, MFA, CSRF, isolamento e ClamAV real) mais 34 de administração/clientes. Rollback de código compatível para a revisão anterior e retorno à candidata ensaiados sem reversão de banco.
- Navegador: todas as 27 UFs selecionadas e conferidas, clique no desenho, navegação por teclado, arraste, rotação/reset e alternância das abas. Larguras 320, 390, 768 e 1366 px sem overflow horizontal. Mapa e seletor reconferidos no domínio público, desktop e mobile; sem erros de console na amostra. Testes por viewport não equivalem a testes em aparelhos físicos ou auditoria integral de acessibilidade.
- Verificação externa sem ignorar certificados: TLS 1.3/SAN corretos, HTTP → HTTPS, GET/HEAD 200 nas quatro páginas públicas, CSP/nosniff/DENY e HSTS presentes. Os 12 recursos únicos referenciados pelas páginas responderam 200 por HTTPS, sem referências de carregamento HTTP nos HTML/CSS inspecionados.
- Backup criptografado antes da publicação e antes da alteração do vhost; revisão dos workers confirmada. Banco, contas existentes e serviços de outros projetos preservados. Staging desligado após os testes para liberar recursos; produção e seus agendamentos permanecem ativos. Backups não foram exportados.

As limitações funcionais de [implementation-status.md](implementation-status.md) continuam válidas. Esta é uma atualização da apresentação e do transporte HTTPS, não declaração de conclusão integral do produto.

Esta atualização mantém as contas e o banco existentes. Não executar novamente o bootstrap de acessos.
