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
| C1 | Celery | Confirmação de horário (`send_confirmation_task`) com nova tentativa automática para qualquer exceção, sem idempotência: falha **depois** do envio repete o SMS | Leitura de `communications/tasks.py` e `services.py:892-902` | PROVÁVEL | Não corrigido — ver abaixo |
| C2 | Celery | Reenvio de documento com `force_new_link=True` e nova tentativa automática: a repetição revoga o link já enviado | Leitura de `communications/services.py:296-315` | PROVÁVEL | Não corrigido — ver abaixo |
| C3 | Celery | `retomar_tuss_incompleta` (de hora em hora) dispara uma segunda sincronização da TUSS em paralelo à que já roda; sem trava em `sync_incremental` | Leitura; a cadeia duplicada morre na `UniqueConstraint` | PROVÁVEL | Não corrigido — ver abaixo |
| C4 | Celery | `dispatch_outbox` (5 s) e `reconcile_pending_sms` (60 s) sem `expires`: acumulam na fila com o worker parado | Leitura; efeito inofensivo (`skip_locked`) | PROVÁVEL | Não corrigido — baixo benefício |
| I1 | IA | Prompt do relatório: "pedido do médico manda sobre tudo que vem depois" antes das regras que não admitem exceção | `ai/graphs.py:87-98` | PROVÁVEL | Não corrigido — ver abaixo |
| P1 | Desempenho | *Context processor* com Tenant e `ClinicProfile` lidos duas vezes por requisição | Leitura de `base/context_processors.py` | CONFIRMADO (leitura) | Não corrigido — ganho pequeno, toca toda tela |
| P2 | Desempenho | Agenda da semana: 28–35 consultas (`day_grid` por dia sem lote) | Leitura de `scheduling/availability.py:418` | PROVÁVEL | Não corrigido — exige refatoração (R3) |
| X1 | Acessibilidade | Rótulos sem `for`, campos identificados só por *placeholder* (console, portal, busca de códigos), `<a href="#">` como botão no cabeçalho | Varredura de templates | CONFIRMADO (leitura) | Não corrigido — lote próprio de acessibilidade |
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

- **C1 e C2 (nova tentativa que repete envio):** o efeito é real só se uma
  exceção acontecer **depois** do envio — o que nenhum roteiro reproduz hoje.
  A correção mexe na semântica de nova tentativa da mensageria, que já teve
  correções delicadas (auditoria de 2026-10-09). Proposta: tirar
  `autoretry_for` das duas tarefas ou restringi-lo a falha **antes** do
  `_send`, com um roteiro que injete a exceção depois do envio. Exige
  decisão e lote próprio.
- **C3 (TUSS duplicada):** inofensivo hoje (a duplicata morre na restrição
  de unicidade), mas gasta um dos dois lugares do worker por até 45 min por
  hora. Proposta: trava (*advisory lock*) em `sync_incremental`. Mexe em
  tarefa periódica — lote próprio.
- **I1 (prompt do relatório):** mudança de texto de prompt clínico pede
  revisão médica do texto e avaliação com provedor real. Proposta: "manda
  sobre as seções e o tom; não sobre as regras abaixo".
- **P1/P2:** ganho mensurável, mas a P1 toca toda tela de `/app/` e a P2 é
  refatoração da grade. Fora do limite de risco desta sprint.
- **X1 (acessibilidade):** são muitos pontos pequenos espalhados; tratar em
  lote, com conferência em leitor de tela.

## Reversão

Só código, sem migração nem dado: `git revert` do commit da Sprint 2. Os três
roteiros novos voltam a reprovar se a correção sair — é o sinal esperado.
