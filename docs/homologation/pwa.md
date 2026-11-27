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
