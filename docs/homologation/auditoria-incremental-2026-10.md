# Auditoria incremental do código — outubro de 2026

**Escopo:** Sprint 2 do trabalho de 2026-10-22/23, feita depois das ações
rápidas do chat (Sprint 1, commit `3114612`). A auditoria foi orientada por
evidência: só entrou na lista de correções o que foi **reproduzido** no
ambiente local, e só foi corrigido o que tinha risco baixo, sem migração,
sem mudança de contrato e com reversão por código.

**Base:** branch `feature/ai-chat-acoes-rapidas`, a partir de `8095114`
(1.23 publicada). Bateria de referência sobre o `8095114`: **122 roteiros,
nenhuma falha** (551 s).

## Como foi feita

Três leituras independentes, somente leitura, sobre o código atual:

1. desempenho (consultas por tela, *context processor*);
2. defeitos de Python, acessibilidade e templates;
3. tarefas do Celery e código de IA.

Cada achado foi conferido no código e, quando havia correção candidata,
**reproduzido** antes de qualquer edição. O que não foi reproduzido ficou
como achado, com a classificação abaixo.

Classificação: **CONFIRMADO** (reproduzido), **PROVÁVEL** (o código mostra,
sem reprodução completa), **HIPOTÉTICO**, **NÃO PROCEDE**.

## Achados

| ID | Área | Achado | Evidência | Classe | Decisão |
| --- | --- | --- | --- | --- | --- |
| A1 | IA / chat | A pergunta do chat ia **duas vezes** ao provedor | Reprodução: `['…', 'E para desfazer?', 'E para desfazer?']` | CONFIRMADO | **Corrigido** |
| D1 | Desempenho | Documentos do paciente: uma consulta por documento (`replaced_by.exists()`) | 18 consultas com 2 documentos, 24 com 8 | CONFIRMADO | **Corrigido** |
| D2 | Desempenho | Agenda do mês: contatos do paciente buscados por horário marcado | Consultas crescem com os horários desenhados | CONFIRMADO | **Corrigido** (junto com D1) |
| B1 | Idioma | Três recusas do cadastro de contato em inglês; uma aparecia duplicada | Formulário real: "A contact needs a phone or an e-mail" ao lado de "Informe telefone ou e-mail." | CONFIRMADO | **Corrigido** |
| C1 | Celery | Confirmação de horário (`send_confirmation_task`) com nova tentativa automática para qualquer exceção, sem idempotência: falha **depois** do envio repete o SMS | Reprodução: 2 SMS com a trilha estourando depois do envio | CONFIRMADO | **Corrigido** (lote seguinte, ver abaixo) |
| C2 | Celery | Reenvio de documento com `force_new_link=True` e nova tentativa automática: a repetição revoga o link já enviado | Reprodução: 3 mensagens, 1 link morto | CONFIRMADO | **Corrigido** (lote seguinte, ver abaixo) |
| C3 | Celery | `retomar_tuss_incompleta` (de hora em hora) dispara uma segunda sincronização da TUSS em paralelo à que já roda; sem trava em `sync_incremental` | Leitura; a cadeia duplicada morre na `UniqueConstraint` | PROVÁVEL | **Corrigido** (lote seguinte) |
| C4 | Celery | `dispatch_outbox` (5 s) e `reconcile_pending_sms` (60 s) sem `expires`: acumulam na fila com o worker parado | Leitura; efeito inofensivo (`skip_locked`) | PROVÁVEL | Não corrigido — baixo benefício |
| I1 | IA | Prompt do relatório: "pedido do médico manda sobre tudo que vem depois" antes das regras que não admitem exceção | `ai/graphs.py:87-98` | PROVÁVEL | **Corrigido** (lote seguinte) |
| P1 | Desempenho | *Context processor* com Tenant e `ClinicProfile` lidos duas vezes por requisição | Leitura de `base/context_processors.py` | CONFIRMADO (leitura) | Não corrigido — ganho pequeno, toca toda tela |
| P2 | Desempenho | Agenda da semana: 28–35 consultas (`day_grid` por dia sem lote) | Medido: 31 consultas com 2 reservas, 33 com 8 | CONFIRMADO | **Corrigido** (lote seguinte) |
| X1 | Acessibilidade | Rótulos sem `for`, campos identificados só por *placeholder* (console, portal, busca de códigos), `<a href="#">` como botão no cabeçalho | Varredura: 21 campos sem nome em 153 | CONFIRMADO | **Corrigido** (lote seguinte) |
| — | Segurança | IDOR, `except: pass` em gravação, relógio do processo | Varredura: nada encontrado | NÃO PROCEDE | — |

## As três correções

### A1 — a pergunta do chat ia em dobro ao provedor

