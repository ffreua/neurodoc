# O despachante da outbox, depois da auditoria de 2026-10-09

Em 09/10/2026 uma auditoria externa (outra IA, com acesso só de leitura
ao código e ao coletor `audit-status` da VPS) leu o processamento
assíncrono e listou oito achados, A1 a A8. Este documento diz o que
procedeu, o que foi corrigido, o que ficou de fora e por quê.

**Nenhum dos oito era incidente em curso.** Antes de mexer, a outbox, as
entregas e os jobs de IA de produção foram contados (só contagens, sem
dado de paciente):

| O que se olhou | O que havia |
| --- | --- |
| Eventos em `processing` | nenhum |
| Eventos pendentes vencidos | nenhum |
| Jobs de IA parados em `queued` | nenhum |
| `scheduling.appointment_reserved`, tentativas | **até 2.886** — o laço "sem consumidor" do A7, que alimentou o incidente de 07/10 |
| `documents.document_issued`, tentativas | até 9 em um evento, concluído |

O A7 não era hipótese: era o mecanismo do acidente de 07/10 (dez
e-mails de "consulta marcada" sobre consultas passadas e canceladas). E
a guarda que nasceu daquele acidente tinha o defeito do A6 — ver abaixo.

## Achado por achado

| | Procede? | O que foi feito |
| --- | --- | --- |
| **A1** lease sem dono | Sim. O risco de **efeito em dobro** era menor do que o relatório sugere — a chave de idempotência de `Delivery`, de `Receivable` e de `AIJob` serializa os consumidores concorrentes —, mas o despachante antigo podia sobrescrever o desfecho do novo | `locked_until` virou **token de posse**: todo passo é `UPDATE` condicionado ao valor gravado no claim; posse renovada antes de cada consumidor; prazo de 30 s para 120 s |
| **A2** e-mail perdido se a fila falhar depois do commit | Sim, e o gatilho é estreito (o RabbitMQ cair entre o commit e a publicação, dentro do worker que acabou de receber uma tarefa dele) | Mitigado, **não resolvido** — ver "O que ficou de fora" |
| **A3** job de IA publicado antes de existir | Sim | Consumidor fora de transação externa + `on_commit`; e **`ai.tasks.retomar_jobs_parados`** a cada 10 min |
| **A4** SMS saindo antes do commit do token | Sim | O despachante não envolve mais o consumidor num `atomic`; o token é confirmado pela transação curta de `deliver_document` **antes** do envio, como o comentário dela sempre disse |
| **A5** lembrete de consulta cancelada | Sim | Estado e horário conferidos em `deliver_appointment_reminder`; lembrete substituído por remarcação descartado em `scheduling.handlers` |
| **A6** idade medida pelo campo que rejuvenesce | Sim — **e anulava a guarda do incidente de 07/10**: um evento sem consumidor tinha `available_at` empurrado a cada 5 min, então sempre parecia ter menos de 5 min de idade | `created_at` |
| **A7** evento sem consumidor sem limite | Sim, o contador; a espera indefinida é deliberada | A tentativa do claim é devolvida quando não há consumidor |
| **A8** exceção sem contexto | Sim | Log com evento, tópico, consumidor, tentativa e classe do erro; abandono como `ERROR` |

### A recomendação do A5 que **não** foi seguida ao pé da letra

O relatório recomendava conferir se o agendamento "continua na versão do
evento". Feito assim, **calaria o lembrete de toda consulta confirmada**:
`row_version` sobe também ao confirmar e ao trocar o tipo de consulta
(`transition_appointment`, `change_appointment_type`), e nenhum dos dois
reagenda lembrete. O critério usado é outro: há evento de lembrete **mais
novo** para o mesmo horário e o mesmo tópico? Só remarcar e trocar o
paciente criam um — e são exatamente os casos em que o lembrete antigo
mente. `check_despachante.py` §7 cobra os dois lados.

### Por que tirar a transação externa é seguro

Ela parecia dar "efeito e marcador juntos". O que dava, na prática, era
o contrário do que cada consumidor pedia: `deliver_document` abre uma
transação curta para gravar o token **antes** de enviar, e dentro da
externa essa transação virava ponto de salvamento — o token só existia
para outra conexão depois que o SMS já tinha saído, e uma falha adiante o
desfazia com a mensagem já entregue.

Sem ela, um consumidor que falha no meio deixa gravado o que fez. Os
consumidores registrados aguentam isso porque cada um é
idempotente por chave própria:

| Consumidor | Chave |
| --- | --- |
| `communications.document_issued` | `Delivery.idempotency_key` (documento × contato × canal) |
| `communications.appointment_*` | `Delivery.idempotency_key` (motivo × horário × versão × contato) |
| `scheduling.appointment_reminder` | `Delivery.idempotency_key` (horário × versão × contato × canal) |
| `finance.encounter_finalized` | `Receivable` por atendimento, sob `select_for_update` na própria transação |
| `ai.encounter_finalized` | `AIJob.idempotency_key` |

**Consumidor novo tem de seguir a mesma regra** — está escrito em
`register_handler`.

## O que ficou de fora, e o que custa

**A2 por inteiro.** A correção completa é guardar a *intenção* de envio
no banco e um processo que a publique e a recupere. Para o e-mail da
instalação isso esbarra num detalhe que pesa: a mensagem de documento
carrega o **token cru** no link, e gravá-la para reenvio poria no banco
o que hoje só existe como hash. O que mudou:

- fora de transação, a falha de publicação cai em `_send` e a entrega
  fica registrada como **tentativa falha**, não como "aceita" — a lista
  de entregas mostra, e a secretária reenvia;
- por isso `deliver_appointment_reminder` perdeu o `@transaction.atomic`:
  com ele, a falha acontecia depois do commit que já dizia "aceita";
- `mail_backend._publicar` registra a falha em `ERROR`, sem destinatário
  nem assunto.

O caso que sobra: e-mail enviado de dentro de uma transação que fecha
(verificação de conta, convite) quando a fila cai naquele instante. A
pessoa vê o erro na tela e repete.

**Sem estado próprio para evento sem consumidor (A7).** Seria uma
migração e uma tela; o problema que custava — o contador — foi resolvido.

**Execução mais longa que o lease.** Um consumidor que passe de dois
minutos pode ser retomado por outro despachante enquanto ainda roda. Os
consumidores de hoje levam segundos (o de IA só enfileira), e a chave de
idempotência continua sendo a rede embaixo.

## Verificação

`check_despachante.py`, contra o PostgreSQL do ambiente local:

1. despachante que perdeu a posse não roda o consumidor nem grava o
   desfecho (a reprodução da auditoria, invertida);
2. a posse perdida no meio impede o consumidor seguinte;
3. o consumidor roda com `connection.in_atomic_block == False`;
4. falha deixa log com evento, consumidor e classe; abandono sai como
   erro;
5. evento sem consumidor volta com `attempts` intacto;
6. evento de dez dias com `available_at` de um minuto é barrado;
7. lembrete: agendada e **confirmada** seguem; cancelada, falta,
   chegada, concluída e já começada não; versão substituída não;
8. job de IA: 5 min intocado, 1 h reenfileirado (uma vez só), 2 dias vira
   falha com a explicação.

A bateria inteira (`rodar_roteiros`) passou junto.
