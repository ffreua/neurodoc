# Backup e restauração

## Backup (`ops/backup.py`, timer `neurodoc-backup.timer`)

Rodando diariamente às 03:00 (`America/Sao_Paulo`) num host com Swarm ativo:
adquire um `pg_advisory_lock` no Postgres (evita concorrência com outro
backup), gera `pg_dump --format=custom` do banco e um `tar` de cada volume
(`media`, `signing`, `letsencrypt`), cifrando cada stream diretamente com
`age -r <destinatário>` sem nunca gravar texto plano em disco. Um
`manifest.json` com hash SHA-256 e tamanho de cada arquivo, mais um marcador
`COMPLETE`, fecha o conjunto; a retenção mínima é de 7 dias e só remove
pastas com `COMPLETE` presente.

## Restauração (`ops/restore.py`)

`--prepare-data` recusa rodar se o host já tiver qualquer serviço/volume
`neurodoc_v1_*` (exige host de recuperação **vazio e separado** — nunca
sobrescreve o ambiente produtivo), confere a integridade de cada arquivo do
manifesto por hash antes de tocar em qualquer coisa, sobe um Postgres
temporário isolado (sem rede pública), restaura o dump como `neurodoc_owner`
e cada volume, confirma que `django_migrations` não está vazio, e só então
permite `--activate` (que exige `NEURODOC_RECOVERY_MODE=True` e todos os
canais externos desligados antes de subir o stack real).

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