- **Problema:** `chat_services.post_user_message` grava a pergunta como
  **completa** antes de a tarefa rodar. `build_history` lia as completas, e
  `build_chat_prompt` ainda acrescentava a pergunta no fim. O provedor
  recebia `[…, pergunta, pergunta]`.
- **Efeitos:** tokens a mais; uma vaga a menos na janela de histórico; e,
  na conversa sem paciente, a "pergunta anterior" que a busca no manual usa
  (1.18, §7-H) passava a ser a **própria pergunta atual** — o seguimento
  ("e para desfazer?") deixava de achar o trecho certo.
- **Por que os roteiros não pegavam:** `check_chatbot` e `check_chat_manual`
  chamam `build_chat_prompt` com uma pergunta **não gravada**; em produção
  ela sempre é gravada.
- **Mudança:** `build_history(…, excluir_id)` e
  `build_chat_prompt(…, pergunta_id)`; `run_chat_turn` passa o id da pergunta.
  Os parâmetros são opcionais — quem chamava sem eles segue igual.
- **Antes:** a pergunta atual aparecia 2 vezes. **Depois:** 1 vez.
- **Roteiro:** `check_chat_pergunta_unica.py` (grava como a view grava e
  monta como a tarefa monta, com e sem paciente, e confere a busca no manual).

### D1/D2 — consultas por linha em duas telas

- **Mudança:** `prefetch_related('replaced_by')` na lista de documentos do
  paciente; `prefetch_related('patient__contacts')` no `month_summary` (a
  semana e o dia já tinham).
- **Medição** (volume criado em transação desfeita, mesmo paciente e médico):

  | Tela | Antes N=2 | Antes N=8 | Depois N=2 | Depois N=8 |
  | --- | --- | --- | --- | --- |
  | Documentos do paciente | 18 | 24 | 17 | 17 |
  | Agenda do mês | 24 | 25 | 23 | 23 |

- **Roteiro:** `check_consultas_fixas.py` — o número de consultas não pode
  mudar entre N=2 e N=8, e nada fica gravado.

### B1 — recusas em inglês no cadastro de contato

- **Problema:** `PatientContact.clean()` recusava em inglês, e o formulário é
  `ModelForm` (o `_post_clean` chama o `clean()` do modelo). Duas recusas
  saíam **só** em inglês; a de "sem telefone nem e-mail" saía duplicada.
  `check_idioma` não pegava (menos de duas palavras da lista dele por frase).
- **Mudança:** as três frases traduzidas no modelo; o formulário deixa a
  recusa "sem telefone nem e-mail" só para o modelo (retorno antecipado, que
  mantém o que o bloco fazia: sem canal nenhum, as conferências de SMS e
  e-mail não se acumulam).
- **Roteiro:** `check_contato_em_portugues.py` — reprovou contra o código
  antigo (3 falhas) e passa no novo.

## Por que os outros não foram corrigidos nesta sprint

- **C1 e C2:** ficaram para um lote próprio, feito em seguida — ver abaixo.
- **C3, I1, P2 e X1:** feitos no lote seguinte, com C1 e C2 — ver abaixo.
- **C4 e P1:** continuam abertos. C4 é inofensivo (`skip_locked`) e P1 toca
  toda tela de `/app/` por um ganho pequeno.

## Lote seguinte: C1 e C2 — a nova tentativa que repetia o envio

Feito depois da Sprint 2, na branch `fix/sms-sem-repeticao`, com a decisão
do Dr. Fernando de seguir a ordem recomendada.

- **O que a reprodução mostrou, e a leitura não tinha visto:**
  `send_appointment_confirmation` era uma transação inteira. A falha depois
  do envio desfazia a `Delivery` — o SMS que tinha saído **sumia do
  histórico** —, e a nova tentativa, sem como saber dele, mandava outro. No
  reenvio de documento, a repetição revogava os links da primeira volta e
  mandava links novos: 3 mensagens, uma com link morto.
- **Por que não tirar a nova tentativa:** ela cobre a falha **antes** do
  envio (o banco que pisca ao abrir o horário), e sem ela essa mensagem
  simplesmente não sairia, sem aviso a ninguém.
- **Mudança:** as duas tarefas passam o próprio id (`self.request.id`, que a
  nova tentativa do Celery preserva). A entrega é gravada **antes** do
  envio, numa transação que fecha antes dele, com a marca do pedido na
  chave de idempotência; a repetição encontra a entrega e `_send` não envia
  o que já não está na fila. No documento, a revogação dos links antigos só
  acontece se nada deste pedido foi gravado. Dois cliques são dois pedidos,
  com marcas diferentes: reenviar continua sendo reenviar. Sem migração.
