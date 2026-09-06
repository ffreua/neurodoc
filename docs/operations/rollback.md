# Rollback de aplicação

## Estratégia: migrations expand-only

Toda migration criada até aqui (S01–S09) é aditiva: novos modelos, novos
campos opcionais/com default, novos índices/constraints que não removem
nem tornam obrigatória nenhuma coluna existente. Nenhuma migration renomeia
ou apaga uma coluna/tabela em uso. Isso é o que permite um rollback de
**aplicação** (voltar para a imagem/release anterior) sem precisar de
downgrade destrutivo de schema: o código antigo simplesmente ignora colunas
novas que não usa; nenhuma coluna que o código antigo espera foi removida.

Uma mudança que precisasse remover/renomear uma coluna seguiria o padrão
expand → migrate dados → contract em releases separadas (a fase "contract"
só acontece quando nenhuma release antiga que dependa da coluna antiga
ainda pode ser um alvo de rollback) — nenhuma sprint até agora precisou
disso.

## `skip-build`

`ops/deploy.py`/`ops/runtime.py` reaproveitam o `digest`/`RELEASE_ID` de
`.runtime/last-successful.json` quando nenhuma mudança de código exige nova
imagem — um rollback é, na prática, um novo `docker stack deploy` apontando
para o `APP_IMAGE`/`RELEASE_ID` anteriores já resolvidos por digest (nunca
por tag flutuante), reaproveitando o mesmo mecanismo de rollout
`start-first` com duas réplicas coexistindo (ver `docs/operations/deploy.md`).

## Coerência worker/beat

`app`, `celery_worker` e `celery_beat` usam a **mesma imagem** (`APP_IMAGE`)
com comandos diferentes (`command: [app|worker|beat]`, ver
`docker-stack.yml`) — um rollback troca a imagem das três réplicas de uma
vez; nunca existe uma janela em que o worker rode código de uma release e o
app de outra. Há sempre exatamente um `beat` (`replicas: 1`), evitando
agendamentos duplicados durante a transição.

## Encerramento de task conciliável

Tasks Celery em andamento durante um rollback/rollout usam
`stop_grace_period` generoso (60s app, 390s worker) e os handlers de outbox
(S08) são idempotentes via `ProcessedEvent` — uma task interrompida a meio
de um rollout é reprocessada com segurança pelo dispatcher na release
seguinte, sem duplicar efeito (verificado em S08 com o teste de redelivery).

## Decisões de escopo

- Um drill real de rollback (deploy da release N, rollback para N-1,
  confirmar coerência) depende de um Swarm real (P-02) — não foi executado
  nesta etapa. A garantia de "sem downgrade destrutivo" foi verificada por
  revisão de **todas** as migrations gravadas até S09: nenhuma remove ou
  renomeia coluna/tabela.
