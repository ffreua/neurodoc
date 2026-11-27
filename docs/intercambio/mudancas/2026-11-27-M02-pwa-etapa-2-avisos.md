# MD-2026-11-27-02 — Aplicativo instalado, Etapa 2: avisos no celular

**Data:** 2026-11-27. **Tipo:** mudança (pedido do titular). **Feito nos dois na mesma rodada** (PD-M-2026-11-27-02).

## O que mudou

- **Avisos no celular (Web Push)**, ligados por aparelho na Central de notificações. Chegam o que
  vai ao sino, a mensagem da equipe e o pedido e o exame do portal. A notificação diz **só o
  tipo** (`push.TEXTOS`), nunca o paciente — decisão do titular.
- `notifications/webpush.py`: RFC 8291/8188/8292 sobre `cryptography` e `httpx`, sem dependência
  nova; `check_push` confere a cifra byte a byte contra o exemplo da RFC.
- `notifications/push.py`: lista fechada de serviços de push (o worker não faz `POST` para
  endereço qualquer), par VAPID gerado na primeira vez e cifrado em `InstallationSettings`
  (migração `base.0007`), `PushSubscription` da pessoa (migração `notifications.0003`), disparo
  depois do commit, envio pelo worker (`tasks.enviar_push`).
- Gatilhos: `services.notify_*` (o sino), `teamchat.services.send` (não para quem mandou, não para
  quem está on-line, uma por conversa a cada 2 min), `documents/portal.py` e `portal_exames.py`
  (para quem tem `READ_CLINICAL`).
- Worker do aparelho (`base/pwa.py`): `push` e `notificationclick`, só endereço do próprio site.
- **Sair** tira o aparelho (`user_logged_out` em `notifications/apps.py`, `nd-pwa.js`).
- `PWA_PUSH=False` (em `OPTIONAL_KEYS`) desliga só os avisos.
- Artigo `instalar-app` com o passo "Avisos no celular"; `check_idioma` conhece `InscricaoRecusada`.

## Diferenças entre os lados

Nenhuma no código novo: os arquivos são os mesmos, e o nome do produto vem de `base.pwa.PRODUTO`.

## Verificação

`check_push` e os vizinhos nos dois. Assinatura VAPID aceita pelos serviços reais da Apple e do
Google (ver `docs/homologation/pwa.md`, Etapa 2). Falta a homologação no aparelho real.
