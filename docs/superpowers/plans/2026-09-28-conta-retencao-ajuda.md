# Conta, retenção e ajuda — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Manter a edição da própria conta dentro do aplicativo, eliminar dados transitórios nos prazos aprovados e substituir as capturas inválidas da ajuda.

**Architecture:** A rota atual de “Minha conta” continua sendo a alternativa sem JavaScript e para contas sem clínica; dentro do shell ela também responde com um fragmento carregado e salvo no modal. Duas tarefas Celery diárias apagam notificações e entregas vencidas, com tentativas de entrega removidas antes do registro protegido. O capturador da ajuda passa a visitar as rotas atuais e a abrir o modal de registro profissional.

**Tech Stack:** Django, Django Templates, JavaScript sem framework, Celery Beat, PostgreSQL, Playwright.

**Spec:** desenho aprovado nesta conversa em 28/09/2026; notificações lidas por 7 dias, não lidas por 15 dias e entregas por 15 dias, sempre com exclusão física.

## Global Constraints

- Preservar a rota autônoma de “Minha conta” para quem não possui contexto de clínica.
- Excluir fisicamente somente notificações vencidas, `Delivery` vencidas e seus `DeliveryAttempt`; não apagar documentos, consultas, agendamentos, contatos nem auditoria.
- Entregas ainda em processamento não podem ser removidas.
- Toda mudança de comportamento nasce de um roteiro que falha antes da implementação.
- As capturas públicas usam somente os dados sintéticos de demonstração.

---

### Task 1: Overlay de Minha conta

**Files:**
- Modify: `accounts/views.py`
- Modify: `templates/accounts/minha_conta.html`
- Create: `templates/accounts/_minha_conta_panel.html`
- Modify: `templates/partials/header.html`
- Modify: `templates/base.html`
- Modify: `static/duralux/app.js`
- Create: `checks/check_minha_conta_overlay.py`

**Interfaces:**
- Consumes: `MinhaContaForm`, `MinhaContaView._contexto`, `window.NeuroDoc.openModal`.
- Produces: resposta HTML parcial quando `X-Requested-With=XMLHttpRequest`, formulário modal com `data-nd-account-form` e fallback navegável.

- [ ] Escrever o roteiro que exige o gatilho do modal, o fragmento autenticado, erros 400 no fragmento e salvamento sem redirecionamento.
- [ ] Executar o roteiro e confirmar falha pela ausência do contrato de overlay.
- [ ] Extrair o corpo reutilizável do formulário e fazer a view distinguir página completa de requisição assíncrona.
- [ ] Ligar carregamento, envio, substituição dos erros e atualização do nome do cabeçalho no JavaScript global.
- [ ] Executar o roteiro e os roteiros de conta/MFA existentes.

### Task 2: Retenção física de notificações e entregas

**Files:**
- Create: `notifications/retention.py`
- Create: `notifications/tasks.py`
- Create: `communications/retention.py`
- Modify: `communications/tasks.py`
- Modify: `core/settings.py`
- Modify: `PRD.md`
- Create: `checks/check_retencao_transitoria.py`
- Modify: `docs/homologation/mensageria.md`
- Modify: `docs/homologation/communications.md`

**Interfaces:**
- Produces: `purge_expired_notifications(now=None) -> dict`, `purge_expired_deliveries(now=None) -> dict` e tarefas Celery nomeadas.
- Regra de notificação: lida vence por `read_at < now - 7 dias`; não lida vence por `created_at < now - 15 dias`.
- Regra de entrega: registro terminal com `created_at < now - 15 dias`; tentativas filhas são apagadas primeiro devido ao `PROTECT`.

- [ ] Criar dados nas fronteiras dos prazos e escrever o roteiro que exige preservação e exclusão corretas.
- [ ] Executar o roteiro e confirmar falha porque as funções ainda não existem.
- [ ] Implementar as duas operações idempotentes e as tarefas Celery.
- [ ] Agendar a limpeza diária em horário fora do backup e das demais rotinas pesadas.
- [ ] Executar o roteiro duas vezes para provar idempotência e os roteiros de mensageria/notificações.

### Task 3: Capturas válidas da ajuda

**Files:**
- Modify: `ops/capturar_ajuda.py`
- Modify: `static/help/convenios-lista.png`
- Modify: `static/help/convenios-valores.png`
- Modify: `static/help/equipe-lista.png`
- Modify: `static/help/equipe-registro.png`
- Modify: `checks/check_ajuda.py`

**Interfaces:**
- Produces: capturas das rotas `/app/org/convenios/`, `/app/org/valores/`, `/app/org/equipe/` e do modal `#crm-*` aberto na tela de equipe.

- [ ] Estender o roteiro da ajuda para exigir as quatro capturas e rejeitar respostas de erro durante a captura.
- [ ] Confirmar que o capturador atual não possui essas telas.
- [ ] Adicionar as quatro telas e o preparo que abre o modal de registro profissional.
- [ ] Rodar `scripts/capturar_ajuda.sh` e conferir visualmente os quatro arquivos.
- [ ] Rodar `check_ajuda.py` e confirmar ausência de imagens duplicadas ou órfãs.

### Task 4: Release e produção

**Files:**
- Modify: `docs/homologation/help-center.md`
- Modify: `docs/homologation/mensageria.md`
- Modify: `docs/operations/diario-do-primeiro-deploy.md`

**Interfaces:**
- Consumes: `scripts/deploy.sh`, healthchecks Swarm e consultas somente leitura de produção.
- Produces: release versionada, serviços saudáveis e primeira limpeza executada de forma explícita.

- [ ] Rodar os roteiros focados, `manage.py check` e a bateria completa disponível.
- [ ] Revisar `git diff`, conferir que nenhum segredo ou dado real entrou nas imagens e registrar a release.
- [ ] Commitar e publicar a imagem pelo mecanismo existente.
- [ ] Executar uma vez as duas tarefas de retenção na produção e registrar as contagens removidas.
- [ ] Comprovar réplicas saudáveis, HTTPS 200 e ausência de erros novos nos logs.
