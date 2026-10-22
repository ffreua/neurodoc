# Voltar uma versão

Revisto em 2026-10-22 contra `ops/deploy.py` e `docker-stack.yml`. A versão
anterior deste documento, escrita antes da VPS, dizia duas coisas que não
eram verdade e que custariam caro no dia de usar: que `--skip-build` volta
para a release anterior (ele republica a **atual**) e que app e worker
nunca rodam releases diferentes (rodam, durante qualquer troca).

O rollback do NeuroDoc é **de imagem**: volta o código, não o banco. Ele
funciona porque as mudanças de esquema publicadas são *expand* — e é por
isso que a primeira pergunta antes de voltar é o que a release mudou no
banco (§3).

## 1. Quando a versão nova não fica saudável: sozinho

`app`, `celery_worker`, `celery_beat` e `traefik` têm
`failure_action: rollback` no `update_config`: se a tarefa nova não fica
saudável no período observado, o Swarm devolve **aquele serviço** à
especificação anterior. O `ops/deploy.py` percebe o estado de rollback,
termina com `Deployment failed or rolled back: <serviço>` e **não** grava
`.runtime/last-successful.json` — a última publicação boa continua sendo a
anterior.

`db`, `rabbitmq` e `redis` têm `failure_action: pause`: banco e filas não
voltam sozinhos. Pausado, o deploy também termina com erro, e o que fazer é
decisão de quem opera.

**A volta é por serviço, não do conjunto.** O `docker stack deploy` troca os
serviços cada um pela sua regra; se só o `app` falhar, ele volta e o worker
pode ter ficado na versão nova. Depois de um deploy que terminou em
rollback, confira a imagem dos três serviços da aplicação (§2) e volte os
que ficaram para trás.

## 2. Para voltar de propósito

Os três serviços que usam a imagem da aplicação, juntos:

```bash
docker service rollback neurodoc_v1_app
docker service rollback neurodoc_v1_celery_worker
docker service rollback neurodoc_v1_celery_beat
```

`docker service rollback` devolve o serviço à especificação de antes da
última atualização dele. Como todo deploy troca o `ROLLOUT_ID` dos três,
todo deploy atualiza os três — e "a especificação anterior" é a da
publicação anterior. Com duas ressalvas: se a última publicação foi um
`--skip-build` (troca de segredo, chave do `.env`), a anterior tem a
**mesma** imagem e o rollback não muda de versão; e o Swarm guarda um passo
só — um segundo `rollback` volta para onde se estava.

Voltar só o `app`, como alguns documentos mandavam,
deixa o worker executando tarefas com o código novo e o beat agendando pelo
código novo.

Conferir que voltaram para a mesma imagem, e qual é ela:

```bash
for s in app celery_worker celery_beat; do
  docker service inspect neurodoc_v1_$s --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'
done
grep APP_IMAGE .runtime/previous-successful.json
```

As três linhas têm de ser iguais, e iguais ao `APP_IMAGE` da publicação
anterior (`previous-successful.json` guarda o registro de antes da última
publicação bem-sucedida — depois de um `--skip-build`, ele também aponta
para a imagem atual). Se a imagem não for a esperada, não insista no
rollback: publique a correção.

### O que o rollback manual deixa para trás

`.runtime/last-successful.json` continua apontando para a versão da qual
se voltou — o `docker service rollback` não passa pelo `ops/deploy.py`. Duas
consequências:

- **`deploy.sh --skip-build` desfaz o rollback.** Ele republica a imagem de
  `last-successful.json`. E é o comando que a manutenção manda usar para
  trocar um segredo ou ligar uma chave do `.env` — então, depois de voltar
  de propósito, não use `--skip-build` até publicar a correção.
- **O backup registra a versão errada.** `ops/backup.py` copia o registro
  de `last-successful.json` para o `manifest.json`, e a restauração
  (`--activate`) exige o checkout exatamente daquele SHA.

A saída definitiva de um rollback manual é **publicar a correção** — um
commit novo (inclusive um `git revert`) pelo caminho normal de
`DEPLOY.md`, na raiz do repositório. Isso reescreve o registro e põe tudo de
volta em acordo.

## 3. O banco não volta

As releases publicadas até aqui se declararam *expand*: acrescentam
tabela, coluna, índice ou restrição sem remover nem renomear o que o código
anterior usa. A declaração é de quem publica — o preflight não lê as
migrations, só recusa `NEURODOC_SCHEMA_CHANGE` diferente de `expand`. Cada
nota em `docs/releases/` registra a mudança de esquema da sua release (as
linhas "Mudança de schema" e "Rollback").

Antes de voltar, leia essa linha na nota da release que está saindo. Duas
coisas que *expand* não garante:

- **coluna nova obrigatória.** O Django preenche as linhas existentes com o
  `default` do campo e não deixa default no banco; o código anterior, que
  não conhece a coluna, falha ao inserir linha nova naquela tabela;
- **migração de dados.** Uma `RunPython` que converte dado (a
  `scheduling/0007`, que encurtou retornos de 80 minutos, é um exemplo) não
  é desfeita pela volta da imagem.

Uma mudança que precise remover ou renomear coluna segue expand → migrar
dados → contract, em releases separadas, e a contract só entra quando
nenhuma release que dependa da coluna antiga ainda puder ser alvo de volta.
Nenhuma precisou disso até 2026-10-22.

## 4. Tarefas em andamento

`stop_grace_period` de 60 s no `app` e de 390 s no worker: a troca espera a
tarefa em curso terminar antes de matar o contêiner. Os consumidores da
outbox são idempotentes (`ProcessedEvent`), então um evento interrompido no
meio é reprocessado na volta sem duplicar efeito. Tarefa longa que morre na
troca precisa retomar pelo estado — é o que fazem a retomada da TUSS e a dos
jobs de IA parados (`CELERY_BEAT_SCHEDULE` em `core/settings.py`).

Há sempre um só `beat` (`replicas: 1`, `stop-first`): nunca dois agendando
ao mesmo tempo durante a troca.
