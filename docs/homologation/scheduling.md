# Homologação — Agenda e trabalho da secretaria (S04)

Evidência coletada via scripts de verificação (`python manage.py shell`) contra
a pilha real (models, services, constraints do banco) e via
`django.test.Client` contra as views reais. Dados sintéticos apenas.

## H-12 — Agenda

- [x] Regra semanal inválida (`local_start >= local_end`) é rejeitada no
  `clean()`; regra válida (segunda-feira 09:00–12:00, slots de 30 min) produz
  6 horários livres antes de qualquer bloqueio.
- [x] Exceção datada (`ScheduleBlock`, kind=`block`) prevalece sobre a regra
  semanal sem alterá-la: bloquear 10h–11h reduz os horários livres do dia sem
  tocar `AvailabilityRule`.
- [x] **Duas reservas sobrepostas para o mesmo médico**: a segunda tentativa no
  mesmo horário é rejeitada pela `ExclusionConstraint` do PostgreSQL
  (`btree_gist`, intervalo semiaberto `[início,fim)`) — testado diretamente
  contra o banco real, não apenas em memória. Reservas **adjacentes** (fim de
  uma = início da outra) são aceitas, conforme a semântica semiaberta exigida.
- [x] Encaixe (`is_overbook=True`) exige justificativa (`override_reason`) —
  sem ela, o serviço recusa antes mesmo de tentar gravar; com justificativa,
  o encaixe é aceito mesmo sobrepondo uma reserva comum (a
  `ExclusionConstraint` só se aplica a `is_overbook=False`).
- [x] Transições ilegais são recusadas no service (ex.: `scheduled` →
  `completed` diretamente, pulando `checked_in`/`in_progress`), tanto na API
  Python quanto via `POST /app/scheduling/<id>/<action>/` (resposta 409, sem
  erro 500).
- [x] Fluxo real via HTTP: `confirm` → `check-in` → `start` → `complete`
  percorrido com sucesso pelas rotas reais; cancelar um atendimento já
  concluído responde 409 sem corromper estado.
- [x] Remarcar é atômico e **invalida os lembretes da versão anterior**: dois
  `OutboxEvent` (24h/2h antes) são criados na reserva; após remarcar, os dois
  da versão antiga viram `cancelled` e dois novos são criados na versão
  corrente — confirmado via consulta direta ao banco.
- [x] Cancelamento não apaga a reserva (mantém histórico/trilha de estados);
  libera a agenda apenas no sentido de que uma nova reserva no mesmo horário
  não colide mais (`ExclusionConstraint` só considera status ocupantes).
- [x] Painel da secretaria (`/app/scheduling/desk/`) mostra apenas
  nome/contato/médico/status — nenhum termo clínico (diagnóstico, hipótese,
  queixa, CID, exame) aparece na página, testado por busca textual no HTML
  renderizado real.
- [x] Calendário dia/semana/mês implementado como três views distintas com
  navegação por link/botão (não depende de arrastar); remarcar usa um
  formulário dedicado (`/app/scheduling/<id>/reschedule/`) com verificação de
  `row_version` (409 em conflito de edição concorrente).

## Decisões de escopo

- A UI desta sprint é deliberadamente simples (tabelas/listas HTML sem
  JavaScript de calendário visual) — prioriza corretude do backend
  (constraint de banco, transições, locks) sobre polimento visual, que é
  objeto de S14 (integração com o design system real).
- `override_by` (quem autorizou o encaixe) fica `None` nesta sprint por falta
  de uma tela de aprovação de encaixe por terceiro; a justificativa textual
  já é obrigatória e auditada, o que satisfaz o aceite de S04-T05. Uma tela de
  aprovação explícita pode ser adicionada depois sem migração incompatível.
- Lembretes ficam registrados como `OutboxEvent`; o *dispatcher* que
  efetivamente os envia (e-mail/SMS) é objeto de S08.
