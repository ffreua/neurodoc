# Capacidade: quantas clínicas a VPS aguenta, e como ajustar

Escrito em 2026-11-03, quando os processos do `app` e as tarefas do worker
deixaram de ser números fixos no código e passaram ao `.env`. Os números
abaixo são **medidos** onde diz "medido" e **estimados** onde diz
"estimado" — não houve teste de carga.

## A máquina

| Recurso | Total | Em uso (medido em 2026-11-03) |
| --- | --- | --- |
| CPU | 6 vCPU AMD EPYC | carga média ~0,5 — quase ociosa |
| Memória | 16 GiB | 3,1 GiB depois do ajuste (2,5 GiB antes) |
| Disco | 197 GiB | 29 GiB |
| Banco | — | 111 MB: 10 clínicas ativas, 2.341 pacientes, 7.728 atendimentos (quase tudo o consultório-sede, por causa do histórico do iClin) |

## O que mudou em 2026-11-03

| Serviço | Antes | Agora | Limite no `docker-stack.yml` |
| --- | --- | --- | --- |
| `app` (2 réplicas) | 2 processos cada | **4 processos cada** (`APP_WORKERS=4`) | 2 núcleos e 1,5 GiB por réplica (era 1 núcleo e 1 GiB) |
| `celery_worker` | 2 tarefas por vez | **6 tarefas por vez** (`WORKER_CONCURRENCY=6`) | 2 núcleos (era 1,5), 3 GiB |
| `db` | 1 núcleo, 2 GiB | **sem mudança** | — |

Medido em produção depois do deploy: `uvicorn --workers 4` nas duas
réplicas, sete processos do Celery no worker (o principal e seis filhos),
~470 MiB por réplica do `app` e ~680 MiB no worker.

**Por que o limite de CPU subiu junto.** Cada processo do `app` atende uma
requisição por vez (a view é síncrona e roda numa thread). Quatro processos
presos a um núcleo dividiriam o mesmo núcleo e não atenderiam mais gente —
mais processos só rendem com CPU para eles.

**Por que o worker é o ganho mais claro.** Quase todo o tempo de uma tarefa
de IA, e-mail ou SMS é espera pela resposta de fora. Seis tarefas
simultâneas quase não gastam CPU a mais e acabam com a fila quando várias
clínicas usam a IA ao mesmo tempo.

**Por que o banco ficou em 1 núcleo.** O `db` é atualizado `stop-first`:
mudar o limite dele reinicia o PostgreSQL, com o sistema fora do ar
durante a troca. Ele usava ~1–7% de CPU. Quando precisar, a mudança é para
fazer fora do horário de atendimento.

## Quantas clínicas (estimado)

O que limita não é o número de clínicas cadastradas, e sim quantas pessoas
clicam **ao mesmo tempo** — uma clínica pequena tem 1 a 3 pessoas ativas no
pico.

- Antes do ajuste: 4 requisições simultâneas → **100 a 150 clínicas** do
  porte das atuais (1 a 3 médicos).
- Depois: 8 requisições simultâneas e 6 tarefas → **em torno de 300**.

**O que aperta primeiro, nesta ordem:** a fila do worker (IA é a tarefa
mais longa), os processos do `app`, a memória do banco quando houver bem
mais dados, e o tempo de backup e restauração, que cresce com o banco.

**O limite que não é de capacidade:** é um servidor só. Se ele cair, todas
as clínicas param juntas, tenha 10 ou 300. Acima de umas 50 clínicas
pagantes, vale pensar num segundo servidor ou num banco gerenciado — pela
disponibilidade, não pelo desempenho.

## Como ajustar

As duas chaves moram no `.env` da VPS (`/srv/neurodoc/.env`):

```bash
APP_WORKERS=4          # processos por réplica do app, 1 a 16; vazio = 2
WORKER_CONCURRENCY=6   # tarefas simultâneas do worker, 1 a 32; vazio = 2
```

Mudou, publique (`bash scripts/deploy.sh`): não precisa mexer no código.
`ops/entrypoint.sh` confere os dois antes de subir e **recusa** valor fora
da faixa, vazio com espaço, letra ou sinal — o contêiner não sobe com
número inválido, em vez de subir com um padrão silencioso. Para voltar ao
padrão, apague as duas linhas; a cópia de antes do ajuste está em
`/srv/neurodoc/.env.antes-processos-2026-11-03`.

**Subir os números exige subir o limite junto.** Mais processos no `app`
sem mais núcleo no `docker-stack.yml` não ganha nada; conte ~120 MiB por
processo do `app` e ~110 MiB por tarefa do worker antes de passar do limite
de memória. `check_processos.py` confere que os limites do stack cabem os
processos e que o `entrypoint.sh` recusa os valores inválidos.

## Como conferir

```bash
docker service ls                                  # app 2/2, o resto 1/1
docker stats --no-stream | grep -E 'app|worker|db' # memória de cada um
docker exec <app> cat /proc/1/cmdline | tr '\0' ' ' # --workers N
```

Para um número medido em vez de estimado, o passo seguinte é um teste de
carga no ambiente local simulando N clínicas ao mesmo tempo.
