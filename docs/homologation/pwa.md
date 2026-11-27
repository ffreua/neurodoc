# Aplicativo instalado (PWA) — Etapa 1

> **2026-11-27, NeuroDoc 1.63 / ProntDoc 1.17.0.** O mesmo desenho nos dois
> produtos; muda só o nome e a cor (`base/pwa.py::PRODUTO`, `COR`). Roteiro:
> `checks/check_pwa.py`.

## O que já existia antes desta etapa

O manifesto (`/site.webmanifest`, `base/seo_views.py::ManifestView`), os
ícones na raiz e a cor do tema já estavam no ar desde a 1.5, e as telas já
tinham passado pela auditoria de celular (`mobile.md`). Já dava para
"Adicionar à tela inicial" — e o ícone criado assim abria num **404**:
`start_url` era `/app/`, e nenhuma rota respondia em `/app/` exatamente.

## O que esta etapa faz

| Peça | Onde | Por quê |
| --- | --- | --- |
| `/app/` redireciona à tela inicial | `core/urls.py` (`app-inicio`) | O ícone abria um 404 depois do login. Rota, e não troca do `start_url`: o iPhone guarda o endereço no dia em que o ícone foi criado e nunca o relê, então só a rota conserta os ícones que já existem. Vai ao painel, que já manda cada papel à sua tela (a secretária ao balcão). |
| `id` fixo no manifesto | `ManifestView` | Sem `id`, a identidade do app é o `start_url`; mudá-lo um dia faria o Android tratar a versão nova como outro app. |
| Atalhos Agenda e Pacientes | `ManifestView` | Abrem para os quatro papéis (conferido no roteiro). "Novo atendimento" não entra: precisa de um paciente. |
| Service worker | `base/pwa.py`, `/sw.js`, `static/duralux/nd-pwa.js` | Só a tela **sem internet** (`/offline/`). |
| Manifesto fora das telas do paciente | `pwa.instalavel`, `partials/head.html` | O paciente que adicionasse o portal à tela inicial ganharia um ícone que abre o login da clínica. |
| "Instalar o app" | menu da conta, login, artigo `instalar-app` | O botão "Instalar agora" só aparece quando o navegador entrega o pedido (Chrome e Edge); no iPhone, o artigo aponta o passo do Safari. Some dentro do app instalado (`@media (display-mode: standalone)`). |

## O que o service worker **não** faz, e por quê

- **Não guarda nenhuma tela do sistema.** Página de `/app/` carrega
  prontuário, e celular se perde, é roubado e é emprestado. O cache tem um
  item só: a própria `/offline/`, sem dado de ninguém, sem script e sem
  arquivo externo.
- **Não toca em `POST`** nem em nada que não seja navegação `GET`:
  formulário, assinatura, envio de arquivo, o SSE do chat e o `fetch` das
  telas passam direto.
- **Não toca em navegação fora de `/app/` e `/accounts/`**: portal do
  paciente, `/d/`, `/verificar/` e a vitrine seguem como sempre, mesmo no
  navegador de quem instalou.
- **Erro do servidor passa como veio.** Só a falha de rede vira a tela sem
  internet; um 403 ou 500 disfarçado de "sem conexão" mandaria o
  diagnóstico para o lugar errado.

Por isso não há modo "offline" do prontuário, e a decisão é deliberada: o
rascunho local do atendimento (`static/clinical/atendimento.js`) já cobre a
queda curta de conexão no meio da consulta.

## Botão de emergência e rollback

`PWA_SERVICE_WORKER=False` no `.env` da VPS e republicar
(`scripts/deploy.sh --skip-build` basta). As páginas param de registrar o
worker e `/sw.js` passa a servir um que apaga o próprio cache e se
desregistra na próxima visita de cada aparelho. Apagar o arquivo do
servidor **não** bastaria: o worker já instalado continuaria lá.

A chave está em `ops/make_runtime.py::OPTIONAL_KEYS` — sem ela o valor do
`.env` não chegaria ao contêiner (o `check_csp` reprovou a primeira versão
por isso). Fora do `.env.example` de propósito: o deploy completa o `.env`
da VPS com o molde, e o padrão do código (ligado) basta.

Voltar a versão do código também é seguro, mas não apaga o worker dos
aparelhos: ele continua registrado e fazendo só o que fazia — mostrar a
`/offline/` guardada quando a rede cai — com o código antigo. Para
tirá-lo, ligue o botão de emergência **antes** de voltar a versão, espere
os aparelhos visitarem o sistema, e só então volte.

## Homologação (2026-11-27, ambiente local, Chromium)

