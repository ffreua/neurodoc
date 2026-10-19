# Baseline de ambiente, imagens e versões

Este documento registra a arquitetura e as versões selecionadas no PRD (seção
8.2 e 17.1). Foi escrito em S01, **antes** de existir VPS, e partes dele
descrevem esse momento — estão marcadas como histórico.

**Atualização de 2026-10-18.** A P-02 foi resolvida em 2026-09-25 (ver
`docs/decisions.md`): repositório `github.com/ffreua/neurodoc`, imagens em
`ghcr.io/ffreua/neurodoc`, VPS Integrator x86_64 com 6 vCPU e 15 GB, primeiro
deploy em 2026-09-25 e uso real desde 2026-10-02. Este arquivo seguiu dizendo
"pendente" por três semanas depois disso. A tabela de capacidade abaixo é a
**proposta** do PRD, e não a máquina que existe. As versões de Docker e do
Compose na VPS não foram registradas aqui; quem precisar delas deve
perguntar à própria VPS (`docker version`), não a este documento.

## Topologia e capacidade propostas

| Ambiente | vCPU | RAM | Disco | Réplicas | Observação |
| --- | --- | --- | --- | --- | --- |
| Produção (piloto) | 8 | 16 GiB | 200 GiB SSD/NVMe | app: 2 (+1 temporária no rollout) | Ubuntu 24.04 LTS amd64; sujeito a H-23, não medido |
| Demonstração local | 4 | 8 GiB | 60 GiB | 1 | Tarefas serializadas; não usar para prometer capacidade do piloto |

### Serviços permanentes (7) e limites por réplica

| Serviço | Réplicas | CPU limite/reserva | Memória limite/reserva | Rede |
| --- | --- | --- | --- | --- |
| app | 2 | 1 / 0,25 | 1 GiB / 384 MiB | traefik_public + neurodoc_v1_internal |
| celery_worker | 1 (concorrência 2) | 1,5 / 0,75 | 3 GiB / 1 GiB | interna + neurodoc_v1_egress |
| celery_beat | 1 | 0,25 / 0,1 | 256 MiB / 64 MiB | interna + egress |
| db | 1 | 1 / 0,25 | 2 GiB / 512 MiB | interna |
| rabbitmq | 1 | 0,75 / 0,25 | 1 GiB / 256 MiB | interna |
| redis | 1 | 0,5 / 0,1 | 512 MiB / 128 MiB | interna |
| traefik | 1 | 0,5 / 0,1 | 256 MiB / 64 MiB | traefik_public |

### Redes (três, pré-criadas fora do stack)

| Rede | Criação | Internal | Alcance |
| --- | --- | --- | --- |
| traefik_public | overlay externo | false | Traefik e app; apenas Traefik publica portas |
| neurodoc_v1_internal | overlay `--internal` externo | true | DB/brokers, sem saída direta nem portas no host |
| neurodoc_v1_egress | overlay externo | false | Saída de workers/beat; nenhuma porta publicada |

Todos os serviços de dados ficam no nó `neurodoc_data=true`; o script de deploy
recusa múltiplos nós (volumes locais não seguem uma task migrada).

## Matriz de versões (seção 8.2 do PRD)

| Componente | Baseline selecionada | Observação |
| --- | --- | --- |
| Ubuntu VPS | 24.04 LTS amd64 | Escolha conservadora para o guia de deploy |
| Python | 3.14.7 | Atende `>3.13` sem ambiguidade de patch |
| Django | 6.1.1 | Matriz oficial inclui Python 3.14 |
| LangChain | 1.4.0 | Atende `>1.0` |
| LangGraph | 1.2.11 | |
| Celery | 5.6.3 | Suporte inicial a Python 3.14 |
| dj-celery-panel | 0.6.0 | Metadados incluem Django 6.1/Python 3.14 |
| PostgreSQL | 17.11 | Imagem candidata `postgres:17.11-bookworm` |
| RabbitMQ | 4.3.5 | Imagem sem management público |
| Redis | 8.10.1 | Avaliar licenciamento aplicável à distribuição |
| Traefik | 3.7.12 | Provider `swarm` |
| Docker Engine | 29.8.0 (candidato do guia) | Verificar versão disponível no repositório Ubuntu e fixá-la |
| Compose plugin | Versão estável do repositório Docker | **Registrada nesta execução:** Docker Desktop local relata `Docker Engine 29.7.2`; Compose plugin `v2` (via `docker compose`). A versão instalada na VPS não foi registrada aqui (histórico de S01, antes da VPS existir) |
| WhiteNoise | 6.12.0 | Storage de manifesto e compressão apenas |
| Modelo de IA padrão | `z-ai/glm-5.3-flash` via OpenRouter | Validar recursos/provedor final por configuração |

### Ferramenta de resolução de dependências

`requirements.in` foi resolvido com **uv 0.12.10** (`uv pip compile
--generate-hashes --python-version 3.14`) dentro de um contêiner
`python:3.14.7-slim-bookworm`, gerando `requirements.txt` com hashes para os 28
pacotes diretos e suas transitivas (123 entradas no total). O cabeçalho gerado
por `uv` no topo de `requirements.txt` registra o comando exato usado; cada
regeneração do lock deve preservar esse cabeçalho. O build (`Dockerfile`)
recusa ausência de lock: `pip install --require-hashes -r requirements.txt`.

