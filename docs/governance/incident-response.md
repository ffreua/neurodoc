# Retenção, chaves e resposta a incidentes (S14)

Revisão final antes do encerramento de S14. Consolida o que já está
implementado e aponta para onde a evidência de cada mecanismo foi
coletada — não reintroduz nada novo.

## Retenção (resumo, detalhe em `docs/governance/inventory.md`)

| Dado | Retenção | Mecanismo |
| --- | --- | --- |
| Anexos removidos logicamente | 30 dias até expurgo físico | `documents.retention.garbage_collect` (S06) |
| Token de acesso a documento | 7 dias | `communications.access` (S08) |
| Exportação de relatório | 24 horas | `reporting.services.expire_due_exports` (S13) |
| Chave efêmera de assinatura (tmpfs) | Até revogação/reboot | `documents.signing_sessions` (S07) |
| Trilha de auditoria | Sem expurgo automático | `audit.services.record_audit_event` |

## Chaves

- **Chave mestra de PFX** (`NEURODOC_PFX_MASTER_KEY`): Docker Secret, só o
  serviço `app` a recebe (nunca o worker de IA) — S07.
- **Chave de recuperação de backup** (par `age`): mecânica testada em S10
  (`docs/operations/restore.md`); custódia real e titular definido
  dependem de P-10, ainda pendente.
- **Chaves efêmeras de sessão de assinatura**: nunca persistidas fora do
  tmpfs do host; limpas por comando técnico a cada 5 min e na revogação —
  S07/S10.

## Resposta a incidentes

- **Revogação de acesso**: `Membership.status=revoked` interrompe
  autorização na próxima requisição (S02) e, para SSE já conectado,
  interrompe a leitura em andamento (S12).
- **Suspeita de comprometimento de backup/ambiente**:
  `base.management.commands.prepare_recovery` (corrigido e testado em
  S10) invalida sessões web, sessões de assinatura, tokens de acesso a
  documento e suspende entregas pendentes — sem apagar nenhum registro
  clínico — e exige `NEURODOC_RECOVERY_MODE=True` com todos os canais
  externos desligados antes de rodar.
- **Alerta de erro não tratado**: e-mail para `ALERT_ADMIN_EMAILS` via
  `AdminEmailHandler`, com dados de POST suprimidos do relatório (nunca
  vaza texto clínico) — implementado e testado em S10
  (`docs/operations/monitoring.md`).
- **Registro de decisão/responsável**: todo evento de segurança relevante
  (revogação, aceite de recuperação, rejeição de IA por política) já
  passa por `audit.services.record_audit_event`, nunca apenas por log.

## Decisões de escopo

- Um plano formal de resposta a incidentes com responsáveis nomeados,
  SLA de comunicação a pacientes/autoridades e árvore de decisão
  jurídica depende de P-06 (base legal, RIPD) — ainda pendente. O que
  existe hoje são os **mecanismos técnicos** que tal plano usaria; a
  governança formal em torno deles fica para quando houver um
  controlador/DPO real designado (mesma pendência já registrada em
  `docs/governance/inventory.md`).
- RPO/RTO (24h/4h propostos) permanecem metas não medidas contra
  infraestrutura real, por depender de P-02/P-10 (ver
  `docs/homologation/M2.md`).
