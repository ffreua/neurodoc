# Deploy — primeira publicação e rollout

P-02 (VPS real) segue **pendente**: nenhuma publicação em origem real, nenhum
certificado wildcard e nenhum deploy Swarm foram executados nesta etapa. Este
documento descreve o mecanismo já implementado (`ops/deploy.py`,
`ops/runtime.py`, `ops/staticfiles.py`, `docker-stack.yml`) e o que foi
efetivamente verificado sem uma VPS.

## Preflight (`ops.deploy.preflight`)

Antes de qualquer `docker stack deploy`, `preflight()` recusa, nesta ordem:

1. `DEBUG` diferente de `False`.
2. Release não homologada (`NEURODOC_RELEASE_APPROVED != 'True'`).
3. Mudança de schema destrutiva sem procedimento de manutenção
   (`NEURODOC_SCHEMA_CHANGE != 'expand'`).
4. `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` sem as entradas obrigatórias do
   domínio de produção.
5. Menos de duas réplicas de `app` (rollout `start-first` exige duas
   réplicas coexistindo).
6. E-mail de conta ACME não configurado.
7. Nó Swarm inativo, mais de um nó, ou rótulo `neurodoc_data` ausente.
8. Redes `traefik_public`/`neurodoc_v1_internal`/`neurodoc_v1_egress` fora do
   isolamento esperado (`inspect_network`).
9. Qualquer secret listado em `docker-stack.yml` ausente no Swarm.
10. `/run/neurodoc-signing` fora de `tmpfs`.
11. Arquivos-âncora do repositório ausentes (release incompleta) ou
    repositório com mudanças rastreadas não commitadas.

**Verificado nesta etapa** (sem Swarm/VPS): a leitura do código confirma que
cada condição acima é checada explicitamente antes de qualquer chamada
destrutiva; os itens 1–6 e 11 são puro Python sobre configuração/arquivos e
não dependem de infraestrutura real. Os itens 7–10 dependem de um cluster
Swarm real (mesmo que de nó único) e **não foram exercitados** nesta
execução — ficam bloqueados por P-02.

## Conferir antes de publicar (`scripts/deploy.sh --check`)

`--check` roda o preflight inteiro e **para ali**: sem `git pull`, sem build,
sem push e sem `docker stack deploy`. Existe porque, sem ele, a única forma de
descobrir que falta um secret, o rótulo `neurodoc_data` no nó, uma entrada em
`ALLOWED_HOSTS` ou o `tmpfs` de `/run/neurodoc-signing` era começar uma
publicação de verdade — que já teria construído e empurrado uma imagem antes
de a primeira dessas condições ser lida.

```bash
cd /srv/neurodoc
scripts/deploy.sh --check
```

Saída esperada: `Preflight aprovado: ...`. Qualquer outra coisa é a primeira
condição que falhou, na ordem da lista acima — o preflight recusa na primeira
e não continua, então corrigir e repetir é o ciclo normal no provisionamento.

Rodá-lo na máquina de desenvolvimento falha logo no primeiro item (`DEBUG=False`),
o que é o esperado: o preflight descreve a produção, não o ambiente local.

## Registro da release (`docs/releases/`)

`NEURODOC_RELEASE_APPROVED=True` é uma trava declarativa: o preflight só
verifica que alguém a ligou. O que responde "esta versão foi homologada por
quem, com base em quê?" é `docs/releases/<SHA>.md`, criado a partir de
`docs/releases/TEMPLATE.md` e **commitado antes** de ligar a flag — o
preflight recusa repositório com mudança rastreada não commitada, então o
registro entra na mesma árvore que vai ao ar.

## Publicação e HTTPS

O roteador Traefik (`docker-stack.yml`) usa `Host` + `HostRegexp` para o
domínio principal e o wildcard `*.neurodoc.app.br`, com `certresolver:
cloudflare` (desafio DNS-01, sem expor porta interna alguma além de
`traefik_public`). Isso exige uma zona DNS real na Cloudflare e um token de
API — nenhum dos dois está disponível nesta execução (P-02).

## Rollout simultâneo (duas releases)

`ops/staticfiles.py::public_asset` serve cada asset sob
`/static/<release-sha>/...`; cada release grava seus arquivos em um
diretório próprio (`/data/staticfiles/public/static/<release>/`) marcado
pronto por um arquivo `.ready` (`ops/runtime.py::prepare_staticfiles`).
Como o caminho é endereçado pelo SHA da release, duas releases nunca colidem
no mesmo diretório — a condição de aceite ("duas releases coexistem sem
limpeza do diretório servido") é satisfeita pelo desenho do endereçamento,
não por uma limpeza coordenada. A limpeza de releases antigas (quando
existir) só pode atuar sobre diretórios diferentes do release atual e do
anterior em rollout, nunca sobre o que está sendo servido.

## Decisões de escopo

- Sem uma VPS, um domínio real e credenciais Cloudflare, os itens 7–10 do
  preflight, a emissão de certificado e o rollout real com duas réplicas
  ativas em produção não puderam ser exercitados. O código foi revisado
  linha a linha e é logicamente consistente com o exigido; a execução real
  fica registrada como pendência explícita (P-02), não como aceite.
- O mecanismo de assets versionados por release foi verificado por leitura
  de código (endereçamento por SHA, marcador `.ready`); um drill real com
  duas réplicas publicando simultaneamente fica para quando o ambiente Swarm
  estiver disponível.
