# Homologação — Aderência visual (S14)

Toda sprint anterior (S04 a S13) documentou explicitamente que o polimento
visual e a integração com o arquivo real do design system
(`design_system/design-system.html`, tema "Duralux Admin UI Pattern
Library") ficariam para esta etapa. Esta é essa etapa.

## O que foi extraído do arquivo real

O design system referencia sua folha de estilo compilada real em
`design_system/refs/duralux/assets/f1bb68a482b802d8_index-D1a-T4mr.css`
(445 KB, Bootstrap + tema Duralux). Tokens extraídos diretamente dessa
folha (`grep` nas variáveis `:root` reais, não inventados):

| Token | Valor real extraído |
| --- | --- |
| `--bs-primary` | `#3454d1` |
| `--bs-secondary` | `#64748b` |
| `--bs-success` | `#17c666` |
| `--bs-info` | `#3dc7be` |
| `--bs-warning` | `#ffa21d` |
| `--bs-danger` | `#ea4d4d` |
| `--bs-body-color` | `#4b5563` |
| `--bs-body-bg` | `#f0f2f8` |
| `--bs-border-color` | `#e5e7eb` |
| `--bs-border-radius` | `4px` |
| `--bs-font-sans-serif` | pilha `system-ui` do próprio arquivo |

## O que foi implementado

- `static/base.css` (novo) — aplica exatamente esses tokens (cor, tipografia,
  raio de borda) a **toda** página do produto, via `templates/base.html`
  (o template mestre que toda tela já estende desde S01) — sem precisar
  restructurar nenhum template individual.
- `templates/base.html` reescrito: adiciona `<meta name="viewport">`
  (ausente até agora — item de acessibilidade real, ver
  `docs/homologation/accessibility.md`), um cabeçalho de navegação
  persistente (marca, links para Indicadores/CRM/Financeiro/Chat/
  Notificações/Assinatura/Sair) que não existia antes, e um contêiner
  `<main>` com `overflow-x: auto` como rede de segurança para tabelas
  largas que ainda não têm um wrapper próprio.
- Foco de teclado visível (`:focus-visible`) em todo link/botão/campo —
  verificado visualmente com uma captura de tela real após `Tab` (ver
  `docs/homologation/accessibility.md`).

## Achado real corrigido nesta sprint: não havia como escolher organização após o login

Testando o produto pela primeira vez nesta sessão como um usuário real
(via navegador de verdade, não injetando sessão diretamente pelo Django
shell como em toda homologação anterior), o login redirecionava sempre
para `/app/` — uma URL que não corresponde a nenhuma view registrada — e
não existia nenhuma tela para um usuário com mais de uma organização
escolher em qual entrar (`SwitchTenantView` já existia desde S02, mas
nada no produto o chamava). Corrigido:

- Nova `TenantPickerView` (`/accounts/select-organization/`) lista as
  organizações ativas do usuário; com exatamente uma, entra direto sem
  perguntar; com mais de uma, sempre exige escolha explícita (nunca
  reaproveita uma escolha de login anterior).
- `LOGIN_REDIRECT_URL` aponta para essa tela, não mais para `/app/`.
- `SwitchTenantView` e o `MFAChallengeView` agora redirecionam para
  `reporting:dashboard` (uma URL real) em vez de `/app/`.

Testado de ponta a ponta com um navegador real (Chrome via CDP,
`agent-browser`): login → seleção de organização → painel de indicadores
com dados reais renderizados corretamente, capturas de tela em anexo a
este registro (login, painel, foco de teclado, viewport móvel).

Um segundo caso foi encontrado e corrigido no mesmo teste: um link direto
para uma página protegida (`/app/crm/`) enquanto deslogado perdia o
destino original depois do login — o usuário sempre caía no painel
genérico, nunca na página que pretendia abrir. Corrigido em duas partes:
`TenantMiddleware` agora redireciona (em vez de 404) para a escolha de
organização quando o usuário está autenticado mas ainda sem organização
selecionada na sessão, preservando o destino original via `?next=`; e
`TenantPickerView`/`SwitchTenantView` repassam esse `next` (validado com
`url_has_allowed_host_and_scheme`, nunca um redirecionamento aberto) até o
fim. Testado de ponta a ponta: deslogado → link direto para `/app/crm/` →
login → escolha de organização → aterrissa exatamente em `/app/crm/`, com
os dois pacientes de demonstração já refletindo o card de CRM criado
automaticamente pela reserva de consulta (S09).

## Decisões de escopo

- ~~A folha de estilo completa do Duralux (445 KB CSS + 3,7 MB JS,
  componentes de sidebar/cards/kanban visual específicos do tema) **não**
  foi adotada integralmente — isso exigiria reestruturar a marcação HTML
  de mais de 30 templates para as classes específicas daquele tema, um
  escopo maior que esta sprint. O que foi adotado são os tokens de cor/
  tipografia/raio reais, aplicados sobre a estrutura HTML já correta de
  cada tela — uma melhoria visual real e de baixo risco, não uma
  reprodução pixel-a-pixel do arquivo de referência.~~

  **Decisão superada.** O tema passou a ser aplicado integralmente (CSS,
  JS, botões, sombras, animações e shell), incluindo a reestruturação da
  marcação das 51 telas — ver
  [aplicação integral do design system](design-system-full.md). O
  `static/base.css` descrito abaixo foi substituído por
  `static/duralux/duralux.css` (o arquivo real do tema, servido
  localmente) mais `static/duralux/neurodoc.css` e
  `static/duralux/app.js`.
- Um achado de UX real (o gap de seleção de organização) só apareceu
  porque este foi o primeiro teste de ponta a ponta como usuário real
  nesta sessão — toda sprint anterior validou views/dados via
  `django.test.Client` com sessão montada diretamente. Recomendação
  registrada para sprints futuras: incluir pelo menos um percurso de
  navegador real por sprint, não só chamadas de view isoladas.
