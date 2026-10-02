# Backup e restauração

## Backup (`ops/backup.py`, timer `neurodoc-backup.timer`)

Rodando diariamente às 03:00 (`America/Sao_Paulo`) num host com Swarm ativo:
adquire um `pg_advisory_lock` no Postgres — a mesma trava que a aplicação
pega para coletar lixo ou compactar o arquivo morto
(`ops/locks.py::BACKUP_LOCK`), de modo que nenhum arquivo é movido, comprimido
ou apagado durante a cópia —, gera `pg_dump --format=custom` do banco e um
`tar` de cada volume
(`media`, `signing`, `letsencrypt`), cifrando cada stream diretamente com
`age -r <destinatário>` sem nunca gravar texto plano em disco. Um
`manifest.json` com hash SHA-256 e tamanho de cada arquivo, mais um marcador
`COMPLETE`, fecha o conjunto; a retenção mínima é de 7 dias e só remove
pastas com `COMPLETE` presente.

**Levar a cópia para fora da VPS** é
[`copia-externa.md`](copia-externa.md): o backup acima mora na mesma máquina
que ele protege, e `ops/backup.py` termina dizendo isso (`copy off-host and
verify restore`).

## Restauração (`ops/restore.py`)

`--prepare-data` recusa rodar se o host já tiver qualquer serviço/volume
`neurodoc_v1_*` (exige host de recuperação **vazio e separado** — nunca
sobrescreve o ambiente produtivo), confere a integridade de cada arquivo do
manifesto por hash antes de tocar em qualquer coisa, sobe um Postgres
temporário isolado (sem rede pública), restaura o dump como `neurodoc_owner`
e cada volume, confirma que `django_migrations` não está vazio, e só então
permite `--activate` (que exige `NEURODOC_RECOVERY_MODE=True` e todos os
canais externos desligados antes de subir o stack real).

## O que o host de recuperação precisa ter ANTES

`ops/restore.py --prepare-data` sobe o Postgres de recuperação com
`docker service create`, e isso traz pré-condições que não são óbvias
lendo só o comando. Nenhuma delas produz mensagem útil quando falta: o
`run()` de `ops/deploy.py` esconde a saída dos comandos de propósito
(ela pode conter dado de aplicação), então o que aparece é
`Command failed: docker service (exit 1)` e nada mais — na noite de
restaurar, que é a pior noite para descobrir isso.

| Precisa | Por quê |
| --- | --- |
| `age` no host | é ele que decifra; `restore.py` o chama direto |
| Docker em **modo Swarm** | usa `docker service create` e `docker config create` |
| Rótulo `neurodoc_data=true` no nó | o serviço tem `--constraint` para ele |
| Rede `neurodoc_v1_internal` (overlay, `--internal`) | é a rede do Postgres de recuperação |
| Segredos `NEURODOC_DB_ADMIN_PASSWORD`, `NEURODOC_DB_OWNER_PASSWORD`, `NEURODOC_DB_APP_PASSWORD` | o Postgres nasce com eles |
| `docker login` no registry | `resolve_image` puxa a imagem da release |
| `.env` com o mesmo `REGISTRY` | `read_manifest` recusa manifesto de outro registry |
| Nenhum serviço ou volume `neurodoc_v1_*` | a recusa deliberada de host não-vazio |

**Os três segredos de banco não precisam ser os de produção.** O Postgres
da recuperação é inicializado do zero com eles, e `pg_dump --format=custom`
de um banco não carrega definição de papel — então valores novos servem.
Isso é bom saber sob pressão: **a senha do banco não faz parte do que você
precisa ter guardado para restaurar.**

O que **precisa** ser o de produção são `NEURODOC_PFX_MASTER_KEY` e
`NEURODOC_SECRETS_MASTER_KEY`, e só na hora do `--activate`: sem elas o
banco volta inteiro e os campos cifrados (certificado de assinatura,
credenciais de SMTP das clínicas) voltam ilegíveis.

```bash
docker swarm init
docker node update --label-add neurodoc_data=true $(docker node ls -q)
docker network create --driver overlay --internal neurodoc_v1_internal
for s in NEURODOC_DB_ADMIN_PASSWORD NEURODOC_DB_OWNER_PASSWORD NEURODOC_DB_APP_PASSWORD; do
  openssl rand -base64 48 | tr -d '

' | docker secret create "$s" -
done
```

