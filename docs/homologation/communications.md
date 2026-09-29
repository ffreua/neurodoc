# Homologação — Comunicações, outbox e notificações (S08)

## Retenção da caixa de notificações

O sino é uma caixa transitória, não a trilha de auditoria do sistema.
Notificações lidas são excluídas fisicamente **7 dias após a leitura**; as não
lidas, **15 dias após a criação**. A limpeza roda diariamente às 01:10 e não
remove o prontuário, documento, solicitação ou evento de auditoria que originou
o aviso.

Evidência coletada via scripts de verificação (`python manage.py shell`) contra
a pilha real e via `django.test.Client` contra as views públicas reais.
Nenhuma conta SMSDEV real foi usada (P-03 permanece pendente,
`SMS_ENABLED=False` neste ambiente) — ver "Decisões de escopo".

## H-09 — Entrega e lembretes

- [x] **Emissão de documento gera entrega em cada canal elegível**: um
  documento assinado (S07) dispara `documents.document_issued` no outbox; o
  dispatcher genérico processa o evento e `communications.services.
  deliver_document` cria uma `Delivery` por canal habilitado/confirmado do
  contato (`email_enabled`+`verified_email_at`, `sms_enabled`+
  `verified_phone_at`) — testado com um contato com os dois canais
  habilitados: e-mail foi efetivamente enviado (capturado no backend
  `locmem`), SMS ficou `no_contact` porque o canal está desabilitado na
  plataforma (`SMS_ENABLED=False`), nunca fingindo sucesso.
- [x] **Ausência de contato elegível vira pendência, não erro**: paciente
  sem nenhum contato autorizado para documentos gera uma `Notification`
  (`kind=delivery_pending_contact`) para os papéis `secretary`/`owner` do
  tenant — testado diretamente, sem conteúdo clínico no título
  (`sanitized_title` é um texto fixo genérico).
- [x] **Link opaco + resposta que o paciente sabe** (DEC-21): o link
  enviado nunca abre o documento diretamente — a página pública
  (`/d/<token>/`) sempre exige os **quatro últimos dígitos do CPF** do
  paciente, ou a **data de nascimento** quando não há CPF cadastrado
  (criança, na maioria das vezes), com até 5 tentativas (`MAX_ATTEMPTS`);
  o link vale 30 dias (`TOKEN_VALIDITY_DAYS`).

  Esta homologação descrevia, até 2026-09-19, o mecanismo anterior —
  código de 8 dígitos válido por 10 minutos enviado ao contato verificado,
  link de 7 dias. Aquele texto continuou no documento **depois** de o
  código ter sido substituído, de modo que a homologação estava assinada
  sobre um comportamento que o sistema já não tinha. O registro da troca,
  com o que se perde e o que se ganha, está em `communications/access.py`
  e em DEC-21.

  O que sustenta a proteção hoje é o **link**: 32 bytes aleatórios,
  entregues só a contato autorizado e verificado, com prazo e revogação. Os
  quatro dígitos não são segredo forte — são 10.000 combinações contra
  cinco tentativas, e o contador é atômico (`UPDATE ... otp_attempts + 1`
  condicionado ao limite), de modo que requisições paralelas não contam
  como uma.

  Testado: resposta errada → 403 sem liberar o PDF; resposta certa → libera
  o PDF (bytes reais, `Content-Type: application/pdf`); token revogado
  depois da verificação bem-sucedida **ainda assim** passa a responder 404
  na próxima visita — a revogação é checada em `resolve_token()` a cada
  acesso, não apenas na tela de verificação, então uma sessão de navegador
  já "verificada" não sobrevive a uma revogação.
