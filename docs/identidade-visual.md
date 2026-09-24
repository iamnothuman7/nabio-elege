# Identidade visual — Nabio Elege

A marca oficial é a imagem fornecida pelo proprietário do produto. O PNG original foi incorporado sem alterações, com transparência preservada, em `workspace/brand/nabio-elege.png` (275.799 bytes, 6000 × 3375 px).

- SHA-256 do original: `3c5e0ec3a85f7c344889cf5aefd4343c1a9f96c7bc46d4841b67033e609f7768`.
- Verde institucional: **#117444**.
- Verde de destaque: **#42B04A**.
- Verde profundo de apoio: **#073F26**; não substitui as cores originais da marca.
- Assinatura colorida sempre sobre branco. Sobre verde, usar a versão totalmente branca: `white=True` no componente `workspace/brand_logo.html`.
- O branco é aplicado com `filter: brightness(0) invert(1)`: mantém o desenho e a transparência, sem nova imagem gerada nem letras reconstruídas.
- `brand.css` enquadra apenas a área útil do PNG, removendo visualmente suas margens transparentes. Não altera a proporção. `mark=True` enquadra o símbolo original para usos decorativos 3D.
- Texto branco usa o verde institucional; o destaque #42B04A usa texto escuro #052E1B. Não usar texto branco pequeno sobre o verde de destaque.

O componente está presente na landing page, no acesso/convite/recuperação, na navegação do painel e nos formulários públicos. As cores de erro, aviso e categorias do mapa mantêm seu significado; a identidade não deve substituir a informação semântica.

## Favicon oficial

O símbolo quadrado fornecido separadamente pelo proprietário é o favicon de todas as páginas da aplicação. O arquivo `workspace/brand/nabio-elege-icon.png` preserva integralmente o PNG original, suas cores e transparência. Apesar do nome do anexo mencionar 1080 px, sua resolução real é **3375 × 3375 px**, com 101.860 bytes. O navegador o reduz para o tamanho da aba, sem reconstrução ou alteração do desenho.

- SHA-256: `1268ccee4c18972aa6ad70dd57ef81aff9066436683e377ba44a959aff1faabc`.
- Declaração compartilhada em `workspace/brand_icons.html`, incluída no `head` da landing page, acesso, painel e formulários públicos.
- Testes verificam hash, dimensões, tipo PNG e presença de uma única declaração de favicon em cada estrutura de página.
