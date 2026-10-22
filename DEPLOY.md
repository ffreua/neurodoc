# Deploy do NeuroDoc — por onde começar

**Esta é a porta de entrada** de tudo que é publicação e operação. Ela diz
como a produção está montada, como se publica uma versão hoje e onde está
o detalhe de cada assunto. Revista em 2026-10-22, com a **1.24** no ar.

A primeira versão deste arquivo foi escrita na auditoria pré-deploy de
2026-09-24, antes de existir servidor; ela está no histórico do Git. O que
mudou desde então — certificado por desafio de DNS, proxy da Cloudflare,
segredos do Swarm em vez de arquivos, rollback que não é `--skip-build` —
está corrigido aqui e nos documentos abaixo.

| Para | Leia |
| --- | --- |
| Montar um servidor do zero | [`docs/operations/primeiro-deploy.md`](docs/operations/primeiro-deploy.md) (e `scripts/setup_deploy.sh`, que o executa) |
| Operar no dia a dia: publicar, conferir, trocar senha, firewall | [`docs/operations/manutencao.md`](docs/operations/manutencao.md) |
| Entender o mecanismo: preflight, rollout, estáticos | [`docs/operations/deploy.md`](docs/operations/deploy.md) |
| Voltar uma versão | [`docs/operations/rollback.md`](docs/operations/rollback.md) |
| Backup e restauração | [`docs/operations/restore.md`](docs/operations/restore.md) |
| Cópia do backup fora da VPS | [`docs/operations/copia-externa.md`](docs/operations/copia-externa.md) |
| Saber se está de pé: saúde, logs, alertas | [`docs/operations/monitoring.md`](docs/operations/monitoring.md) |
| Número de versão × SHA | [`docs/operations/versionamento.md`](docs/operations/versionamento.md) |
| Imagens e versões de componentes | [`docs/operations/environment.md`](docs/operations/environment.md) |
| O que aconteceu no primeiro deploy | [`docs/operations/diario-do-primeiro-deploy.md`](docs/operations/diario-do-primeiro-deploy.md) (histórico) |

`DEPLOY_CHECKLIST.md` e `PRE_DEPLOY_AUDIT.md` são o registro do primeiro
deploy (1.0, setembro de 2026) e **não** descrevem o procedimento de hoje.

Onde este arquivo e o código divergirem, vale o código: `ops/deploy.py`,
`docker-stack.yml`, `ops/make_runtime.py`.

---

## Como a produção está montada

| | |
| --- | --- |
| Servidor | VPS Ubuntu 24.04, **Docker Swarm de um nó só** — o preflight recusa mais de um (`NEURODOC_NODES=1`), porque os volumes são locais e não seguem uma tarefa migrada |
| Projeto | `/srv/neurodoc` (o caminho padrão das unidades do systemd) |
| Serviços | sete: `app` (2 réplicas), `celery_worker`, `celery_beat`, `db`, `rabbitmq`, `redis`, `traefik` |
| Imagem | `ghcr.io/ffreua/neurodoc:<SHA do commit>`, entregue ao stack **por digest** (`REGISTRY` no `.env`) |
| Borda | **Cloudflare com proxy** (desde 2026-10-19, SSL em *Full (strict)*) → Traefik → `app` |
| Certificado da origem | Let's Encrypt pelo Traefik, por **desafio de DNS na Cloudflare** (`dnsChallenge`, token no segredo `CLOUDFLARE_DNS_API_TOKEN`). A porta 80 não participa da emissão |
| Firewall | UFW com 22/80/443; e 80/443 **só para as faixas da Cloudflare** (`ops/cloudflare_firewall.sh`, timer `neurodoc-cloudflare-fw.timer`) |
| Segredos | **quinze segredos do Swarm** (`docker secret`), lidos de `docker-stack.yml`. `.secrets/` é só do ambiente local |
| Temporizadores | `neurodoc-backup.timer` (03:00 de Brasília), `neurodoc-signing-cleanup.timer` (a cada 5 min), `neurodoc-cloudflare-fw.timer` (na subida e uma vez por dia) |

