# Verificações de regressão

Roteiros que exercitam o sistema contra o banco de demonstração
(`seed_demo`), pela camada HTTP, com o cliente de teste do Django.

Não são testes unitários e não substituem uma suíte automatizada — a
DEC-20 registra que nenhuma foi criada nesta fase. São o que existe hoje
para responder "isto continua funcionando?", e cada um tenta **quebrar**
o que verifica, em vez de confirmá-lo.

Estavam num diretório temporário, fora do repositório, até 09/09/2026.
Um diretório temporário some, e com ele sumiria a única regressão que
existe sobre permissões, isolamento entre inquilinos e o portal.

## O que os roteiros deixam para trás

Desde `audit/0003_auditevent_imutavel` a trilha de auditoria é
`INSERT`-only no banco, e o papel da aplicação não tem `UPDATE` nem
`DELETE` sobre ela. Três roteiros limpavam as próprias sobras apagando os
eventos que haviam gerado, para então poder apagar a conta ou a
organização que `AuditEvent.actor`/`AuditEvent.tenant` prendem por
`PROTECT`. O banco passou a recusar isso — e o primeiro atalho que a
proteção quebrou foi o deles, o que é o sinal de que ela funciona.

Agora essas entidades são **aposentadas**: perdem os poderes, devolvem os
identificadores únicos (e-mail, CNPJ, slug) e ficam de pé, com a trilha
intacta apontando para elas. Cada rodada completa deixa, portanto, algumas
contas `aposentado-por-roteiro-*` e organizações `aposentada-por-roteiro-*`
no banco de demonstração. São inofensivas e coerentes — a organização
aposentada mantém o roteiro de exame, justamente porque outros roteiros
varrem todas as clínicas e cobram isso de cada uma.

Elas aparecem como `[roteiro] organizacao de teste aposentada` e
`[roteiro] conta aposentada`, para quem abrir o console não precisar
adivinhar o que são.

**O resto não acumula, e isso foi medido.** Rodar a bateria inteira duas
vezes seguidas deixa paciente, atendimento, anexo, documento e
agendamento exatamente onde estavam. Até 19/09/2026 não era assim: cinco
roteiros que emitem documento deixavam **vinte e dois anexos por rodada**
(o `MedicalDocument` era apagado e o PDF dele ficava órfão, no banco e no
volume de mídia), e o `check_secretary` deixava um paciente por rodada —
o pré-cadastro pela agenda cria paciente junto com o agendamento, e só o
agendamento era devolvido. Paciente ativo conta para o limite do plano
(`tenancy/limits.py`), de modo que aquele acúmulo terminaria fazendo os
roteiros falharem por esgotamento de cota, e não por regressão.

Ao escrever um roteiro novo, meça: conte as linhas antes e depois e
confira que o número voltou. É mais barato que descobrir meses depois,
pela lista de pacientes da clínica de demonstração.

Para zerar, recrie a base: `docker compose down -v`, suba de novo e rode
`seed_demo` (e `import_cmed` no worker, se for exercitar as receitas).

## Como rodar

Todos, ou os que interessam:

```sh
docker compose exec app python manage.py rodar_roteiros
docker compose exec app python manage.py rodar_roteiros planos landing
docker compose exec app python manage.py rodar_roteiros --parar-no-primeiro
```

Uma linha por roteiro, a saída completa só de quem falhou, e código 1 se
algum falhar. Cada um roda em processo próprio — é mais lento do que
carregar todos no mesmo interpretador, e é assim de propósito: eles mexem
em `settings`, criam e apagam registros, e um roteiro que passa por causa
de quem rodou antes não serve para nada.

Enquanto se **escreve** um roteiro, use a forma antiga: `rodar_roteiros`
lê `checks/` de dentro da imagem, e a linha abaixo empurra o arquivo do
disco, de modo que a edição vale sem reconstruir.

```sh
docker compose exec -T app python manage.py shell < checks/check_matrix.py
```

Cada roteiro imprime o que observou, termina em `OK: …` quando passa e
sai com código 1 listando as falhas quando não passa.

## O que cada um cobre