| Conferência | NeuroDoc | ProntDoc |
| --- | --- | --- |
| `check_pwa` e vizinhos (SEO, ajuda, login, CSP, celular, vitrine, idioma, rótulos, portal, auditoria, compressão, processos) | passam | passam |
| Worker registrado e controlando a página | sim | sim |
| Servidor desligado: `/app/...` mostra a tela sem internet; `/verificar/` não é tocado | sim | sim |
| "Tentar de novo" reabre a tela pedida; 404 do servidor passa como veio | sim | — |
| Formulário (rascunho de documento) e visualização do PDF com o worker ativo | sim | — |
| Botão de emergência: na visita seguinte o worker some e a página não o registra | sim | — |
| Chrome entrega o pedido de instalação ("Instalar agora" aparece) | sim | sim |
| Transbordo horizontal em 8 telas × 9 tamanhos (360×740, 390×844, 844×390, 768×1024, 820×1180, 1024×1366, 1280×800, 1366×768, 1920×1080) | zero | zero |

O download de PDF não pôde ser conferido pela ferramenta de navegação: ela
cancelou o download **também com o worker desligado**, então o limite é
dela. O worker devolve a resposta do servidor sem tocá-la (cabeçalhos
inclusive). A conferir no aparelho real, junto com o iPhone, que o
Chromium não simula.

## A conferir no aparelho real

1. iPhone (Safari): Compartilhar → Adicionar à Tela de Início; o ícone abre
   o login e, depois dele, a tela inicial; "Instalar o app" some no menu.
2. Android (Chrome): "Instalar app"; os atalhos ao segurar o ícone.
3. Baixar um PDF de documento dentro do app instalado.
4. Modo avião com o app aberto: a tela sem internet.

---

# Etapa 2 — avisos no celular (Web Push)

> **2026-11-27, NeuroDoc 1.64 / ProntDoc 1.18.0.** O mesmo código nos dois
> produtos (`notifications/push.py`, `notifications/webpush.py`). Roteiro:
> `checks/check_push.py`.

## Decisões do titular

- **O que chega:** tudo que vai ao sino (IA pronta ou falhou, resposta do
  assistente, exportação pronta, documento sem contato para entrega — e todo
  tipo novo que o sino ganhar), a **mensagem da equipe** e o **pedido e o
  exame enviados pelo portal**.
- **O que a notificação diz:** **só o tipo** ("Nova mensagem da equipe",
  "Resultado da IA pronto para revisão."), **nunca o nome do paciente** —
  ela aparece na tela bloqueada. Os textos estão em `push.TEXTOS`; tipo sem
  texto sai com "Você tem um novo aviso.", e nunca com o título do sino.

## Como funciona

| Peça | Onde | Por quê |
| --- | --- | --- |
| Ligar por aparelho | Central de notificações, `templates/notifications/_avisos_no_celular.html`, `static/duralux/nd-push.js` | A permissão do navegador só é pedida no toque do botão: pedida ao abrir a tela, a pessoa clica em "Bloquear" sem ler, e o bloqueio só se desfaz nas configurações do aparelho. Cinco estados: desligado, ligado (com teste e desligar), bloqueado, iPhone fora do app instalado, sem suporte. |
| A inscrição | `PushSubscription` (da **pessoa**, não da clínica) | O aparelho é um só e quem trabalha em duas clínicas quer os avisos das duas nele. Dez aparelhos por pessoa (sai o mais antigo); o mesmo aparelho passa para quem entrou nele. |
| O endereço de entrega | `push.SERVICOS` | Vem do navegador e o worker faz `POST` nele: só Google, Apple, Mozilla e Windows, `https`, sem porta e sem usuário. Aceitar qualquer endereço faria do worker — que está na rede do banco e do Redis — um carteiro para onde o usuário quisesse. |
| Cifra e assinatura | `notifications/webpush.py` | RFC 8291 (cifra), 8188 (`aes128gcm`) e 8292 (VAPID) sobre `cryptography` e `httpx`, já no lock com hash. `pywebpush` foi recusada: as versões novas puxam `aiohttp`, `http-ece` e `py-vapid` para dentro do worker que guarda as chaves de SMS, e-mail e IA. O risco de errar um byte é coberto pelo roteiro, que confere o exemplo da RFC byte a byte. |
| O par VAPID | `InstallationSettings.push_vapid_*` | Gerado na primeira vez que alguém abre a Central, a privada cifrada (`base.crypto`), como a chave da IA reserva. **Não** é segredo do Swarm: um segredo novo no `docker-stack.yml` teria de existir na VPS antes do deploy. **Trocar o par derruba todas as inscrições**, então ninguém troca à mão. |
| O disparo | `services.notify_*`, `teamchat.services.send`, `documents/portal.py`, `portal_exames.py` | Sempre **depois do commit**. Quem não tem aparelho não gera tarefa. A mensagem da equipe não vai a quem mandou nem a quem está on-line (`presence`), e no máximo uma por conversa a cada dois minutos por pessoa. O portal vai a quem tem `READ_CLINICAL` — a mesma capacidade que abre Portal → Solicitações. |
| O envio | `tasks.enviar_push` (worker) | Como SMS e e-mail. 404/410 apagam a inscrição; outra falha conta, e cinco seguidas apagam. Sem nova tentativa: aviso atrasado dez minutos já não serve. O log tem só o servidor do serviço, nunca o endereço inteiro. |
| No aparelho | `base/pwa.py` (`push`, `notificationclick`) | Mostra sempre (o navegador exige) e abre só endereço do próprio site; foca a janela aberta em vez de abrir outra. |
| Sair | `notifications/apps.py`, `nd-pwa.js` | "Sair" cancela a inscrição no navegador e o servidor tira a linha daquele aparelho. A sessão que **vence** não tira, de propósito: a pessoa teria de religar a cada sessão vencida, e o aviso não traz dado de paciente. |

