# Fluxos centrais de operação Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir integralmente os fluxos de colaboradores, IA, contatos, indicadores e cobrança sem enfraquecer isolamento, auditoria ou imutabilidade clínica.

**Architecture:** Convites e credenciais permanecem em `tenancy`/`accounts`; tarefas assíncronas publicam notificações e a leitura tardia de laudo vira adendo; cobrança passa a ter o agendamento como origem no check-in e associa o atendimento depois. Consultas de indicadores filtram apenas cadastros completos.

**Tech Stack:** Django, PostgreSQL, Celery, django-otp, templates Bootstrap e scripts de regressão em `checks/`.

**Spec:** `docs/superpowers/specs/2026-09-28-colaboradores-ia-financeiro-indicadores.md`

## Global Constraints

- Nenhuma informação clínica ou token bruto entra em log, notificação ou auditoria.
- Todo acesso é limitado ao inquilino ativo.
- Atendimento finalizado permanece imutável; conteúdo posterior entra como `ClinicalAmendment`.
- Envio de e-mail usa o backend assíncrono já configurado para o worker.
- Operações de credencial são auditadas e o reset de MFA exige prova MFA atual do responsável.

---

### Task 1: Convite e verificação de e-mail

**Files:**
- Modify: `tenancy/forms.py`
- Modify: `tenancy/admin_views.py`
- Modify: `tenancy/views.py`
- Modify: `tenancy/invitations.py`
- Modify: `accounts/urls.py`
- Create: `templates/tenancy/email/collaborator_invitation.txt`
- Modify: `templates/tenancy/collaborator_invited.html`
- Modify: `checks/check_email.py`

**Interfaces:**
- Produces: `invitation_url(request, token) -> str` e `send_collaborator_invitation(invitation, token, request) -> str`.
- Consumes: `accounts.services.send_email_verification(user, request)`.

- [ ] Escrever regressões para URL absoluta, e-mail automático, duas senhas, verificação do novo usuário e POST de reenvio.
- [ ] Executar os roteiros e confirmar falhas pelos comportamentos ausentes.
- [ ] Implementar URL absoluta e envio, mantendo o botão de copiar como alternativa.
- [ ] Trocar o formulário por `password1`/`password2` e validar igualdade antes de consumir o convite.
- [ ] Enviar verificação após criar a conta e declarar `verify-email/resend` antes da rota dinâmica.
- [ ] Executar novamente as regressões.

### Task 2: Administração segura de credenciais da equipe

**Files:**
- Modify: `accounts/services.py`
- Modify: `tenancy/admin_views.py`
- Modify: `tenancy/urls.py`
- Modify: `templates/tenancy/team.html`
- Create: `templates/accounts/email/security_reset_notice.txt`
- Modify: `checks/check_convite.py`

**Interfaces:**
- Produces: `send_password_reset(user, request)`, `invalidate_user_sessions(user)` e views POST de senha/MFA.
- Consumes: `accounts.mfa.verify_totp_token` e `RecoveryCode`.

- [ ] Escrever testes de escopo, e-mail de senha, recusa sem código MFA, remoção dos dispositivos/códigos e sessões.
- [ ] Confirmar as falhas antes da implementação.
- [ ] Implementar ações apenas sobre membro do inquilino, proibindo auto-reset de MFA.
- [ ] Auditar cada ação e notificar o colaborador sem revelar segredos.
- [ ] Executar novamente as regressões.

### Task 3: Conclusão e revisão das tarefas de IA

**Files:**
- Modify: `ai/services.py`
- Modify: `ai/tasks.py`
- Modify: `ai/extraction.py`
- Modify: `ai/views.py`
- Modify: `notifications/targets.py`
- Modify: `clinical/views.py`
- Modify: `templates/ai/job_detail.html`
- Modify: `templates/clinical/_exam_results.html`
- Modify: `templates/clinical/_exam_draft.html`
- Create: `static/ai/job-status.js`
- Modify: `checks/check_ia_plano.py`
- Create: `checks/check_ia_assincrona.py`

