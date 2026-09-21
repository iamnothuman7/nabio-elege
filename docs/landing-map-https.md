# Mapa 3D público e HTTPS — 21/09/2026

- A seção “Um mapa que faz parte do trabalho” usa malhas simplificadas das 27 UFs do IBGE, obtidas em 21/09/2026. [Documentação oficial da API](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3). Fonte da geometria: `/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF`; nomes e regiões: `/api/v1/localidades/estados?orderBy=nome`.
- Geometria estática local em `landing_brazil_geometry.html`, projetada em Mercator e arredondada em décimos de unidade SVG para apresentação. São limites simplificados, não dados cadastrais ou topografia. As camadas de profundidade são ilustrativas. Sem dados de eleitores, rastreamento ou requisição ao IBGE durante a navegação da landing.
- Seleção por estado, destaque da região, teclado, arraste e controles de rotação/reset. O seletor oferece alternativa para UFs pequenas. Sem JavaScript, o desenho e a fonte continuam disponíveis; com redução de movimento, a seleção é mantida e a rotação visual fica desabilitada.
- A pedido do responsável, o botão visível de pausa foi retirado do carrossel. O movimento permanece automático e contínuo quando a página está visível, respeitando a preferência de redução de movimento do dispositivo.
- GET e HEAD das páginas públicas suportados. A verificação externa em 21/09/2026 confirmou TLS 1.3, certificado Let's Encrypt YR2 para `elege.nabio.pro`, válido de 21/09/2026 a 20/12/2026, e redirecionamento HTTP → HTTPS. Não foi reproduzido erro de certificado.
- O vhost HTTPS exclusivo passa a declarar HSTS por 24 horas, sem `includeSubDomains` ou `preload`. Configuração será aplicada após backup, verificação de hash do vhost e `nginx -t`, com reload gracioso. Não altera certificados ou sites de outros projetos. Reforço de HTTPS não equivale a certificação de segurança completa do produto.

Esta atualização mantém as contas e o banco existentes. Não executar novamente o bootstrap de acessos.
