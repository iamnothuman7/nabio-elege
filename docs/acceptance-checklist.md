# Roteiro de homologação

Use apenas a demonstração local e dados fictícios até concluir os bloqueios de produção listados em `implementation-status.md`. Este roteiro não substitui avaliação jurídica, contábil ou de segurança.

## Central eleitoral

- Entrar como `demo.gestor`; conferir painel, candidatura e navegação no computador e celular.
- Abrir Mapa territorial, alternar camadas, filtrar território e localizar um comitê. Conferir atribuição OpenStreetMap e ausência de dados individuais de eleitores.
- Criar território, ponto operacional público e cabo eleitoral fictício. Validar coordenadas e vínculo por campanha.
- Criar ação de rua; encaminhar para revisão. Entrar como `demo.revisor` para aprovar. Escalar trabalhador treinado; confirmar e registrar presença dentro da janela permitida.
- Tentar escala sobreposta e vínculo de outra campanha; ambos devem ser recusados.
- Criar cadastro voluntário com finalidade, comprovação e declaração de maioridade. Conferir estado pendente e revisão por outro operador. Testar acesso de responsável e usuário sem permissão global.

## Ciclos administrativos

- Criar orçamento/linhas e obter aprovação independente.
- Criar compra com itens, revisar pedido, conferir obrigação gerada e receber em duas parcelas; estoque não pode duplicar ao repetir uma ação.
- Aprovar obrigação por outro operador, registrar pagamento e conciliar parcialmente. Tentar conciliar acima do valor e repetir comando idempotente.
- Reservar estoque, consumir/liberar e tentar saída maior que o saldo.
- Criar custódia de patrimônio e viagem; tentar períodos conflitantes.
- Revisar conteúdo editorial; registrar somente uma publicação externa coerente com o conteúdo aprovado.
- Gerar manifesto contábil, revisar e exportar. Exportação não deve ser tratada como entrega oficial; esta exige protocolo externo explícito.

## Formulários, privacidade e documentos

- Criar finalidade e formulário, revisar por outro autor, publicar e gerar link. Abrir em sessão sem autenticação, enviar registro fictício e verificar recibo/atendimento.
- Repetir envio com a mesma chave; não deve duplicar atendimento. Pausar formulário e verificar recusa de novos envios.
- Testar upload privado com ClamAV real: arquivo limpo, arquivo de teste antivírus, tipo inválido e serviço indisponível. Nunca liberar download quando a verificação não for positiva.
- Testar supressão, revogação de acesso e classificação de documentos. Validar que consultas de contato não expõem o contato na URL.

## Segurança e operação antes de produção

- Executar suíte SQLite e PostgreSQL e verificar resultado da CI.
- Exigir MFA no perfil normal; testar replay TOTP, recuperação, revogação de sessões e limitação de login.
- Criar operador sintético com permissões explícitas; conferir recusa de alvos existentes, ausência de superusuário e troca obrigatória antes do MFA/acesso às campanhas.
- Trocar senha com confirmação da senha atual e segundo fator; comprovar encerramento das demais sessões e bloqueio após tentativas repetidas.
- Criar caso jurídico, autorizar um revisor e manter outro integrante sem concessão. Conferir listas, acesso direto, ações, documentos, ocorrências, seletores e auditoria; repetir após revogação e expiração do vínculo.
- Associar documento a dois casos e confirmar que acesso a apenas um não autoriza o download. Recusar remoção do último administrador ativo do caso.
- Instalar com o lock de hashes; conferir divergência de pins, compilação de templates, collectstatic, Gitleaks, auditoria de dependências e artefato por SHA na CI.
- Testar campanhas distintas, vínculos expirados, usuário suspenso e superusuário sem vínculo explícito.
- Verificar que arquivo de campanha bloqueia escrita e que pendências impedem fechamento.
- Homologar RLS, concorrência de todos os fluxos críticos, política de dados, backups/restauração, alçadas e documentos contábeis.
- Configurar domínio/HTTPS, cookies seguros, armazenamento privado, antivírus, workers, observabilidade, provedor de mapas e capacidade de carga.

Não liberar produção apenas por uma tela renderizar ou pela suíte local passar.