**Interfaces:**
- Produces: notificação `target_type='ai_job'`, timeout documental de 180 s e `accept_draft_as_amendment(...)`.
- Consumes: `clinical.finalization.add_amendment(...)`.

- [ ] Escrever testes para notificação terminal, atualização da tela, timeout de 180 s e revisão pós-finalização.
- [ ] Confirmar as falhas antes da implementação.
- [ ] Publicar notificação de sucesso/falha e recarregar a tela enquanto o job está ativo.
- [ ] Permitir nova tentativa de leitura após finalização e aceitar o resultado somente como adendo.
- [ ] Ajustar textos para explicar extração/transcrição e revisão médica, sem prometer diagnóstico automático.
- [ ] Executar novamente as regressões.

### Task 4: Edição de contatos

**Files:**
- Modify: `patients/views.py`
- Modify: `patients/urls.py`
- Create: `templates/patients/contact_form.html`
- Modify: `templates/patients/detail.html`
- Modify: `checks/check_precadastro.py`

**Interfaces:**
- Produces: `PatientContactUpdateView` escopada por paciente e inquilino.
- Consumes: `PatientContactForm` e `confirm_contact_channels`.

- [ ] Escrever regressão para editar telefone/e-mail, renovar confirmação e impedir contato de outro inquilino.
- [ ] Confirmar a falha antes da implementação.
- [ ] Implementar tela, rota, auditoria e link “Editar”.
- [ ] Executar novamente a regressão.

### Task 5: Indicadores e pré-cadastro

**Files:**
- Modify: `reporting/patients.py`
- Modify: `reporting/views.py`
- Modify: `tenancy/limits.py`
- Modify: `templates/reporting/dashboard.html`
- Modify: `checks/check_precadastro.py`

**Interfaces:**
- Produces: consultas de carteira/idade/cota filtradas por `RegistrationStage.COMPLETE`.

- [ ] Escrever regressões provando que pré-cadastro não altera carteira nem cota.
- [ ] Confirmar as falhas antes da implementação.
- [ ] Aplicar o filtro e remover a consulta/cartão de localização.
- [ ] Executar novamente a regressão.

### Task 6: Cobrança no check-in

**Files:**
- Modify: `finance/models.py`
- Modify: `finance/receivables.py`
- Modify: `finance/handlers.py`
- Create: `finance/migrations/0004_receivable_appointment.py`
- Modify: `scheduling/services.py`
- Modify: `clinical/views.py`
- Create: `checks/check_cobranca_checkin.py`

**Interfaces:**
- Produces: `create_receivable_for_appointment(appointment, actor_id)` e `attach_encounter_to_receivable(encounter)`.
- Consumes: `resolve_price(..., appointment_type=appointment.type)`.

- [ ] Escrever regressões para check-in, idempotência, tipos de consulta, associação posterior e ausência de cobrança em adendo.
- [ ] Confirmar as falhas antes da implementação.
- [ ] Tornar `Receivable.encounter` opcional, adicionar `appointment` e restrições condicionais de unicidade/origem.
- [ ] Criar recebível durante check-in e associá-lo quando o atendimento correspondente for aberto/finalizado.
- [ ] Reparar de forma idempotente agendamentos já em check-in/concluídos que possuam honorário aplicável.
- [ ] Executar novamente as regressões.

### Task 7: Verificação e publicação

**Files:**
- Modify: `checks/README.md`
- Create: `docs/releases/<sha>.md` somente na VPS durante o deploy.

**Interfaces:**
- Consumes: todos os comportamentos anteriores.

- [ ] Executar testes focados, todos os roteiros, `manage.py check`, `makemigrations --check` e `git diff --check`.
- [ ] Validar em navegador convite, cópia, formulário de senha, contato e atualização do job.
- [ ] Revisar o diff contra cada requisito da especificação.
- [ ] Commitar, enviar, executar preflight/deploy e verificar migrações, serviços, saúde e reparos em produção.

