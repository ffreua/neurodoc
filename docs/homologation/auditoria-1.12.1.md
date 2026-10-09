# A auditoria independente da 1.12.1

Em 09/10/2026 uma segunda auditoria externa (GPT Astra, relatórios em
`neurodoc-audit-1.12.1/`, fora deste repositório) examinou o snapshot
`fd9c039`: 150 verificações, 17 achados confirmados (4 P1, 13 P2), nenhum
vazamento entre clínicas. Todos os 17 foram conferidos no código antes de
qualquer mudança, e **todos procedem**. A prioridade é que foi revista: a
do relatório mede o pior caso teórico; a daqui mede o que pode acontecer no
consultório.

Antes de mexer, a produção foi medida (só contagens e metadados):

| Achado | O que havia em produção |
| --- | --- |
| ND-001 | 18 PDFs de documento médico, **todos** administrativos, mais 5 rascunhos órfãos; nenhum baixado por quem não é médico, nenhum excluído; coleta em ensaio |
| ND-006 | os 5 SMS "sem confirmação" são da clínica com chave própria |
| ND-007 | nenhum SMS aceito sem id do provedor |
| ND-008 | nenhum anexo em quarentena |

Nenhum dos achados tinha sido explorado.

## Lote 1 — segurança e perda de dado (1.12.2)

| Achado | O que foi feito |
| --- | --- |
| **ND-001** PDF de documento visível e removível pela recepção | O PDF gerado nasce **clínico** (guarda de 20 anos). Quem abre é decidido pela relação com o documento: **emitido**, a recepção baixa e imprime (decisão do controlador, 2026-10-09); **rascunho**, só quem lê prontuário. Ninguém o remove pela lista de anexos — nem o médico: ele é o documento. A coleta de arquivos nunca o apaga. Migração `documents/0007` reclassifica os existentes |
| **ND-002** finalizar gravava a cópia velha | A finalização relê o atendimento sob a mesma trava do autosave e grava só os campos da finalização |
| **ND-003** reenvio revogava o próprio link | Revogação uma vez, antes do lote |
| **ND-010** `next` externo depois do MFA | `_safe_next`, como o resto do login; e "Invalid code." virou "Código inválido." |
| **ND-017** pedido do portal na ficha de outro paciente | O formulário leva o token da identificação que o abriu; outro token é 409, com o nome de quem está identificado agora |
| **ND-016** dois envios para uma entrega (regressão da 1.12.1) | Estado `sending`: a entrega passa de `pending` a `sending` num `UPDATE` condicional antes do transporte; quem perde não envia. Falha de transporte volta a `pending`, como antes. Migração `communications/0009` (só a lista de escolhas) |

### Duas coisas que o relatório não tinha visto

- **O rascunho órfão.** Emitir em papel troca o `pdf_attachment` do
  documento pelo PDF do papel; o rascunho anterior fica ligado ao paciente,
  com o conteúdo clínico, sem nenhum documento apontando para ele. Uma
  correção só pela relação o deixaria aberto. A migração o reconhece pelo
  nome que `documents.issuance` dá aos arquivos que gera.
- **A secretária não precisava adivinhar UUID.** O relatório descreve o
  acesso pela rota genérica com o id do anexo; na prática o PDF aparecia na
  lista de anexos do paciente, com nome e botão de baixar.

### Decisão do controlador

A recepção **imprime** receitas e relatórios emitidos para entregar ao
paciente. Por isso a regra não é "clínico fecha", e sim "emitido abre para
quem administra o cadastro do paciente" (`PATIENT_ADMIN`).

## Lote 2 — o restante barato (1.12.3)

| Achado | O que foi feito |
| --- | --- |
| **ND-004** IA depois de perder o papel médico | `build_ai_authorization` reconstrói as capacidades (`capabilities_for`) e exige `CLINICAL_AI`, como o chat já fazia; e o vínculo tem de ser do usuário do contexto. Antes de mexer: os 10 jobs de produção foram todos pedidos por vínculo com papel médico e CRM verificado |
| **ND-014** cópia velha reativa consulta cancelada | Remarcar, transições, troca de paciente e troca de tipo **releem a consulta sob trava**. Remarcar só vale para agendada ou confirmada e na versão que a tela viu; a recusa aparece na tela, e não como "o erro foi registrado". Cancelar ficou atômico com a invalidação dos lembretes e o evento |
| **ND-006** DLR com a chave errada | `check_delivery(..., tenant_id=delivery.tenant_id)` |
| **ND-007** "ERRO" com HTTP 200 | Só a recusa **explícita** (`situacao: ERRO`) vira `SmsSendFailed`; qualquer outra forma segue como antes |
| **ND-009** exportação vencida | O download confere `expires_at` |
| **ND-011** exportação duas vezes | Posse por `UPDATE` condicional de `queued` para `running`; quem perde não mexe |
| **ND-012** prazo da retomada de IA | A retomada não toca mais o `updated_at`; anota a última vez em `limits.retomado_em`. Falha ao publicar um job não derruba a rodada |
| **ND-013** descarte de texto livre | Texto livre e impressões contam como conteúdo, pedem motivo e aparecem no resumo do que se perde |
| **ND-015** falha de assinatura sem registro | A falha é registrada **depois** do rollback, numa transação própria — inclusive a senha errada do certificado, que também se perdia. O documento continua "pronto para assinar", que era o comportamento real |

### O que não foi seguido no ND-015

O relatório recomendava persistir o estado terminal `failed`. Não foi
feito: o comportamento que o médico vê hoje — e sempre viu, porque o
rollback desfazia o `failed` — é "tente de novo", e um erro inesperado da
biblioteca de assinatura não é defeito do documento. Trancá-lo em `failed`
obrigaria a refazer o documento. O que se perdia, e voltou, é o registro.
De quebra, esse erro deixou de virar "Server Error (500)" na tela.

### O que o relatório não tinha visto no ND-014

A tela de remarcar não conferia o estado da consulta **nunca**, nem sem
concorrência. E a troca de paciente e a troca de tipo tinham o mesmo
padrão de gravar a cópia velha inteira; receberam a mesma releitura.

## O que não se faz, e por quê

- **ND-005 / A2 por inteiro** — guardar a intenção de envio para reenviar
  exige estados novos e um desenho para o link de documento sem gravar o
  token cru. Decisão de desenho separada.
- **ND-002 nos "filhos"** — serializar a inclusão de medicação, exame e
  hipótese com a finalização mexe em cerca de dez telas do prontuário; a
  janela é de milissegundos e o risco de quebrar o atendimento é maior que
  o defeito. A perda real de texto, que é a da finalização, está fechada.
- Nada de infraestrutura (VPS maior, workers separados, outbox redesenhada)
  sem métrica que justifique — o próprio relatório diz o mesmo.

## Verificação

`check_auditoria_lote2.py`: com o código anterior **reprova em 19
verificações**; com o novo, passa inteiro.

`check_auditoria_lote1.py`: com o código anterior **reprova em 16
verificações** (e para no fim porque o código antigo gravou o pedido do
portal na ficha errada — o defeito em ação); com o novo, passa inteiro.
`check_g10.py` passou a mandar o token no formulário do portal, como o
navegador manda.