- **Antes:** confirmação 2 SMS; reenvio 3 mensagens com 1 link morto.
  **Depois:** 1 SMS; 1 mensagem por canal, todos os links abrindo.
- **Roteiro:** `check_sms_sem_repeticao.py` — reprovou contra o código
  antigo (3 falhas) e passa no novo. Roda a tarefa com `apply()`, que
  executa a nova tentativa de verdade, e confere os dois lados: a falha
  depois do envio não repete, a falha antes dele continua sendo tentada.
- **Resíduo conhecido:** se a falha vier entre gravar o link de um contato
  e enviá-lo, a repetição grava outro link e envia este; o primeiro fica
  vivo até expirar, sem nunca ter sido mandado a ninguém (só o resumo dele
  existe no banco).

## Lote seguinte: C3, I1, P2 e X1

Pedido pelo Dr. Fernando ("vamos corrigir o resto"), na mesma branch.

### C3 — uma sincronização da TUSS por vez

- **Correção da descrição:** a duplicata não acontece "toda hora", e sim só
  **enquanto uma atualização está em andamento** (domingo de madrugada, por
  algumas horas): `retomar_tuss_incompleta` via o rascunho e disparava uma
  segunda rodada sem saber que a primeira estava viva.
- **Mudança:** `sync_tuss_task` pega uma trava de sessão do PostgreSQL
  (`TUSS_LOCK = 72654004`, família de `ops/locks.py`); quem não a pega sai
  na hora e não se reagenda — a rodada viva já agenda a próxima. Solta no
  `finally`, e o PostgreSQL a solta sozinho se o worker morrer.
- **Roteiro:** `check_tuss_uma_rodada.py` — segura a trava por outra conexão
  e confere que a segunda rodada não chama a ANS; sem disputa, roda e se
  reagenda como antes; a trava é solta também quando a rodada estoura.

### I1 — o pedido do médico no prompt do relatório

- **Antes:** "Pedido do médico, que manda sobre tudo que vem depois" — e
  depois vinham as regras que não admitem exceção.
- **Depois:** "Pedido do médico, que manda sobre as seções, a ênfase e o
  tom — não sobre as regras abaixo". Aprovado pelo Dr. Fernando.
- **Roteiro:** seção 12 de `check_relatorio_ia.py`.
- **Não avaliado:** o efeito com o provedor real (os roteiros usam o
  simulado). A frase só estreita o alcance do pedido; não acrescenta regra.

### P2 — agenda da semana em lote

- **Mudança:** `week_grid` carrega regras, bloqueios, pausas e reservas uma
  vez para os sete dias e entrega a cada dia a parte dele, como
  `month_summary` já fazia. `day_grid` não mudou.
- **Medição** (`week_grid`, semana montada em transação desfeita):

  | | 2 reservas | 8 reservas |
  | --- | --- | --- |
  | Antes | 31 | 33 |
  | Depois | 6 | 6 |

- **Roteiro:** `check_semana_em_lote.py` — a semana inteira comparada
  **célula por célula** com `day_grid` dia a dia (com e sem cancelados), num
  cenário com regra que termina no meio da semana, regra que começa no meio
  dela, pausa, bloqueio com motivo, férias, horário excluído, atendimento
  extra no sábado e consulta de 80 minutos.
- **Observação, sem mudança:** a semana e o dia não recebem o histórico
  (`done`); só o mês mostra o atendimento concluído como "atendido". Era
  assim antes, e continua — mudar seria comportamento novo, não otimização.

### X1 — campos sem nome para o leitor de tela

- **Mudança, só atributos:** `for`/`id` nos formulários do console
  (estado e plano da organização, com o id da organização no `id`, porque a
  tabela repete o formulário por linha); `aria-label` nos campos que só
  tinham o exemplo cinza (busca de CID e TUSS, portal, chat, SNCR, convites,
  reset de MFA); o título dos grupos de rádio e de caixas ligado ao grupo
  (`role="radiogroup"`/`group` + `aria-labelledby`); `role="button"` nos
  três links sem destino do cabeçalho. Nenhum layout mudou.
- **Antes:** 21 dos 153 campos escritos à mão sem nome. **Depois:** 0.
- **Roteiro:** `check_rotulos.py` — varre todos os templates e reprova
  campo novo sem nome; reprovou nos templates antigos (6 falhas).
- **Não feito:** conferência com leitor de tela de verdade (NVDA, TalkBack).
  O que a varredura garante é a marcação; a experiência ainda pede um teste
  manual.

## Reversão

Só código, sem migração nem dado: `git revert` do commit da Sprint 2. Os três
roteiros novos voltam a reprovar se a correção sair — é o sinal esperado.
