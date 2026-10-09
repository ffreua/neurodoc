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

`check_auditoria_lote1.py`: com o código anterior **reprova em 16
verificações** (e para no fim porque o código antigo gravou o pedido do
portal na ficha errada — o defeito em ação); com o novo, passa inteiro.
`check_g10.py` passou a mandar o token no formulário do portal, como o
navegador manda.