| Roteiro | Assunto |
| --- | --- |
| `check_admin` | Convênios, planos e tabela de honorários — quem pode o quê |
| `check_chave` | Chave-mestra de segredos separada da do PFX, e a rotação |
| `check_captura_removida` | Captura local ausente do menu, das rotas e da ajuda |
| `check_agenda` | Modal de marcação, hora explícita na semana e vagas livres/ocupadas no mês |
| `check_exame_neurologico_texto` | Texto narrativo do exame: autosave, releitura, resumo e hash clínico |
| `check_bookerr` | Aviso de erro nomeando o campo que falhou |
| `check_cf` | Itens trazidos do atendimento anterior |
| `check_docform` | Formulário de documento por tipo, e retificação |
| `check_g3` | Equipe, papéis, registro profissional, identidade da clínica |
| `check_g45` | Provedor de IA e SMTP por clínica, com os botões de teste |
| `check_g6` | QR, assinatura no PDF, verificação pública, receita em duas vias |
| `check_g7` | Entrega ao paciente: link, segundo fator, revogação |
| `check_g8` | Compactação de anexo e relatório de retenção |
| `check_g9` | Campanhas: consentimento, lista congelada, descadastro |
| `check_foto` | Fotografia do paciente: formatos, papéis, isolamento e remoção |
| `check_financeiro_fechamento` | CSV de competência/caixa, documento fiscal, repasse individual, arquivamento e limpeza restrita |
| `check_g10` | Portal de solicitações e a fila do médico |
| `check_hint` | Máscara de segredo com largura fixa |
| `check_ia_padrao` | Provedor de IA padrão da instalação, e a precedência da clínica |
| `check_instalacao` | Instalacao nova: do zero ao primeiro paciente (exige banco vazio) |
| `check_isolation` | Documento no prontuário do paciente certo |
| `check_links` | Nenhum perfil vê link que não consegue abrir |
| `check_matrix` | A matriz de acesso confere com o PRD seção 4 |
| `check_mfa_certificado` | QR e percurso da MFA, verificação recente e certificado isolado por médico |
| `check_nome_do_contato` | Nome do contato próprio acompanha a ficha e a inclusão de novos contatos funciona |
| `check_notificacoes` | Aviso nomeia o paciente, leva à resolução, e alcança só quem pode agir |
| `check_convite` | Entrada do superadministrador: link, senha, MFA, console |
| `check_landing` | Página de vendas, formulário de contato e a tela de leads |
| `check_ajuda` | Manual e FAQ públicos, e nenhuma captura faltando ou órfã |
| `check_chatbot` | O que o chat manda ao provedor, e o que ele nunca manda |
| `check_codigos` | Busca de CID-10 e TUSS, incluindo a abreviação da tabela |
| `check_email` | O web enfileira, o worker entrega: conta e senha chegam |
| `check_mensageria` | A mensageria da instalacao e a de cada clinica nao se tocam |
| `check_inativacao` | Suspender congela, encerrar fecha, e nada e apagado |
| `check_convite_plano` | Convite carregando o plano, e o console que emite e troca |
| `check_planos` | Limites de plano nas seis portas, e o que acontece ao rebaixar |
| `check_precadastro` | Contato do pré-cadastro e confirmação antes de entrar na lista de pacientes |
| `check_prontuario` | Número do prontuário e documentos por paciente |
| `check_roles` | Resposta de cada papel nas telas principais — **só imprime, não reprova**: a regressão só aparece para quem lê a saída. Quem afirma a matriz é `check_matrix` |
| `check_roteiro` | A clínica nasce com o roteiro de exame instalado |
| `check_resto` | Hábitos, confirmação por e-mail, pedido editável, receita, console |
| `check_secretary` | A secretária trabalha, e não passa do que lhe compete |
| `check_super` | O console da instalação por dentro, e o que ele não mostra |
| `check_tenantb` | O que o mesmo usuário alcança em cada organização — **só imprime, não reprova**, como `check_roles` |
| `check_alerta_erro` | O e-mail de alerta do erro 500 não leva settings nem segredo |
| `check_auditoria_lote1` | Auditoria de 2026-10-09, lote 1: PDF emitido × rascunho, finalização × autosave, reenvio, `next` do MFA, portal (exige PostgreSQL) |
| `check_auditoria_lote2` | Auditoria de 2026-10-09, lote 2: IA para quem perdeu o papel, cancelamento que a cópia velha não desfaz, DLR, "ERRO" com HTTP 200, exportação, retomada de IA |
| `check_aviso_de_horario` | Paciente avisado ao marcar, remarcar e cancelar, com o endereço como `Local` |
| `check_backup` | Restaurador carrega, trava única entre backup e arquivo morto, unidades do systemd |
| `check_bloquear_horario` | Bloquear horário livre (fica e conta na estatística) e a duração que segue o tipo nas consultas antigas |
| `check_campanha_servidor_proprio` | Campanha só sai pelo servidor SMTP da própria clínica, em qualquer plano |
| `check_cobranca_checkin` | O check-in gera uma cobrança só, reaproveitada pelo atendimento |
| `check_colaboradores` | Convite de colaborador, confirmação de conta e credenciais |
| `check_contatos_indicadores` | Contato editável, e pré-cadastro fora dos indicadores e da cota |
| `check_contrato` | Contrato de adesão: cláusulas, aceite gravado com o texto, prazos, via ao contratante |
| `check_crm_em_outra_conta` | CRM já registrado em outra conta: recusa útil, sem revelar o e-mail |
| `check_csp` | Política de conteúdo: nonce, nada de `onclick`, `<script>` sem nonce reprovado |
| `check_decisoes` | Decisões da auditoria pré-deploy: endereço da API de IA (SSRF) e a coleta em ensaio nos dois sentidos |
| `check_declaracao` | Declaração de comparecimento sem CID nem diagnóstico, e que não é atestado |
| `check_despachante` | Outbox: posse do evento, consumidor fora de transação, idade do aviso (exige PostgreSQL) |
| `check_dinheiro` | Pagamento e ajuste aceitam o formato brasileiro e não dão 500 |
| `check_entrega_documento` | Entrega ao paciente que não derruba a tela: SMS num segmento, e-mail sai mesmo com SMS quebrado, saída pelo worker |
| `check_exames_do_portal` | Laudo enviado pelo paciente no portal: só PDF, 5 por envio, 3 MB, tudo ou nada, prontuário certo, alerta e ciente do médico, e a janela de retorno que não o barra |
| `check_medicacao_editar` | Alterar a medicação no lugar: o lápis e o formulário preenchido por linha, só o campo mudado muda, a trilha sem valores, sem mudança sem rastro, e as recusas (finalizado, secretária, outra clínica, outro atendimento) |
| `check_resumos_aprovados` | O resumo por IA aprovado (e o editado) aparece no atendimento, estruturado e texto livre; pendente, recusado, apoio diagnóstico, outro atendimento e outra clínica ficam fora; o texto clínico e o `content_hash` não mudam; a secretária não abre |
| `check_busca_por_nome` | A busca acha pelas palavras do nome, em qualquer ordem e sem acento, nas três portas (agenda, busca rápida, lista); palavra ausente tira (é E); número do prontuário com e sem zeros; nada de outra clínica, e o arquivado fora da agenda |
| `check_cep_na_edicao` | O CEP novo troca o endereço também na edição: preserva só o digitado nesta tela (não o que veio do banco), mede a mudança contra o CEP de abertura, limpa número e complemento da casa anterior, e o cadastro novo não apaga a rua digitada antes do CEP |
| `check_confirmacao_unica` | Uma pergunta por ação: o `nd-inline.js` cede ao modal do sistema, o modal está no `base.html` sem condição, toda tela com `data-nd-confirm` herda dele, e nenhuma caixa nativa (`window.confirm/alert/prompt`) nova |
| `check_estruturado` | Prontuário estruturado: impressões na aba, "trazer tudo", cada envio voltando para a sua aba |
| `check_evolucao` | Série temporal: eixo proporcional à data, escala no próprio domínio |
| `check_excluir_horario` | "Excluir este horário" some com a célula, e "Incluir horário" a reabre |
| `check_exportacao` | Exportação do acervo em MD e JSON: quem pode pedir cada um, o arquivo do worker |
| `check_fuso` | O "hoje" é o de Brasília: varre o repositório atrás de `date.today()` e `timezone.now().date()` |
| `check_honorario_tipo` | Honorário por tipo de atendimento |
| `check_ia_assincrona` | Conclusão visível do job de IA, e revisão tardia de laudo como adendo |
| `check_ia_plano` | A IA segue o plano contratado: capacidade, autorização do job, resumo automático, chat |
| `check_idade` | Idade ao lado do nome, e no atendimento a idade na data dele |
| `check_idioma` | Tudo que o usuário lê está em português (varre o código) |
| `check_importacao` | Migração de cadastro: ninguém nasce autorizado a receber mensagem, repetível, CPF repetido não derruba |
| `check_imutabilidade` | O que não pode mudar: finalizado, salvamento concorrente, trilha, guarda de 20 anos |
| `check_incluir_horario` | Botão "Incluir horário" nas três visões, e as recusas |
| `check_intervalos_e_ficha` | Intervalo pontual da agenda nos três caminhos, naturalidade, gaveta da ficha |
| `check_js_atributo` | JS que monta atributo HTML sem escapar aspas (varre JS e templates) |
| `check_leitura_retirada` | A leitura de laudo pela IA saiu de todos os caminhos (1.18), o job antigo é cancelado com a explicação, e as varreduras de esquema e de prompt que valem para toda tarefa de IA |
| `check_mensagens_retencao` | O chat da equipe apaga a mensagem em 72 horas e cada um apaga a própria janela; o não lido refeito; o ícone do som que troca de verdade |
| `check_chat_manual` | O chat sem paciente responde pelo manual e pela documentação técnica (RAG por palavras), com a fonte; a conversa com paciente fica só com o prontuário |
| `check_links_de_mensagem` | Todo link que sai em e-mail ou SMS abre, e nada é enfileirado antes do commit |
| `check_login` | Duas portas de entrada que devolviam tela crua |
| `check_logotipo` | O logotipo é o da organização aberta, sem cache de cinco minutos |
| `check_mensagem_clinica` | "Fale com a NeuroDoc" e sugestões: da clínica para o console |
| `check_mensagem_paciente` | O texto do SMS e do e-mail ao paciente |
| `check_mensagens` | Chat da equipe: conversa única por par, fronteira entre clínicas, contador |
| `check_mes_e_estatisticas` | Visão de mês e estatísticas: o passado não mente |
| `check_mfa_reconfirmacao` | Reconfirmar o segundo fator sem derrubar a sessão |
| `check_minha_conta` | Cada um edita o próprio nome, e só o próprio |
| `check_minha_conta_overlay` | "Minha conta" abre e salva no modal, com página inteira de reserva |
| `check_mobile` | Aderência ao celular, no que dá para conferir sem navegador (varre templates) |
| `check_nome_caixa_alta` | Nome do paciente em caixa alta pelos quatro caminhos de criação |
| `check_nome_exibido` | O nome na tela é o mesmo da receita |
| `check_paginacao` | Primeira e última página das listagens, criando volume antes de olhar |
| `check_perimetro` | A borda: CSRF, desidentificação, IP do visitante atrás do proxy |
| `check_por_cid` | Busca de paciente por CID: fronteira de papel e a última palavra por código |
| `check_portal_retorno` | Portal barra consulta com mais de 180 dias, quando manda barrar, nas três portas |
| `check_provedor_e_sms` | O padrão da instalação para IA e SMS, e nenhuma view enviando de dentro da requisição |
| `check_sncr_transicao` | Transição do SNCR (1.21.1): a RCE eletrônica para em 31/10/2026 (dia de Brasília), recusada no servidor e na tela sem gastar número; o papel continua; a receita simples só recebe o aviso |
| `check_portaria344` | Lista oficial das substâncias controladas (Portaria 344/98): leitura inteira do ato vigente, receituário da norma, parser estrito, classificação por palavra inteira |
| `check_receitas` | Catálogo CMED, emissão em papel, QR só em documento assinado (exige `import_cmed`) |
| `check_recontratacao` | Recontratar preserva a conta e devolve o acesso com convite novo |
| `check_relatorio_ia` | Relatório escrito pela IA vira rascunho, e o texto editado é o que vai assinado |
| `check_retencao_transitoria` | Dado transitório some no prazo: notificação 7/15 dias, entrega 15 |
| `check_retorno` | Retorno programado: data, aviso 20 dias antes, fila da secretária |
| `check_rodape_do_documento` | Assinatura no pé da última folha de cada via, e cabeçalho e rodapé de página ("Página N de M" por via) em toda folha, medidos pela posição do texto no PDF |
| `check_seo` | O que o buscador vê: `<title>`, `noindex`, sitemap, canônica, JSON-LD |
| `check_servicos_do_inquilino` | IA, SMS e e-mail da clínica, e o retorno ao padrão quando desliga |
| `check_sms_plano` | O SMS segue o plano contratado |
| `check_texto_livre` | Atendimento em texto livre ao lado do estruturado, e o adendo depois de fechado |
| `check_tipo_de_consulta` | Trocar o tipo de um horário marcado só antes da chegada, com a duração acompanhando |
| `check_um_envio_por_endereco` | Um envio por endereço, e não por contato |
| `check_chat_stream_ui.cjs` | Evento terminal encerra a geração na tela do chat. **É Node**: o `rodar_roteiros` não o vê; rode com `node checks/check_chat_stream_ui.cjs` |

## Cuidados

Rodam contra o banco de **demonstração**, não contra um banco de teste
descartável: alguns criam registro e apagam no fim. Um roteiro
interrompido no meio pode deixar sobra — `check_secretary` deixa um
paciente por rodada, porque apaga o horário e não o cadastro (paciente com
atendimento é protegido por `PROTECT`, e apagá-lo apagaria o registro de
que aquele atendimento existiu; o caminho é arquivar).

Nunca rodar contra dado real.
