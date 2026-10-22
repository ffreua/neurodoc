# Saúde, logs e alertas

Revisto em 2026-10-22 contra `core/settings.py`, `ops/http_health.py`,
`ops/probe_ready.py`, `ops/celery_health.py`, `ops/queue_probe.py`,
`base/logging.py` e `ai/tasks.py`. Não há provedor externo de métricas nem
de observabilidade (Sentry, Grafana e afins): o que existe é o que está
aqui, e a rotina de olhar está em [`manutencao.md`](manutencao.md) §1 e §2.

## Sondas de saúde

Quatro, e cada uma responde a uma pergunta diferente — confundi-las é o
jeito de achar que está tudo bem quando não está.

| Sonda | Pergunta | Quem usa |
| --- | --- | --- |
| `/health/` (`ops/http_health.py::HealthMiddleware`) | o processo web responde? | o `HEALTHCHECK` do `app`, o *healthcheck* do Traefik, o fim de cada deploy (pelo domínio público) e o timer do firewall da Cloudflare |
| `ops/probe_ready.py` | o banco responde, não há migration pendente e os estáticos da release estão prontos? | o deploy, dentro de cada contêiner `app`, antes de declarar sucesso |
| `ops/celery_health.py` | o worker responde a `ping`? o beat escreveu o batimento há menos de 60 s? | o `HEALTHCHECK` do worker e o do beat |
| `ops/queue_probe.py` | a fila e o backend de resultado funcionam de ponta a ponta? | ninguém automaticamente — é para rodar à mão |

**`/health/` é só de vida.** Ele responde `ok` no próprio middleware, antes
de qualquer view, e **não toca o banco**: banco fora do ar não o derruba.
Ele confere o `Host` (`request.get_host()`), então um host fora de
`ALLOWED_HOSTS` recebe 400 em vez de `ok`. Quem pergunta pelo banco e pelo
esquema é o `probe_ready.py`.

`queue_probe.py` manda a tarefa `base.tasks.operational_ping` à fila
`maintenance` (ou `recovery`, em modo de recuperação) e espera a resposta,
que traz `ok`, o `RELEASE_ID` e a versão do produto:

```bash
docker exec $(docker ps -q -f name=neurodoc_v1_app | head -1) python /app/ops/queue_probe.py
```

Resposta boa: `Queue and result backend responded to an operational probe.`

## Logs

Tudo vai para a saída do contêiner, e se lê pelo serviço:

```bash
docker service logs neurodoc_v1_app --tail 100
docker service logs neurodoc_v1_celery_worker --tail 100
docker service logs neurodoc_v1_traefik --tail 50
```

- **Nível.** A raiz registra a partir de `WARNING`; o worker e o beat rodam
  com `--loglevel=WARNING`; o Traefik, com `log.level: WARN`. O `uvicorn`
  sobe com `--no-access-log`: não há linha por requisição.
- **Redação.** `base.logging.RedactSensitiveDataFilter` está no handler de
  console **e** no de e-mail: troca por `[REDACTED]` o valor que vier
  depois de `password`, `token`, `secret`, `otp`, `authorization`, `pfx` ou
  `code_hash`.
- **Host inválido** (`django.security.DisallowedHost`) vai só para o
  console, sem e-mail — senão cada varredura da internet viraria alerta.
- **Política de conteúdo**: as violações chegam em `/csp-report/` e saem no
  log da aplicação com o prefixo `csp:`.

Os temporizadores do host escrevem no `journal`, não no Docker:

```bash
journalctl -u neurodoc-backup.service -n 30 --no-pager
journalctl -u neurodoc-cloudflare-fw.service -n 5 --no-pager
journalctl -u neurodoc-signing-cleanup.service -n 5 --no-pager
```

## Alertas por e-mail

São dois, para destinatários diferentes.

### Erro 500 → `ALERT_ADMIN_EMAILS`

O logger `django.request` em `ERROR` — qualquer 5xx não tratado — dispara o
`AdminEmailHandler` para os endereços de `ALERT_ADMIN_EMAILS`. O Django só
manda esses e-mails com `DEBUG=False`, e o envio sai pela fila como
qualquer outro e-mail: quem fala com o SMTP é o worker.

O relatório de erro não carrega o corpo da requisição.
`base.logging.NoPostDataExceptionReporterFilter`
(`DEFAULT_EXCEPTION_REPORTER_FILTER` em `core/settings.py`) suprime todos
os parâmetros de POST: o filtro padrão do Django só esconde campo cujo
**nome** pareça sensível e não tem como saber que `chief_complaint` é
texto clínico. Um alerta precisa do traceback e do caminho, nunca do corpo.
Testado de ponta a ponta em S10, com um trecho de queixa clínica num POST
sintético que não apareceu em lugar nenhum do e-mail gerado.

### IA da instalação falhando → superadministradores (1.23)

`ai.tasks.vigiar_ia_da_instalacao`, no beat, **de hora em hora no minuto
47**: confere o provedor de IA padrão da instalação e, se configurada, a
reserva. Na passagem para a falha manda e-mail a **todo superusuário
ativo** com e-mail cadastrado — não a `ALERT_ADMIN_EMAILS` —, repete uma
vez a cada 24 horas enquanto durar, e para sozinho quando a verificação
volta a passar. O e-mail diz se a reserva está cobrindo, porque isso muda a
urgência, e aponta `/instalacao/operacao/`.

É a peça que faltou nos quarenta dias de `410 Gone` de 2026 (§7-D do
`CLAUDE.md`): a verificação existia, mas só rodava quando alguém clicava.

## O que se olha à mão

| Quando | O quê | Onde |
| --- | --- | --- |
| Toda semana | os sete serviços de pé; o backup do dia | [`manutencao.md`](manutencao.md) §1 e §2 |
| Todo mês | a cópia externa conferida | [`copia-externa.md`](copia-externa.md) |
| A cada 6 meses | restaurar de verdade | [`restore.md`](restore.md) |

## Backup que falhou (desde a 1.24.1)

`neurodoc-backup.service` tem `OnFailure=neurodoc-backup-falhou.service`:
quando o backup termina com erro, o systemd dispara
`scripts/avisar_falha_backup.sh`, que roda `manage.py avisar_falha_backup`
**no contêiner do worker** (só ele tem a credencial de e-mail) e manda aos
superadministradores ativos o aviso, com o comando para ver o motivo.
Antes disso a falha só ficava no `journal`. Sem worker no ar, o aviso não
sai — e a própria unidade do aviso falha no `journal`
(`journalctl -u neurodoc-backup-falhou.service`).

## O que ainda não existe

- **Alerta de que a cópia externa não trouxe nada novo.** A tarefa diária
  registra `0 novo(s)` no log e sai com sucesso.
- **Métricas de desempenho** (RNF-01, H-23): nenhuma medição sob carga.