**O `app` tem saída para a internet**, ao contrário do que alguns
documentos antigos dizem: ele está em `traefik_public`, que não é
`internal`. O que o impede de enviar e-mail, SMS ou falar com a IA é não
receber os segredos de saída (`ops/make_runtime.py` só os entrega ao
worker). Ver o §2 do `CLAUDE.md`.

## Publicar uma versão

**No computador de desenvolvimento**, com a bateria verde e a versão
fechada: a nota em `docs/releases/` (nomeada pela versão, como
`1.24-o-pedido-pronto.md`) entra no mesmo commit, **antes** do push.

```bash
git push origin main
```

**Na VPS**, como o usuário de operação:

```bash
cd /srv/neurodoc
git pull --ff-only
bash scripts/deploy.sh --check
setsid nohup bash scripts/deploy.sh > /tmp/deploy.log 2>&1 < /dev/null &
tail -f /tmp/deploy.log
```

Por que cada linha:

- **`--check` primeiro.** Roda o preflight inteiro e para — sem build,
  sem push, sem `stack deploy`. Sem ele, a única forma de descobrir que
  falta um segredo ou uma entrada de `ALLOWED_HOSTS` é começar uma
  publicação de verdade. A resposta boa é `Preflight aprovado: ...`.
- **`setsid nohup`**: a publicação leva de 10 a 25 minutos. Presa à sessão
  SSH, uma queda de conexão a mata no meio do `stack deploy`.
- **Nunca commite na VPS.** O deploy faz `git pull --ff-only`; um commit
  local diverge do `origin` e a publicação seguinte para ali.

Termina com duas linhas — a versão do produto e o SHA:

```
NeuroDoc 1.24 publicado.
Release <sha> deployed; all services are healthy.
```

### O que o deploy faz, na ordem (`ops/deploy.py`)

1. **Preflight** — a lista completa está em
   [`docs/operations/deploy.md`](docs/operations/deploy.md).
2. `git pull --ff-only` e se reexecuta com o código novo.
3. Gera os `env_file` de cada papel em `.runtime/` (cada segredo só para
   quem precisa dele).
4. Resolve as imagens de infraestrutura por digest e **recusa** se alguma
   mudou desde a última publicação (`Infrastructure image changed`): trocar
   Postgres, RabbitMQ, Redis ou Traefik é manutenção planejada, não efeito
   colateral de publicar aplicação.
5. Constrói e empurra `REGISTRY:<SHA>` — **na VPS** —, a menos que essa tag
   já exista no registry.
6. Confere que a imagem carrega o SHA certo, prepara os volumes, busca as
   faixas da Cloudflare e escreve o `traefik.yml`.
7. `docker stack deploy` e espera: cada serviço convergido e saudável,
   `ops/probe_ready.py` em cada `app` (banco, nenhuma migration pendente,
   estáticos prontos) e, por fim, `/health/` pelo domínio público.
8. Só então grava `.runtime/last-successful.json` (e guarda o anterior em
   `previous-successful.json`).

**Quem migra o banco é o `app`, na subida** (`bootstrap_release` →
`ops/runtime.py::prepare_release`), pela conexão `migrations`, sob trava do
PostgreSQL — duas réplicas subindo juntas migram uma vez só. **Nunca rode
`manage.py migrate` à mão**: a conexão padrão é `neurodoc_app`, sem DDL, e
para em `permission denied for schema public`.

### As três chaves do `.env` que o deploy cobra

| Chave | Valor | Por quê |
| --- | --- | --- |
| `NEURODOC_RELEASE_APPROVED` | `True` | Trava declarativa: o preflight só confere que alguém a ligou. Quem responde "homologado por quem, com base em quê" é a nota em `docs/releases/` |
| `NEURODOC_SCHEMA_CHANGE` | `expand` | Qualquer outro valor é recusado. Mudança que apaga ou renomeia coluna exige procedimento de manutenção |
| `TRUSTED_PROXIES` | faixas privadas **e** as da Cloudflare | Declarada vazia, é recusada. Sem as faixas da Cloudflare, o produto vê o IP do nó dela e não o do visitante, e os limites de tentativa viram um balde só |

