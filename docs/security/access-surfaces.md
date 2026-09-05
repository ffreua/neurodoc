# Inventário de permissões e superfícies de acesso

Registro de S01-T10 (RT-02/RT-03): toda superfície de acesso deve negar por
padrão e nenhum relacionamento cruzado entre tenants é permitido. Este
inventário lista as superfícies conhecidas nesta fase (S01); cada sprint que
implementa a superfície correspondente deve atualizar a coluna "Estado".

| Superfície | Rota/mecanismo | Quem pode acessar | Isolamento/negação padrão | Estado |
| --- | --- | --- | --- | --- |
| Admin Django técnico | `/admin/` (`core/urls.py`, `base.admin.TechnicalAdminSite`) | Apenas `is_staff` + `is_superuser` + MFA verificada (não o dono da clínica) | `TechnicalAdminSite.has_permission` nega sem os três requisitos; usuário comum recebe redirect/403; nenhuma delegação de painel global à clínica | Implementado e homologado em S02 (`docs/homologation/M0.md`) |
| dj-celery-panel / dj-control-room | URLs registradas sob `/admin/dj-control-room-base/`, `/admin/dj-celery-panel/`, `/admin/dj-control-room/` | Administração técnica apenas (`REQUIRE_SUPERUSER=True` por pacote + `TechnicalPanelMFAMiddleware` exigindo MFA) | 404 sem `is_superuser`+MFA; mascaramento de payloads de tarefas sensíveis fica para quando existirem tarefas reais (S07+) | Acesso protegido em S02; mascaramento de payload pendente (nenhuma tarefa sensível existe ainda) |
| Documentação técnica (MkDocs) | `/technical-docs/` via `ops/docs.py` (`technical_docs` view), registrada em `core/urls.py` | Apenas superuser técnico com MFA verificado (`user.is_verified()`) | 404 para qualquer usuário sem os três requisitos (`is_staff`, `is_superuser`, MFA); nunca cache público (Cloudflare deve ignorar) | Implementado e homologado em S02 |
| `/health/` (liveness) | `HealthMiddleware` intercepta antes do middleware de tenant | Público, sem autenticação | Não retorna dados de banco/broker; não prova saúde assistencial isolado | Implementado (`ops/http_health.py`) |
| Estáticos públicos | `/static/<RELEASE_ID>/...` via `ReleaseStaticMiddleware` | Público | Apenas arquivos da release publicada (`.ready` marker); sem listagem de diretório; `staticfiles.json` bloqueado explicitamente | Implementado (`ops/staticfiles.py`) |
| Anexos e mídia clínica/administrativa | Download autenticado por objeto (RF-05.03) | Usuário com vínculo ativo + escopo (C ou A) sobre o paciente/documento | Sem rota pública de media (`MEDIA_URL = '/private-media-unrouted/'`, nunca servida diretamente); classes distintas para anexo administrativo x clínico; auditoria inclusive em negação | Modelagem e views são S06/S07 |
| Documentos emitidos (entrega ao paciente) | Link opaco + verificação por código (RF-09.02) | Contato autorizado do paciente, com código de 8 dígitos, validade 10 min, até 5 tentativas | Token com expiração/revogação; sem enumeração; sem diagnóstico/medicamento/CPF na mensagem | S08/S09 |
| Exportações (CSV/PDF) | Síncronas até 1.000 linhas/5s; acima disso, fila (RF-10.02) | Usuário autorizado no escopo do relatório (G/A conforme papel) | Arquivo privado, expiração 24h; sanitização de fórmula CSV; supressão de células pequenas em visão gerencial | S13 |
| Cache (Redis DB 1) | `CACHES['default']` | Somente processos internos (app/worker) | TTL até 15 min (RNF-01.10); rede `neurodoc_v1_internal`, sem porta publicada; não é fonte de verdade clínica (DEC-18) | Implementado em `core/settings.py` |
| Result backend (Redis DB 0) | `CELERY_RESULT_BACKEND` | Somente workers/app internos | TTL até 24h; mesma rede interna | Implementado |
| Eventos transitórios (Redis DB 2) | `AI_EVENTS_REDIS_URL` | Somente processos internos que emitem/consomem SSE de IA | TTL até 1h (RNF-01.10); nunca fonte de verdade clínica | Configurado; consumo real é S11 |
| SSE (streaming de chat/IA) | RF-11.04 | Usuário autenticado com escopo C sobre o paciente selecionado | Eventos sequenciais com escopo e expiração; revogar acesso encerra novas entregas de streaming | S11 |
| Jobs assíncronos (Celery) | Filas `communications`, `ai`, `documents`, `maintenance`, `recovery` | Processos internos (worker); usuário nunca acessa fila diretamente | `CELERY_TASK_ROUTES` fixo por domínio; fila `recovery` isolada, usada apenas com `NEURODOC_RECOVERY_MODE=True` | Roteamento definido em `core/settings.py`; tasks reais por app são das sprints seguintes |
| Secrets (Docker Secrets / arquivos) | `ops/env.py:secret()` | Somente o processo do serviço que declara o secret no `env_file`/`_FILE` | Nunca em texto no `compose.yml`/`docker-stack.yml`; erro de secret ausente nunca expõe o valor | Implementado |
| Chave de assinatura (tmpfs) | `/run/neurodoc-signing` | Apenas réplicas `app`, UID/GID 10001, modo 0700 | Não é Docker Secret (varia por autorização médica); não entra em backup; nunca persiste fora do tmpfs | Volume declarado em `compose.yml`/`docker-stack.yml`; fluxo de autorização é S07 |
| Área `/app/` (tenant-scoped) | `tenancy.middleware.TenantMiddleware` | Usuário autenticado, e-mail confirmado, com Membership `active` no tenant da sessão e hostname compatível | 404 sem contexto válido (sem vazar existência do tenant); contexto reconstruído a cada requisição, nunca cacheado na sessão — revogação tem efeito imediato | Implementado e homologado em S02 (`tenancy/context.py`, `middleware.py`) |
| Trilha de auditoria (`AuditEvent`) | `audit/models.py`, `audit/services.py:record_audit_event` | Escrita: qualquer código do domínio via a API explícita; leitura: apenas admin técnico (read-only) | Append-only (sem `add`/`change`/`delete` no admin); nunca recebe texto clínico, senha ou token; IP mascarado (`protect_ip`) | Implementado e homologado em S02 |
| MFA / sessão de verificação recente | `accounts/mfa.py`, `django_otp` | Usuário dono do dispositivo TOTP; `require_recent_mfa` para operações privilegiadas | Recovery code de uso único; verificação expira após 30 min para ações privilegiadas | Implementado e homologado em S02 |

## Referências cruzadas

- RT-02 (tenancy em toda via de acesso) e RT-03 (privacidade/integridade) são
  os requisitos técnicos que este inventário rastreia.
- A matriz completa de permissões por papel (`owner`, `doctor`, `secretary`,
  `manager`, admin geral) está na seção 4 do PRD e será implementada a partir
  de S02.
- Este inventário deve ser revisado a cada sprint que adiciona uma superfície
  nova (novo endpoint, novo canal de entrega, novo job) — não é um documento
  estático de S01.