Uma primeira tentativa de resolução com `pip-compile` (`pip-tools`) no mesmo
contêiner foi abandonada por lentidão (resolução silenciosa do backtracking do
`pip` sobre a árvore pesada de `langchain`/`langgraph`); `uv` produziu o mesmo
conjunto de pacotes de topo com resolução completa em menos de um minuto.

## Imagens Docker candidatas

| Imagem | Referência |
| --- | --- |
| `python:3.14.7-slim-bookworm` | Base do `Dockerfile` da aplicação (app/worker/beat) |
| `postgres:17.11-bookworm` | Banco |
| `rabbitmq:4.3.5` | Broker |
| `redis:8.10.1` | Cache/result backend/eventos transitórios |
| `traefik:v3.7.12` | Proxy/TLS |

Em produção, cada imagem de aplicação é publicada no registry configurado
em `REGISTRY` (`.env`) — nesta instalação, `ghcr.io/ffreua/neurodoc` — com a
tag do SHA Git completo, e o stack recebe o
**digest** confirmado pelo registry — nunca a tag `latest`
(`ops/deploy.py::resolve_image` recusa referência sem tag ou com `:latest`).
Em S01 nenhuma imagem tinha sido publicada; desde 2026-09-25 é assim que cada
deploy publica.

As quatro imagens de infraestrutura (postgres, rabbitmq, redis, traefik)
continuam referenciadas por tag. O `.env` da VPS fixa o digest do Postgres
que já roda, e o deploy aborta se alguma delas mudar em relação ao último
deploy bem-sucedido. Fixar as outras três por digest é decisão aberta,
registrada em `docs/ESTADO-ATUAL.md`.

## Evidências de convergência local (S01)

O `compose.yml` local (gerado por `ops/local_compose.py` a partir de
`docker-stack.yml`) foi efetivamente construído e executado nesta sprint via
Docker Desktop (Docker Engine 29.7.2), com canais externos desabilitados
(`EMAIL_ENABLED=False`, `SMS_ENABLED=False`, `AI_ENABLED=False`). Resultado:
os sete serviços (`app`, `celery_worker`, `celery_beat`, `db`, `rabbitmq`,
`redis`, `traefik`) convergiram para `healthy`; `python manage.py check` sem
problemas; `/health/` respondeu 200 tanto diretamente quanto através do
Traefik; `/admin/login/` respondeu 200.

Essa execução expôs três incompatibilidades reais entre os artefatos originais
e a combinação de versões da matriz (seção 8.2), corrigidas nesta sprint:

1. **RabbitMQ 4.3.5 rejeita filas transitórias não exclusivas.** O Kombu/AMQP
   usado pelo Celery 5.6.3 declara essas filas para o mecanismo de *pidbox*
   (`inspect ping`, usado pelo healthcheck do worker). RabbitMQ 4.x desativa
   esse recurso por padrão (`transient_nonexcl_queues`). Corrigido em
   `ops/infra_entrypoint.sh`, que agora grava
   `/etc/rabbitmq/conf.d/99-neurodoc.conf` permitindo explicitamente
   `deprecated_features.permit.transient_nonexcl_queues` e
   `deprecated_features.permit.global_qos` (a segunda também exigida pelo
   mesmo mecanismo) antes de iniciar o `rabbitmq-server`.
2. **Permissão do arquivo de configuração do RabbitMQ.** O `umask 077` do
   início do script deixava o arquivo gerado ilegível para o usuário
   `rabbitmq` (que roda com privilégios reduzidos). Corrigido com
   `chmod 0644` explícito após a geração do arquivo.
3. **`ops/celery_health.py` não localizava o pacote `core`.** Executado como
   script direto (`python /app/ops/celery_health.py worker`, forma usada no
   `HEALTHCHECK`/`docker-stack.yml`), `sys.path[0]` aponta para `/app/ops`, não
   para `/app` — diferente de `manage.py`, `celery -A core` e `uvicorn`, que
   resolvem o cwd/diretório do projeto por conta própria. Corrigido inserindo
   `/app` em `sys.path` no topo do script; a mesma correção foi aplicada por
   consistência em `ops/probe_ready.py` e `ops/queue_probe.py`, que têm o
   mesmo padrão de invocação e o mesmo risco.
4. **Volumes de dados `staticfiles`/`media`/`signing`/`beat`/`clamav` sem
   diretório pré-existente no volume Docker local.** Um volume nomeado vazio
   herda ownership `root` na primeira montagem, mas os processos rodam como
   UID 10001. Corrigido criando esses diretórios com o `chown` correto no
   próprio `Dockerfile`, antes do `USER 10001:10001`, para que a
   auto-população do volume a partir da imagem preserve a permissão.

Nenhuma dessas correções altera o comportamento documentado no PRD; todas
mantêm as decisões de arquitetura (DEC-12, DEC-19, seção 17) e apenas resolvem
incompatibilidades de versão que só são visíveis executando a composição real
— exatamente o que a seção 8.2 do PRD já avisava não ter sido verificado
("confirma disponibilidade/documentação, não equivale à execução da stack
conjunta").

## Pendências explícitas desta seção

- ~~P-02: URL Git, permissão GHCR, IP/arquitetura e acesso da VPS~~ —
  resolvida em 2026-09-25.
- Digests de produção: o da aplicação é resolvido a cada deploy; os de
  infraestrutura seguem por tag, exceto o do Postgres (ver acima).
- Este documento não substitui H-21/H-22 (homologação de deploy e backup),
  que exigem execução real na VPS.