## Primeiro drill real — 2026-09-26

Feito na **máquina de trabalho do responsável**, e não na VPS, que é o
ponto: um backup restaurado no mesmo servidor que o gerou não prova nada,
porque um incêndio leva os dois juntos.

- Backup usado: o do **timer**, não um feito à mão — `20260926T060116Z`,
  gerado sozinho às 03:00 da primeira madrugada.
- Integridade de cada arquivo conferida por SHA-256 antes de tocar em nada.
- Restaurados: banco, `media`, `signing`, `letsencrypt`.
- Conferido no banco de recuperação: 109 migrations, a clínica com plano e
  estado corretos, as contas, CID-10 (14.233) e CMED (26.242) íntegros, e a
  **última migration publicada presente** — o backup do timer pegou o
  esquema de depois do deploy daquele dia, não um anterior.
- **Aceite do contrato**: o SHA-256 recalculado do texto arquivado bate com
  o hash gravado. A cópia integral exigida pela cláusula 2.3 sobreviveu à
  volta e continua verificável.
- `acme.json` restaurado aponta para `acme-v02` — o certificado de
  produção, não o de teste.

Fica aberto o `--activate` num host separado com as chaves-mestras reais, e
com ele a medição de RPO/RTO. **H-22 deixa de estar sem nenhuma evidência**:
a metade que não dependia de chave-mestra está exercitada contra backup
real gerado por timer real.

## Verificado nesta etapa (sem VPS/backup externo real)

- **Mecânica criptográfica do `age`**: roundtrip completo testado com um
  par de chaves real gerado por `age-keygen`, reproduzindo exatamente as
  funções `encrypt_stream`/`decrypt_to` usadas pelos scripts — cifrado com o
  destinatário, decifrado com a identidade correspondente, bytes idênticos
  ao original; uma identidade **errada** falha fechado (não retorna
  conteúdo algum), confirmando que a integridade depende genuinamente da
  posse da chave privada.
- **`prepare_recovery`** (comando pós-restauração, S10-T07): executado de
  verdade contra o banco local. Bugs reais encontrados e corrigidos nesta
  sprint (o comando já existia desde S01, escrito antecipando modelos que só
  foram implementados agora):
  - `SigningSession.encrypted_unlock_material` é `TextField`; o comando
    tentava gravar `b''` (bytes) — corrigido para `''`.
  - `Delivery.status='needs_reconciliation'` não existia em
    `DeliveryStatus.choices` — adicionado.
  - `apps.get_model('ai', 'AIJob')` derrubava o comando inteiro com
    `LookupError`, já que o app `AIJob` só é modelado em S11 — agora
    tratado com `try/except`, contabilizando zero jobs de IA reconciliados
    até que S11 exista.
  - Após as correções, o comando roda de ponta a ponta: revoga sessões de
    assinatura (zerando o material de desbloqueio), revoga tokens de acesso
    a documento, marca entregas pendentes/aceitas/desconhecidas/falhas como
    `needs_reconciliation`, marca eventos de outbox não concluídos como
    `held_restored`, invalida todas as sessões web e grava um
    `AuditEvent` (`platform.recovery_prepared`) com as contagens — tudo
    confirmado lendo o banco após a execução real.
  - Confirmado também que o comando **recusa** rodar fora do modo de
    recuperação ou com qualquer canal externo habilitado.

## Decisões de escopo

- Um drill completo (`ops/backup.py` real → cópia para fora da VPS →
  `ops/restore.py --prepare-data` → `--activate` num host separado) depende
  de uma VPS real em Swarm (P-02) e de um destino externo autorizado com
  titular de chave definido (P-10) — nenhum dos dois está disponível. RPO/RTO
  não puderam ser medidos contra infraestrutura real; H-22 permanece aberto
  até essas duas pendências resolverem.
- O `manifest.json`/hash/`COMPLETE` e a recusa de host não-vazio foram
  verificados por leitura de código (lógica pura, sem dependência externa
  além do Docker/Swarm em si).
