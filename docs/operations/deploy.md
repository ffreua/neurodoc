# Deploy — o mecanismo

> **Procurando o que fazer?** A porta de entrada é o `DEPLOY.md` na raiz
> do repositório: como a produção está montada, como se publica hoje e
> onde está cada assunto. O dia a dia está em
> [`manutencao.md`](manutencao.md); montar um servidor do zero, em
> [`primeiro-deploy.md`](primeiro-deploy.md). Este documento descreve o
> **mecanismo** — o que `ops/deploy.py` confere e faz, e por quê.

Revisto em 2026-10-22 contra `ops/deploy.py`, `ops/make_runtime.py`,
`ops/runtime.py` e `docker-stack.yml`. Até esta revisão ele dizia que a
VPS (P-02) estava pendente e que nada daquilo tinha sido exercitado; a
produção está no ar desde 2026-09-25, e cada publicação desde então passou
pelo que está descrito aqui.

## Preflight (`ops.deploy.preflight`)

Roda antes de qualquer coisa que construa ou publique. Recusa na primeira
condição que falha, nesta ordem:

1. `REGISTRY` mal formado — tem de ser `host/namespace/repositorio`, sem
   tag; a tag é o SHA, posta pelo próprio deploy.
2. `DEBUG` diferente de `False`.
3. `NEURODOC_RELEASE_APPROVED` diferente de `True`.
4. `NEURODOC_SCHEMA_CHANGE` diferente de `expand`.
5. `ALLOWED_HOSTS` sem `neurodoc.app.br`, `.neurodoc.app.br`, `localhost`
   e `127.0.0.1`.
6. `CSRF_TRUSTED_ORIGINS` sem `https://neurodoc.app.br` e
   `https://*.neurodoc.app.br`.
7. `PUBLIC_BASE_URL` diferente de `https://neurodoc.app.br`.
8. `APP_REPLICAS` menor que 2 — o rollout `start-first` precisa de duas
   réplicas coexistindo.
9. `ACME_EMAIL` igual a `CHANGE_ME` ou sem `@`.
10. `TRUSTED_PROXIES` **declarada e vazia** no `.env`. Vazia não é "use o
    padrão": é "não confie em proxy nenhum", e atrás do Traefik todo
    visitante passaria a ter o IP dele.
11. O nó não é manager ativo do Swarm.
12. Mais de um nó, ou `NEURODOC_NODES` diferente de `1`.
13. O nó sem o rótulo `neurodoc_data=true`.
14. Redes fora do isolamento esperado: `traefik_public` e
    `neurodoc_v1_egress` **não** internas, `neurodoc_v1_internal` interna —
    todas overlay de escopo Swarm.
15. Algum segredo de `docker-stack.yml` ausente no Swarm (são quinze).
16. `/run/neurodoc-signing` fora de `tmpfs`, **ou** com dono diferente do
    UID 10001 — o usuário da aplicação dentro da imagem. Montado com o dono
    padrão, a pasta fica de `root` e a primeira assinatura falharia em
    produção, com paciente na sala.
17. Arquivos-âncora do repositório ausentes, `requirements.txt` sem
    `--hash=`, ou mudança **rastreada** não commitada (arquivo novo não
    rastreado não conta).

Antes do preflight, `configuration()` já recusou qualquer chave do `.env`
que não exista no `.env.example`.

## Conferir antes de publicar (`scripts/deploy.sh --check`)

`--check` roda o preflight inteiro e **para ali**: sem `git pull`, sem
build, sem push e sem `docker stack deploy`. Existe porque, sem ele, a única
forma de descobrir que falta um segredo, o rótulo do nó ou o `tmpfs` era
começar uma publicação de verdade — que já teria construído e empurrado uma
imagem antes de a primeira dessas condições ser lida.

Rodá-lo na máquina de desenvolvimento falha logo no início, o que é o
esperado: o preflight descreve a produção, não o ambiente local.

`scripts/deploy.sh` envolve tudo, inclusive o `--check`, em
`flock -n .runtime/operation.lock` e usa o Python de `.venv-ops` (o do
sistema não tem PyYAML). `-n` quer dizer "se a trava estiver tomada, saia"
— e sai com código 1, **sem mensagem**. A mesma trava é a do backup
(`scripts/backup.sh`, que espera até 45 minutos por ela em vez de
desistir), então um deploy disparado perto das 03:00 pode sair calado.

## Depois do preflight, na ordem

1. **`git pull --ff-only`** e o processo se reexecuta com o código novo
   (`--synced`, uso interno). Por isso commit feito na VPS quebra a
   publicação seguinte: o histórico local deixa de avançar só por
   *fast-forward*.
2. **`prepare_runtime`** escreve `.runtime/app.env`, `worker.env` e
   `beat.env`: a configuração comum, as chaves opcionais presentes e, para
   cada papel, só os segredos dele (`<NOME>_FILE=/run/secrets/...`). O
   `app` recebe a senha do dono do banco e as chaves-mestras; o worker, as
   credenciais de SMTP, SMS e IA; ninguém recebe o que não usa.
3. **Imagens de infraestrutura** (`POSTGRES_IMAGE`, `RABBITMQ_IMAGE`,
   `REDIS_IMAGE`, `TRAEFIK_IMAGE`) resolvidas por digest e comparadas com as
   da última publicação bem-sucedida. Diferente, recusa: `Infrastructure
   image changed: use a planned maintenance upgrade`. Tag é alvo móvel — o
   Docker Hub republicou a do Postgres em 2026-10-06 —, e trocar a imagem
   do banco não pode ser efeito colateral de publicar aplicação.
   `PYTHON_IMAGE` fica fora dessa trava: é a base do build.