## Botões de emergência

- `PWA_PUSH=False` no `.env` e republicar: nada sai, o painel some e as
  rotas respondem 404; a tela sem internet continua. Está em
  `ops/make_runtime.py::OPTIONAL_KEYS` e fora do `.env.example`.
- `PWA_SERVICE_WORKER=False` desliga as duas etapas: o worker que se apaga
  desregistra o worker do aparelho, e com ele a inscrição.

## Homologação (2026-11-27, ambiente local)

| Conferência | NeuroDoc | ProntDoc |
| --- | --- | --- |
| `check_push` (cifra contra a RFC 8291, VAPID, inscrição, telas, disparo, envio, worker, Sair, botões de emergência) | passa | passa |
| Roteiros vizinhos (PWA, notificações, mensagens, portal, CSP, idioma, rótulos, celular, provedor e SMS, isolamento, SEO, ajuda) | passam | passam |
| A Central mostra o painel no estado certo, acima da lista, com o worker controlando a página e sem transbordo em 360, 390, 768 e 1366 px | sim | sim |
| Assinatura VAPID contra os serviços **reais**: com a assinatura certa a Apple recusa só o aparelho inexistente (`BadWebPushToken`) e o Google responde 410; adulterada, os dois recusam a assinatura (403 `BadJwtToken` / `invalid JWT`) | sim | — |

O navegador da ferramenta de automação (Chromium sem janela) recusa a
permissão de notificação, e por isso a inscrição de ponta a ponta fica
para o aparelho real.

## A conferir no aparelho real

1. Android (Chrome) e computador: Central → **Ativar neste aparelho** →
   permitir; **Enviar um aviso de teste** chega em segundos; tocar nele abre
   a Central.
2. iPhone (iOS 16.4+): o painel pede o app instalado no Safari; pelo ícone
   da tela inicial, ativar e testar.
3. Com o sistema fechado no celular, uma mensagem da equipe mandada do
   computador chega como "Nova mensagem da equipe", sem nome nem texto.
4. **Sair** no celular; o teste mandado de outro aparelho não chega mais a ele.

---

# Comunicados do console

> **2026-11-27, junto com a Etapa 2.** `notifications/comunicados.py`,
> `/instalacao/comunicados/`. Roteiro: `checks/check_comunicados.py`.

O superadministrador escreve um comunicado e ele chega ao **sino** de cada
pessoa (na clínica dela) e ao **celular** de quem ligou os avisos, com o
título e o começo do texto; ao tocar, abre a página com o texto inteiro.

- **Dois tipos:** aviso do sistema e propaganda, com a etiqueta na página.
  **Sem recusa** (decisão do titular). A propaganda fica **travada** até o
  contrato `CONTRATO_COM_PROPAGANDA` e, depois, vai só à clínica cujo
  último aceite é dessa redação — o contrato vigente cobre o aviso
  (cláusula 18.1), não a publicidade. Minuta em
  `docs/governance/comunicados-minuta.md`.
- **Público:** todas as clínicas, as de um plano, uma clínica, ou um papel.
  Vínculo ativo; clínica encerrada nunca; suspensa só no aviso.
- **Prévia antes de enviar** (clínicas, pessoas, aparelhos) e o **código do
  segundo fator recente** para enviar, como as outras ações graves do console.
- **Texto da casa:** escapado na página, link só do próprio site; nunca dado
  de paciente. A trilha registra o envio sem o texto.
- **Entrega pelo worker**, calculando os destinatários na hora; a tarefa
  repetida não entrega duas vezes. O histórico mostra pessoas, aparelhos
  entregues e falhas.