`.env` só aceita chave que exista no `.env.example` — chave nova entra
primeiro no molde, onde aparece num diff.

## Conferir depois de publicar

```bash
docker service ls                                   # sete serviços, 2/2 no app e 1/1 nos outros
curl -s https://neurodoc.app.br/health/             # ok
curl -sI https://neurodoc.app.br/ | grep -i 'strict-transport\|x-frame\|nosniff\|referrer\|content-security'
```

E na interface: o rodapé mostra a versão nova, e `/instalacao/` mostra a
versão ao lado do build (SHA).

O teste antigo de `Host:` desconhecido devolvendo 400 **não vale mais de
fora**: com a Cloudflare na frente, quem responde a um host estranho é a
borda dela, e a origem não aceita conexão de mais ninguém.

## Voltar atrás

Resumo — o procedimento está em
[`docs/operations/rollback.md`](docs/operations/rollback.md):

- se a versão nova não fica saudável durante a publicação, o Swarm volta
  **o serviço que falhou** sozinho e o deploy termina com erro;
- para voltar de propósito, `docker service rollback` nos **três** serviços
  que usam a imagem da aplicação (`app`, `celery_worker`, `celery_beat`);
- **`deploy.sh --skip-build` não é rollback**: ele republica a imagem de
  `last-successful.json`, que é a versão que acabou de entrar.

## Backup e restauração

- **Backup diário** às 03:00 de Brasília, cifrado com `age` antes de tocar
  o disco, em `/srv/neurodoc-backups` (`scripts/backup.sh` →
  `ops/backup.py`). Banco e os volumes `media`, `signing` e `letsencrypt`.
- **Cópia fora da VPS**: um PC puxa todo dia às 09:00 e confere cada
  arquivo pelo SHA-256 do manifesto
  ([`copia-externa.md`](docs/operations/copia-externa.md)). A VPS não sabe
  que a cópia existe, de propósito.
- **Restauração** só num host separado e vazio
  ([`restore.md`](docs/operations/restore.md)). Refazer a prova depois de
  qualquer mudança em `BACKUP_AGE_RECIPIENT`.

## Quando algo dá errado

| Sintoma | Onde olhar |
| --- | --- |
| `deploy.sh` sai na hora, com código 1 e sem mensagem | Outra operação segura `.runtime/operation.lock` — outro deploy, ou **o backup das 03:00**, que usa a mesma trava. O arquivo existir não é trava: a trava é do processo, e some quando ele termina. Espere e rode de novo |
| `Infrastructure image changed` | Uma tag de infraestrutura foi republicada no registry. Fixe no `.env` o digest que **já roda** e trate a troca como manutenção (ver `docs/ESTADO-ATUAL.md`, o caso do Postgres em 2026-10-06) |
| `Unknown configuration keys` | Chave no `.env` que não existe no `.env.example` |
| `app` reinicia em laço | `docker service ps neurodoc_v1_app --no-trunc` e `docker service logs neurodoc_v1_app --tail 100` — normalmente segredo faltando ou migration |
| Erro 526 da Cloudflare | O certificado da **origem** não vale (Full strict o exige). `docker service logs neurodoc_v1_traefik --tail 50 \| grep -i acme` — quase sempre o token da Cloudflare |
| Site fora pelo domínio, tudo verde na VPS | O firewall da Cloudflare: `journalctl -u neurodoc-cloudflare-fw.service -n 5`. Ver [`manutencao.md`](docs/operations/manutencao.md) |
| 400 em toda requisição | `ALLOWED_HOSTS` |
| CSRF recusado no login | `CSRF_TRUSTED_ORIGINS` |
| E-mail não sai | `testar_email` e `docker service logs neurodoc_v1_celery_worker` — quem fala com o SMTP é o worker |
| Backup não rodou | `journalctl -u neurodoc-backup.service -n 30` |
