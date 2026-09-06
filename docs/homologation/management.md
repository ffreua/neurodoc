# Homologação — CRM e financeiro (S09)

Evidência coletada via scripts de verificação (`python manage.py shell`) contra
a pilha real e via `django.test.Client` contra as views reais. Dados
sintéticos apenas.

## H-13 — CRM

- [x] Etapas administrativas (`CRMStage`) são um catálogo por tenant
  totalmente independente do estado clínico (`Encounter.status`) — mover um
  card não toca `Encounter`, `EncounterDiagnosis` nem nenhum outro modelo
  clínico; testado movendo um card entre etapas e confirmando que nenhum
  atendimento foi afetado.
- [x] Toda transição é registrada (`CRMTransition`: etapa anterior, etapa
  seguinte, ator) — testado: mover um card grava exatamente uma transição
  com `from_stage`/`to_stage`/`actor` corretos.
- [x] Grid administrativo (`/app/crm/`) filtra por etapa via querystring;
  cada movimentação é um `<button>` de formulário HTML comum — nenhum
  drag-and-drop é necessário, então a ação é alcançável e acionável só com
  teclado (Tab + Enter/Espaço), sem JavaScript.
- [x] **Nenhum diagnóstico aparece no card**: o template (`crm/board.html`)
  só renderiza `patient.full_name`, etapa, responsável, prazo e um resumo
  administrativo de texto livre — testado buscando um trecho de queixa
  clínica conhecida (“cefaleia”) no HTML renderizado real e confirmando
  ausência.
- [x] **Integração com agenda por evento explícito**: reservar uma consulta
  (`scheduling.services.reserve_appointment`) emite um `OutboxEvent`
  dedicado (`scheduling.appointment_reserved`, distinto dos eventos de
  lembrete) que o dispatcher genérico (S08) processa de forma assíncrona —
  o CRM cria ou move automaticamente o card do paciente para a etapa
  "Agendado" **sem** finalizar nenhum atendimento nem emitir documento,
  confirmado diretamente no banco após o dispatch.

## H-14 — Financeiro

- [x] **Vigência sem sobreposição para regras equivalentes**: uma segunda
  `FeeSchedule` com o mesmo médico/plano/procedimento/categoria e período
  sobreposto é recusada (`OverlappingFeeSchedule`) antes de gravar — via
  lock consultivo por chave (não por `EXCLUDE` do Postgres, que trataria
  `NULL` como sempre distinto de si mesmo e deixaria passar duas regras
  gerais sobrepostas; a checagem aqui é explícita em Python e trata `NULL`
  como um valor comparável de verdade). Uma regra **geral** (sem médico)
  coexiste sem conflito com uma regra **específica** de um médico para a
  mesma categoria — testado.
- [x] **Resolução por especificidade**: aplicado no médico com regra
  própria, resolve para a regra do médico; aplicado em outro médico sem
  regra própria, resolve para a regra geral. Ausência de qualquer regra
  aplicável (ex.: categoria `insurance` sem tabela cadastrada) levanta
  `NoApplicableFeeSchedule` de forma limpa, sem criar recebível algum — o
  evento de finalização fica `completed` no outbox (não é um erro de
  processamento; é uma pendência de cadastro), registrada como auditoria
  `finance.receivable_pricing_missing` para revisão administrativa.
- [x] **Snapshot histórico imutável**: alterar `gross_amount` de uma
  `FeeSchedule` **depois** de um recebível já ter sido gerado não altera
  `Receivable.expected_amount` nem `fee_snapshot` — confirmado lendo o
  recebível de volta após a alteração.
- [x] **Recebível idempotente por evento**: finalizar um atendimento emite
  `clinical.encounter_finalized`; o handler financeiro cria exatamente um
  `Receivable` por `(tenant, encounter, charge_kind)`. Chamar
  `create_receivable_for_encounter` de novo diretamente (simulando uma
  redelivery do outbox) retorna a **mesma** linha, sem duplicar cobrança —
  testado tanto pelo caminho feliz (constraint única) quanto pela
  guarda `IntegrityError` para uma corrida concorrente.
- [x] **Decimal e arredondamento conciliam**: pagamento parcial de R$100,00
  sobre uma cobrança de R$280,00 deixa saldo R$180,00 (`status=partial`);
  desconto de R$30,00 reduz `charged_amount` para R$250,00 (saldo
  R$150,00); segundo pagamento de R$150,00 zera o saldo (`status=paid`);
  um estorno de R$30,00 vinculado a um pagamento específico **não apaga**
  o pagamento original (`receivable.payments.count()` continua 2) — apenas
  reduz o recebido líquido, reabrindo o saldo para R$30,00
  (`status=partial`). Toda a aritmética usa `Decimal` quantizado a 2 casas
  com `ROUND_HALF_UP`.
- [x] **Ajuste/estorno não apaga o registro original**: `FinancialAdjustment`
  é sempre um registro novo e append-only; `Payment` nunca é editado ou
  removido por um estorno — confirmado diretamente acima.
- [x] **Competência vs. caixa**: a mesma cobrança aparece na visão de
  competência pela data do atendimento (`competence_date`) e na visão de
  caixa pela data em que o dinheiro efetivamente chegou (`paid_at`) —
  testado com um período contendo ambas as datas.
- [x] **Usuário financeiro não lê nota clínica**: as telas de financeiro
  (`/app/finance/`) e do card CRM foram varridas por busca textual do
  trecho de queixa clínica usado no atendimento de teste — ausente em
  ambas, confirmando que `Encounter.chief_complaint`/`hpi`/diagnósticos
  nunca são passados ao contexto desses templates.

## Decisões de escopo

- `FeeSchedule.physician=None` é a forma de expressar uma regra geral
  (aplicável a qualquer médico do tenant); `plan=None` significa
  particular; `procedure=None` significa "consulta padrão" (sem
  procedimento específico). A ordem de especificidade usada em
  `resolve_price` (médico+plano+procedimento → … → totalmente geral) é uma
  decisão de implementação razoável, não normatizada explicitamente pelo
  PRD.
- O CRM usa **um único card aberto por paciente** (o mais recente fora da
  etapa terminal "Concluído"); reservar uma nova consulta reaproveita esse
  card em vez de criar um card por consulta. Essa é uma simplificação
  deliberada; um modelo de "um card por jornada/oportunidade" poderia
  coexistir sem migração incompatível.
- `bootstrap_default_stages(tenant)` existe como função de serviço
  idempotente, mas **não é chamada automaticamente** na criação de um
  tenant nesta sprint — a integração com `seed_demo` (dados sintéticos de
  demonstração) é escopo de S14.
- Assim como nas sprints anteriores, o polimento visual (kanban arrastável,
  adequação ao design system) fica para S14; esta sprint prioriza a
  corretude do modelo administrativo/financeiro e seu isolamento do
  prontuário.