- [x] **`accepted` ≠ `delivered`**: o envio bem-sucedido ao SMSDEV (ou ao
  backend de e-mail) só move o status para `accepted`; `delivered` exigiria
  confirmação real via DLR (`communications.reconciliation`), que não pôde
  ser exercitada contra um provedor real (ver decisões de escopo).
  `communications.reconciliation.reconcile_pending_sms` foi testado
  diretamente: com o canal SMS desabilitado, cada tentativa de consulta de
  status falha graciosamente e o agendamento avança pela janela
  1/5/15/60 minutos sem travar nem lançar exceção — após esgotar a janela,
  o status vira `unknown` permanentemente ("depois revisão administrativa"),
  nunca reenvio automático cego.
- [x] **Redelivery do outbox não duplica efeito**: um `OutboxEvent` já
  processado, recolocado manualmente em `pending` (simulando uma
  redelivery/lease reclamado de um worker morto), é reconhecido via
  `ProcessedEvent` (chave única `event+consumer`) e **não** executa o
  handler de novo — testado diretamente contando quantas vezes o handler de
  teste foi chamado (1, não 2) antes e depois da redelivery simulada.
- [x] **Remarcar invalida o lembrete antigo**: reservar uma consulta cria
  `OutboxEvent` de 24h/2h; remarcar invoca `invalidate_stale_reminders`
  (já existente desde S04) **antes** de o dispatcher rodar, então o evento
  de 24h nunca chega a ser processado com o horário antigo — confirmado
  lendo o status (`cancelled`) diretamente após o `reschedule_appointment`.
- [x] **Indisponibilidade de SMTP/SMS não invalida o prontuário/documento**:
  uma falha de envio (`EmailSendFailed`/`SmsSendFailed`) é capturada dentro
  de `_send()`, registra uma `DeliveryAttempt` com o resultado e retorna sem
  levantar exceção — o `MedicalDocument` já está `issued` antes do outbox
  sequer tentar a entrega (o evento só é criado depois que a assinatura é
  persistida), então uma falha de entrega nunca reverte a emissão.

## Decisões de escopo

- **P-03 (credenciais SMTP/SMSDEV reais) permanece aberto.** `SMS_ENABLED`
  e o backend real de e-mail continuam desligados neste ambiente. O
  adaptador `communications/smsdev.py` implementa o contrato documentado
  publicamente (POST JSON, `key`/`type=9`/`number`/`msg`/`refer`, endpoint
  `https://api.smsdev.com.br/v1/{send,dlr}`), mas o **schema exato da
  resposta de envio e do DLR não foi homologado contra uma conta real** —
  `_extract_situacao()` (`communications/reconciliation.py`) documenta essa
  limitação explicitamente e trata qualquer formato não reconhecido como
  "ainda desconhecido" (nunca inventa um status de sucesso).
- O backend de e-mail usa o framework nativo do Django
  (`django.core.mail`), que já resolve automaticamente entre SMTP real
  (produção, quando `EMAIL_ENABLED=True`) e `locmem` (usado nesta
  homologação) — não há adaptador próprio a manter.
- Sem um evento de confirmação de leitura real (não existe no baseline de
  e-mail), uma entrega por e-mail bem-sucedida permanece `accepted`
  indefinidamente — nunca é promovida a `delivered` sem evidência real,
  conforme H-09 exige.
- A tarefa periódica `events.tasks.dispatch_outbox` roda a cada 5s e
  `communications.tasks.reconcile_pending_sms` a cada 1 minuto, ambas via
  `CELERY_BEAT_SCHEDULE`. A tabela de lembretes 24h/2h já existia (S04); o
  que esta sprint acrescenta é o dispatcher genérico que efetivamente os
  consome.
- Contatos elegíveis para **lembretes de agenda** usam apenas
  `sms_enabled`/`email_enabled` + verificação — não exigem
  `authorized_for_documents` (que é uma permissão específica para
  documentos médicos, não para avisos administrativos de horário).
- `Notification` não tem tela de contagem/badge nesta sprint (apenas lista +
  marcar como lida) — a integração visual com o design system fica para
  S14, mesmo padrão de todas as sprints anteriores.