4. **Imagem da aplicação**: `REGISTRY:<SHA de HEAD>`. Se a tag já existe no
   registry, não reconstrói; senão `docker build --pull` e `docker push`
   — na VPS. Com `--skip-build`, usa a imagem de `last-successful.json`
   (ver [`rollback.md`](rollback.md): isso **não** é voltar versão). O
   `git pull` do passo 1 acontece mesmo assim, e o `docker-stack.yml` e o
   `.env` usados são os do disco: com commit novo no `origin`, um
   `--skip-build` sobe a imagem antiga com a definição de stack nova.
   Publique a versão nova antes de trocar um segredo.
5. Confere que o rótulo `org.opencontainers.image.revision` da imagem é o
   SHA, e prepara os volumes com o dono certo (UID 10001).
6. Busca as faixas da Cloudflare (`ips-v4`, `ips-v6`), com um
   `User-Agent` próprio — a Cloudflare devolve 403 ao do `urllib` — e
   escreve `.runtime/traefik.yml` com elas em `forwardedHeaders.trustedIPs`.
   Lista com menos de dez faixas é recusada.
7. Cria os `docker config` (init do Postgres, entrypoint da
   infraestrutura, `traefik.yml`), nomeados pelo hash do conteúdo.
8. `docker stack config` para conferir que nenhuma variável ficou sem
   valor, e então `docker stack deploy --with-registry-auth
   --resolve-image always`.
9. **Espera** (até `DEPLOY_TIMEOUT_SECONDS`, 1.200 s no molde): cada um dos
   sete serviços com a atualização concluída, o número de contêineres
   pedido e todos `healthy`; depois `ops/probe_ready.py` dentro de cada
   `app` (banco, nenhuma migration pendente, estáticos marcados prontos).
   Atualização em `paused` ou em qualquer estado de rollback encerra com
   `Deployment failed or rolled back: <serviço>`.
10. Fora do diretório de teste do ACME, pede `PUBLIC_BASE_URL/health/` pelo
    caminho público e exige 200.
11. Grava `.runtime/last-successful.json` (imagens por digest, `RELEASE_ID`,
    `PRODUCT_VERSION`) e guarda o anterior em `previous-successful.json`.
    Só aqui: publicação que falhou não vira "última boa".

## Migrações

Só o `app` migra (`RUN_MIGRATIONS=True` apenas no papel `app`), na
subida: `bootstrap_release` → `ops/runtime.py::prepare_release`, pela
conexão `migrations` (usuário `neurodoc_owner`), dentro de
`pg_try_advisory_lock`. Com duas réplicas subindo juntas, uma migra e a
outra espera a trava. Em seguida coleta os estáticos da release e garante o
CID-10. Worker e beat esperam o esquema ficar sem migration pendente antes
de começar (`wait_for_dependencies`).

## Publicação e HTTPS

O roteador do Traefik (`docker-stack.yml`) atende `neurodoc.app.br` e o
curinga `*.neurodoc.app.br` com `certresolver: cloudflare`. O resolvedor
(`ops/make_runtime.py::make_traefik`) é ACME com **desafio de DNS** pelo
provedor `cloudflare`: o Traefik cria um registro temporário na zona usando
o segredo `CLOUDFLARE_DNS_API_TOKEN`. Por isso o certificado curinga é
possível e a porta 80 não participa da emissão.

`ACME_DIRECTORY` escolhe o ambiente de teste ou o de produção do Let's
Encrypt, e cada um guarda o certificado em arquivo próprio
(`acme-staging.json`, `acme.json`) no volume `letsencrypt` — que entra no
backup.

Desde 2026-10-19 a Cloudflare está na frente com proxy, em *Full
(strict)*: ela exige da origem um certificado válido, e é o do Let's
Encrypt acima. As portas 80 e 443 da VPS só aceitam conexão vinda das
faixas da Cloudflare (`ops/cloudflare_firewall.sh` e o timer
`neurodoc-cloudflare-fw.timer`, instalados à mão — ver
[`manutencao.md`](manutencao.md)).

## Como cada serviço é trocado

| Serviço | Ordem | Se falhar |
| --- | --- | --- |
| `app` (2 réplicas) | `start-first`, uma de cada vez, 120 s entre elas, observada por 180 s | volta sozinho (`failure_action: rollback`) |
| `celery_worker`, `celery_beat` | `stop-first` | volta sozinho |
| `traefik` | `stop-first` | volta sozinho |
| `db`, `rabbitmq`, `redis` | `stop-first` | **pausa** — banco e filas não voltam sozinhos |

Cada serviço segue a própria regra: o Swarm não troca os três serviços da
aplicação como um bloco. Ver [`rollback.md`](rollback.md).

## Estáticos por release

`ops/staticfiles.py::public_asset` serve cada arquivo sob
`/static/<SHA>/...`; cada release coleta para um diretório próprio
(`/data/staticfiles/public/static/<SHA>/`) marcado pronto por `.ready`
(`ops/runtime.py::prepare_staticfiles`). Como o caminho é o SHA, a réplica
velha e a nova servem cada uma o seu durante o rollout, sem limpeza
coordenada.

Não existe limpeza de releases antigas: o volume `staticfiles` ganha um
diretório por publicação. Quando ela existir, só poderá tocar diretórios
diferentes do release atual e do anterior.
