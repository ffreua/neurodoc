# Deploy do NeuroDoc

Roteiro operacional resumido, produzido na auditoria pré-deploy de
2026-09-24 com os comandos **reais** do projeto.

> **O passo a passo completo do primeiro deploy é
> [`docs/operations/primeiro-deploy.md`](docs/operations/primeiro-deploy.md)**
> — 1.000 linhas, com as telas e as armadilhas de cada etapa. Este arquivo é
> o mapa; aquele é o território. Onde os dois divergirem, **vale aquele**, e
> este está errado.
>
> Complementos: [`deploy.md`](docs/operations/deploy.md) (mecanismo),
> [`rollback.md`](docs/operations/rollback.md),
> [`restore.md`](docs/operations/restore.md),
> [`monitoring.md`](docs/operations/monitoring.md),
> [`environment.md`](docs/operations/environment.md).

---

## Pré-requisitos

| | |
| --- | --- |
| VPS | Debian/Ubuntu recente, com `age` disponível nos repositórios |
| Porte | 4 vCPU / 8 GB / 80 GB SSD atende com folga os sete serviços |
| Rede | 80 e 443 abertas; 22 restrita |
| DNS | `neurodoc.app.br` apontando para a VPS **antes** do deploy (Let's Encrypt valida por HTTP) |
| Registro | Acesso de escrita ao registry de imagens (`REGISTRY`) |
| Local | Docker, `git`, Python 3 na máquina que publica |

## Configuração do servidor

```bash
# Na VPS, como root. Idempotente: retoma de onde parou.
./scripts/setup_deploy.sh
```

Ele instala Docker, ativa o Swarm, instala `fail2ban`, ajusta o fuso e
instala os utilitários — **incluindo `age`**, sem o qual a cópia de segurança
não roda. Se `age` não existir na distribuição, o roteiro **para** e aponta o
release oficial: seguir sem ele é escrever um timer de backup que nunca vai
funcionar.

## Variáveis de ambiente

```bash
cp .env.example .env    # 42 variáveis; nenhuma delas é segredo
```

Obrigatórias de conferir:

| Variável | Valor |
| --- | --- |
| `DEBUG` | `False` (o preflight recusa `True`) |
| `PUBLIC_BASE_URL` | `https://neurodoc.app.br` (o preflight recusa outro) |
| `ALLOWED_HOSTS` | domínio real, com e sem `www` |
| `CSRF_TRUSTED_ORIGINS` | `https://` + domínio |
| `ACME_EMAIL` | e-mail real (o preflight recusa `CHANGE_ME`) |
| `ALERT_ADMIN_EMAILS` | quem recebe alerta de erro |
| `SECURE_HSTS_SECONDS` | **`0` neste primeiro deploy** |
| `TRUSTED_PROXIES` | **acrescente as faixas da Cloudflare se ela estiver na frente** |
| `REGISTRY` | `host/namespace/repositorio` |
| `NEURODOC_SCHEMA_CHANGE` | `expand` |

**Segredos** — nunca no `.env`. Um arquivo por segredo em `.secrets/`, modo
0600, sem quebra de linha final:

```
DJANGO_SECRET_KEY  DB_APP_PASSWORD  DB_OWNER_PASSWORD
RABBITMQ_PASSWORD  REDIS_PASSWORD   SECRETS_MASTER_KEY
PFX_MASTER_KEY     SMTP_PASSWORD    SMSDEV_API_KEY
```

`ops/make_runtime.py` distribui cada segredo só ao serviço que precisa dele —
o `app` não recebe as credenciais de saída, o `worker` não recebe a chave do
dono do banco.

## Banco

```bash
# Uma vez, antes do primeiro deploy: papéis, privilégios e extensão.
./ops/postgres_init.sh
```

Cria `neurodoc_owner` (cria esquema) e `neurodoc_app` (só lê e grava dado),
revoga `CREATE` do `PUBLIC` e instala `btree_gist`. As 86 migrations rodam no
start do serviço `app`, que é o único com `RUN_MIGRATIONS=True`.

## Publicação

```bash
# 1. Confere sem publicar nada — preflight completo.
.venv-ops/bin/python -m ops.deploy --check

# 2. Publica: constrói, empurra por digest, atualiza o stack, espera saúde.
.venv-ops/bin/python -m ops.deploy
#    ou, com a trava de execução única:
./scripts/deploy.sh
```

O preflight recusa `DEBUG=True`, `ACME_EMAIL` inválido, `PUBLIC_BASE_URL`
errado, `REGISTRY` mal formado e release não aprovada. `scripts/deploy.sh`
envolve tudo num `flock` — dois deploys simultâneos não se atropelam.

**Antes de `NEURODOC_RELEASE_APPROVED=True`:** copie
`docs/releases/1.0-PRIMEIRO-DEPLOY.md` para `docs/releases/<SHA>.md` e
preencha os campos entre `<>`.

## Primeiro acesso

```bash
docker exec -it <container-app> python manage.py create_superadmin seu@email.com
```

**Configure a MFA antes de qualquer outra coisa** — `/admin/` e `/instalacao/`
exigem `is_superuser` **e** MFA verificada, e sem ela você não entra.

Depois: emita o convite de plataforma da clínica-sede, faça a adesão pelo
cadastro (o aceite do contrato grava SHA-256 e manda a via por e-mail) e
preencha o **encarregado de dados** em Identidade da clínica — enquanto
estiver vazio, o portal do paciente diz que a clínica não designou ninguém.

## Workers e tarefas agendadas

Os três processos sobem pelo stack. O `celery_beat` carrega seis tarefas:

| Tarefa | Quando |
| --- | --- |
| `events.tasks.dispatch_outbox` | a cada minuto |
| `communications.tasks.reconcile_pending_sms` | periódica |
| `reporting.tasks.expire_exports` | periódica |
| `documents.tasks.update_clamav_definitions` | periódica |
| `catalogs.tasks.sync_tuss` | domingo, 4h |
| `documents.tasks.compact_archive` | trimestral, dia 1, 3h |

> **Aberto:** `documents/retention.py::garbage_collect` **não** está agendado.
> Ver `PRE_DEPLOY_AUDIT.md` §9 (D-02) — é decisão sua.

## E-mail

```bash
docker exec -it <container-worker> python manage.py testar_email seu@email.com
```

O envio sai **sempre pelo worker**: só a ele o segredo de SMTP é entregue, e
só ele pode tentar de novo quando o provedor falha.

## HTTPS

Traefik pede o certificado ao Let's Encrypt na subida, validando por HTTP —
por isso o DNS precisa estar apontado **antes**. Confirme o certificado real e
o 301 de HTTP para HTTPS.

**Só então** ligue `SECURE_HSTS_SECONDS`: o navegador guarda a instrução e não
há como voltar atrás pelo servidor.

## Validação pós-deploy

```bash
curl -I http://neurodoc.app.br/                  # 301 para https
curl -s  https://neurodoc.app.br/health/          # saudável
curl -sI https://neurodoc.app.br/ | grep -i \
  'strict-transport\|x-frame\|nosniff\|referrer'
curl -sI -H 'Host: invalido.example' https://neurodoc.app.br/   # 400
```

Na interface: rodapé com **versão 1.0**, `/ajuda/` com as 47 capturas,
`/contrato/`, login com MFA, cadastro de paciente, marcação na agenda,
emissão de documento, `/instalacao/` só com MFA.

Lista completa: `DEPLOY_CHECKLIST.md` e `TEST_MATRIX.md`.

## Rollback

```bash
# Volta ao digest anterior, sem reconstruir.
.venv-ops/bin/python -m ops.deploy --skip-build
```

Detalhe em [`docs/operations/rollback.md`](docs/operations/rollback.md).
**Nesta release não há migration a reverter**: o banco nasce do zero, a
mudança é *expand* e nada é migrado.

## Backup e restauração

```bash
./scripts/backup.sh                 # cifra com age; trava compartilhada
.venv-ops/bin/python -m ops.restore # restauração
```

Duas coisas a fazer **antes** de considerar o deploy concluído:

1. **Levar o backup para fora da VPS.** `BACKUP_DIR` local resolve "apaguei
   sem querer"; não resolve "a máquina morreu". Como o arquivo é cifrado com
   `age`, o destino não precisa ser confiável.
2. **Testar a restauração num host separado.** Backup não testado é
   suposição, e a guarda de 20 anos da Lei 13.787/2018 não aceita suposição.

## Solução de problemas

| Sintoma | Onde olhar |
| --- | --- |
| `app` reinicia em laço | `docker service logs` — normalmente segredo faltando ou migration |
| 400 em toda requisição | `ALLOWED_HOSTS` sem o domínio |
| CSRF recusado no login | `CSRF_TRUSTED_ORIGINS` sem `https://` + domínio |
| Certificado não emitido | DNS ainda não propagado, ou 80 fechada |
| E-mail não sai | Rode `testar_email` **no worker**; confira `SMTP_PASSWORD` em `.secrets/` |
| Tarefa não roda | `celery_beat` de pé? `dispatch_outbox` a cada minuto? |
| Backup falha | `age` instalado? Chave de destinatário configurada? |
| Deploy travado | `.runtime/operation.lock` de uma execução anterior |
