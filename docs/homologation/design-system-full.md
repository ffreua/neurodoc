# Aplicação integral do design system Duralux

Este documento fecha a decisão de escopo registrada em
[aderência visual (S14)](design-adherence.md), que havia adotado **apenas**
os tokens de cor/tipografia/raio do tema e mantido a marcação HTML
original de cada tela. A pedido do produto, o tema passou a ser aplicado
integralmente: CSS, JavaScript, comportamento de botões, sombras,
animações e a estrutura de shell do arquivo de referência
`design_system/design-system.html`.

## Assets: o tema real, servido localmente

| Arquivo publicado | Origem | Observação |
| --- | --- | --- |
| `static/duralux/duralux.css` (443 KB) | `design_system/refs/duralux/assets/f1bb68a482b802d8_index-D1a-T4mr.css` | Bootstrap 5.3 + tema Duralux, cópia do arquivo real |
| `static/duralux/fonts/inter-latin.woff2` (48 KB) | `design_system/refs/duralux/assets/c940764593d0fe5d_UcC73FwrK3iLTeHuS_nVMrMxCp50Sj.woff2` | Inter variável (eixo `wght` 100–900), subconjunto latino |
| `static/duralux/images/check-primary-soft.png` | asset homônimo da referência | único bitmap que a referência realmente traz |
| `static/duralux/app.js` (19 KB) | escrito para este projeto | ver "JavaScript" abaixo |
| `static/duralux/neurodoc.css` (8 KB) | escrito para este projeto | ver "O que foi acrescentado" abaixo |

Três modificações foram feitas na cópia do CSS, todas registradas aqui
porque alteram o arquivo de referência:

1. **`@import` do Google Fonts removido.** A folha original abre com
   `@import "https://fonts.googleapis.com/css2?family=Cinzel:…&family=Inter:…"`
   — 22 famílias, uma requisição a um serviço externo em toda página. Um
   produto que exibe prontuário não deve emitir requisição a terceiro no
   carregamento de tela. No lugar, um único `@font-face` local para Inter
   (a única família que as regras do próprio tema usam: quatro
   declarações `font-family:Inter,sans-serif`; as outras 21 existem
   apenas para o seletor de fonte do "theme customizer", que este produto
   não usa). Confirmado com `fontTools` que o `.woff2` disponível é o
   Inter **variável** latino (`wght` 100–900), portanto uma única
   declaração cobre todos os pesos do tema.
2. **Quatro `url(/images/icons/*.png)` neutralizados.** São bitmaps que a
   referência nunca entregou (`check.png`, `check-green.png`,
   `check-primary.png`), usados só por `.custom-checkbox`,
   `.custom-table-checkbox` e pelo "theme customizer" — componentes que
   este produto não usa. Foram trocados por `content:""` /
   `background-image:none` em vez de apontar para um bitmap diferente
   (que renderizaria o ícone errado) ou de deixar quatro 404 por página.
3. **Nada mais.** Nenhum token, cor, sombra, raio, transição ou
   breakpoint do tema foi redefinido dentro dessa cópia.

O bundle React de 3,7 MB (`faa5d6593f77e237_index-CbND3wdT.js`) **não** foi
adotado: a página de referência não o carrega (seu `<head>` traz apenas
favicon e as duas folhas de estilo) e ele é o aplicativo de demonstração
do tema, não uma dependência da folha de estilo.

Verificado no navegador real: a página carrega exatamente **4** recursos,
todos da própria origem — `duralux.css`, `neurodoc.css`, `app.js` e
`inter-latin.woff2`; `document.fonts.check('16px Inter') === true`;
console sem erros.

## Shell: a estrutura do arquivo de referência

`templates/base.html` foi reescrito como o shell Duralux real, extraído da
marcação minificada das linhas 52 (header) e 57 (sidebar) de
`design_system/design-system.html`:

```
nav.nxl-navigation > .navbar-wrapper > .m-header + .navbar-content > ul.nxl-navbar
header.nxl-header  > .header-wrapper  > .header-left + .header-right
main.nxl-container > .nxl-content     > .page-header + .main-content
                   > footer.footer
```

Contratos de classe lidos direto do CSS do tema, não inventados:
sidebar de 280 px que colapsa para 100 px via `html.minimenu`; header de
80 px com `left:280px`; `.nxl-container` com `margin-left:280px` e
`top:80px`; itens de menu `li.nxl-item[.nxl-caption|.active|
.nxl-hasmenu.nxl-trigger] > a.nxl-link > span.nxl-micon + span.nxl-mtext
+ span.nxl-arrow`, com submenu `ul.nxl-submenu.nxl-menu-visible|
.nxl-menu-hidden`; responsividade em `max-width:1024px`
(`.nxl-navigation{left:-280px}` + `.mob-navigation-active`) e
`max-width:1199.98px` (`.nxl-container{margin-left:0}`) já vem do próprio
tema.

Um segundo shell, `templates/base_auth.html`, atende as telas que existem
fora de um tenant (landing, autenticação, escolha de organização,
convites, link de documento do paciente), usando o card de autenticação do
tema (`.auth-container .card.wd-450`). Sem ele, `.nxl-container` deixaria
280 px de sidebar inexistente à esquerda dessas telas.

## JavaScript: `static/duralux/app.js`

A página de referência **não carrega nenhum JavaScript** — o `<head>` tem
apenas favicon e CSS, e o único script é um bloco inline no fim do arquivo.
Ou seja: os contratos que a folha de estilo espera (`.show` em
`.dropdown-menu`, `.active` em `.tab-pane`, `html.minimenu`,
`html.app-skin-dark`, `.nxl-trigger`, `.collapse.show`) não têm
implementação na referência. `app.js` os implementa em JavaScript puro —
sem Bootstrap bundle, sem jQuery, sem Popper, sem nenhuma requisição
externa:

| Comportamento | Contrato do CSS |
| --- | --- |
| Colapso da sidebar (persistido em `localStorage`) | `html.minimenu` |
| Sidebar em telas pequenas + overlay | `.mob-navigation-active`, `.hamburger.is-active`, `.nxl-md-overlay` |
| Menu multinível | `li.nxl-hasmenu.nxl-trigger`, `.nxl-menu-visible` / `.nxl-menu-hidden` |
| Tema escuro (persistido) | `html.app-skin-dark` |
| Dropdowns (aninhados, fecha por clique externo e `Esc`) | `.dropdown-menu.show` |
| Abas e pills | `.nav-link.active` + `.tab-pane.active.show` |
| Collapse e acordeão | `.collapse.show`, `.collapsed`, `data-bs-parent` |
| Alertas dispensáveis | `data-bs-dismiss="alert"` |
| Tooltips | `.tooltip > .tooltip-arrow + .tooltip-inner` |
| Contadores animados dos KPI | `.counter` |
| Tela cheia | `.full-screen-switcher` |
| Botão de submit ocupado | `.spinner-border` (evita duplo envio em salvamento clínico lento) |

Duas correções reais foram necessárias e estão explicadas em comentário no
próprio arquivo:

- **Alinhamento de dropdown.** O Bootstrap condiciona suas próprias regras
  de posicionamento (`.dropdown-menu-end{right:0;left:auto}`, `.dropup`,
  etc.) ao atributo `data-bs-popper`, que só o Popper adiciona. Sem isso o
  menu "Mover para" do CRM abria para fora da tela. `app.js` define o
  atributo ao abrir e remove ao fechar — o posicionamento documentado do
  Bootstrap, sem biblioteca de posicionamento. Verificado no navegador.
- **Motion reduzida.** Contador e fade de alerta checam
  `prefers-reduced-motion`.

## O que foi acrescentado: `static/duralux/neurodoc.css` (8 KB)

Só o que o tema não cobre, com o motivo de cada bloco no próprio arquivo.
Nenhum token, cor, sombra ou raio do Duralux é redefinido aqui.

- **Marca textual na sidebar.** O tema espera dois bitmaps de logo
  (`logo-full.png`, `logo-abbr.png`) que são do Duralux, não deste
  produto. No lugar, um selo quadrado com a inicial mais o wordmark.
- **Rolagem da sidebar.** `.navbar-content` tem
  `height:calc(100vh - 80px)` e nenhum `overflow`: o tema depende do
  plugin `perfect-scrollbar` (não incluído na referência) para rolar. Sem
  isso, em tela baixa os últimos itens do menu ficam inalcançáveis.
  Corrigido com rolagem nativa.
- **Botões suaves como link no tema escuro** (defeito real do tema). O
  skin escuro do Duralux tem
  `html.app-skin-dark a, … { color:#fff !important }`. Um
  `.btn-light-primary` mantém o fundo lavanda claro, então **todo botão
  suave escrito como `<a>`** virava branco sobre claro — ilegível.
  Encontrado no navegador (botão "Prontuário" da tela de paciente),
  confirmado por inspeção das regras aplicadas
  (`getComputedStyle` → `rgb(255,255,255)`), corrigido restaurando a cor
  contextual apenas no estado de repouso (o hover, que troca o fundo por
  cor sólida, continua do tema).
- **Alertas contextuais no tema escuro.** O design system usa alertas
  Bootstrap padrão (`.alert-primary` e afins), mas o skin escuro do
  Duralux só reestiliza suas próprias variantes
  `.alert-soft-*-message` — os padrões ficavam brancos numa página
  escura. Os blocos acrescentados seguem o idioma do próprio tema para
  alertas escuros (fundo suave, texto contextual, borda tracejada).
- **Foco visível.** `:focus-visible` em link/botão/`.nxl-link`/
  `.page-link`/`.dropdown-item` e um "pular para o conteúdo". Requisito
  de uso por teclado do prontuário, mantido de S14.
- **Formulários renderizados pelo Django** (`.nd-form`) e impressão
  (esconde sidebar/header/rodapé, zera o offset do container).

## Templates: 51 telas convertidas

As 51 telas do produto (o total de 58 arquivos em `templates/` menos os
dois shells, os quatro parciais e `registration/password_reset_email.html`,
que é texto puro de e-mail e não deve receber marcação) passaram a usar os componentes documentados no
arquivo de referência:

- **Cabeçalho de página** — `.page-header` com `.page-header-title h5`,
  `ul.breadcrumb` e `.page-header-right-items`, via blocos
  `{% block page_title %}` / `{% block breadcrumb %}` /
  `{% block page_actions %}` do `base.html`.
- **Cards** — `.card.stretch.stretch-full` com
  `.card-header`/`.card-body`/`.card-footer`; `.card-body.p-0` quando o
  corpo é tabela ou lista.
- **Tabelas** — `.table-responsive > table.table.table-hover.align-middle`
  com `thead.bg-gray-100 > tr.border-b`, `th.ps-4` e última coluna
  `.text-end.pe-4`.
- **KPI** — `.short-info-card` com `.avatar-text.avatar-lg.bg-gray-200.icon`,
  `.fs-4.fw-bold.text-dark > .counter` e `.progress.ht-5`.
- **Botões** — sólidos `.btn-primary`…, suaves `.btn-light-*`, `.btn-icon`,
  tamanhos `.btn-sm`, estado ocupado com `.spinner-border`.
- **Formulários** — `.form-label.fw-semibold`, `.form-control`,
  `.form-select`, `.form-check`, `.form-text.fs-11`, `.is-invalid` +
  `.invalid-feedback`, `.input-group` com `.input-group-text.bg-white`.
- **Status** — `.badge.bg-soft-{tom}.text-{tom}`, com o tom vindo do filtro
  `nd_tone` (`base/templatetags/nd.py`), que mapeia cada valor de status
  real dos modelos para a cor contextual do tema e cai no tom neutro para
  valor desconhecido, em vez de arriscar uma cor que sugerisse a
  gravidade errada.

Dois auxiliares novos evitam repetir marcação 30 vezes:
`templates/partials/form_fields.html` renderiza qualquer form Django com
as classes do tema, e `base/templatetags/nd.py` decide a classe de
controle por tipo de widget (`nd_field`), o tom de badge (`nd_tone`) e o
agrupamento do kanban por etapa (`nd_in_stage`).

`base/context_processors.py` fornece ao shell o que ele precisa em toda
tela — organização atual, papéis, contador e últimas notificações, seção
ativa da sidebar — sempre derivado de `request.access_context` e portanto
escopado ao tenant da requisição, nunca cacheado entre requisições.

## Defeitos reais encontrados e corrigidos nesta etapa

1. **Comentário Django multilinha renderizado como texto visível.**
   `{# … #}` só funciona em uma linha; três comentários meus tinham duas
   ou três. O texto do comentário aparecia no topo da tela de login.
   Encontrado na primeira captura de tela real, não na verificação de
   sintaxe (que passa sem reclamar). Trocados por
   `{% comment %}`/`{% endcomment %}`.
2. **`{% url 'documents:medical-list' %}` sem argumento na sidebar.** A
   rota exige `encounter_id`. Documento médico pertence a um atendimento e
   é aberto a partir dele; a sidebar passou a levar só à assinatura.
3. **Botões irmãos empilhados verticalmente.** O tema define
   `.btn{display:flex}`, então dois botões lado a lado em célula de tabela
   viram duas linhas. Encontrado na lista de pacientes ("Abrir" acima de
   "Prontuário"), corrigido com um `.d-inline-flex` em volta.
4. **`credential_id` duplicado no formulário de sessão de assinatura.** O
   `<select>` da tela e o campo oculto homônimo do form enviavam o mesmo
   nome; o oculto (vazio) vinha depois e sobrescreveria a escolha.
   Corrigido renderizando só `duration_hours` e `password` do form.
5. **`.nxl-navigation .navbar-content` sem rolagem** (defeito do tema, ver
   acima).
6. **Botões suaves como link ilegíveis no tema escuro** (defeito do tema,
   ver acima).
7. **Dropdown abrindo fora da tela** (contrato do Bootstrap que depende do
   Popper, ver acima).
8. **`LogoutView` acionado por link.** O `Django LogoutView` só aceita
   `POST`; o menu anterior tinha `<a href="…/logout/">`, que responderia
   405. O menu da conta agora envia um `POST` com CSRF.
9. **Rótulos de formulário em inglês.** As telas reestilizadas expuseram
   rótulos gerados automaticamente do nome do campo ("Duration hours",
   "Password", "Full name", "Birth date"…) ao lado de texto em português.
   Corrigidos com `label=` nos `forms.Form` e `labels = {…}` no `Meta`
   dos `ModelForm` — nenhuma alteração de modelo, nenhuma migration.

## Verificação executada

| Verificação | Resultado |
| --- | --- |
| Parse de todos os templates (`get_template`) | 58/58 sem erro |
| Renderização das páginas com dados reais semeados (`django.test.Client` contra a pilha Docker em execução) | 27 páginas, 0 falhas |
| Renderização das telas ainda sem dado semeado, com contexto sintético (exercita aridade de `{% url %}` e filtros) | 26 templates, 0 falhas |
| Navegador real (Chrome via CDP) | login → escolha de organização → indicadores → pacientes → paciente → prontuário → atendimento → agenda → CRM → financeiro → chat → assinatura |
| Interações verificadas no navegador | colapso da sidebar, menu multinível, tema escuro, dropdown de notificações, dropdown da conta, dropdown "mover etapa" do CRM, collapse de "adicionar contato" |
| Requisições de rede da página | 4, todas da própria origem; Inter carregada localmente; console sem erros |

## O que não foi feito

- **Componentes do tema que o produto não usa** continuam apenas na folha
  de estilo, sem marcação correspondente: mega-menu do header, seletor de
  idioma, "theme customizer", calendário `tui-full-calendar`, gráficos
  ApexCharts, e-mail/chat/tarefas do aplicativo de demonstração. Nenhum
  deles corresponde a uma tela deste produto.
- **Kanban com arrastar-e-soltar.** O quadro de CRM é colunar como no
  tema, mas a transição de etapa continua por botão dentro de um dropdown
  — acionável por teclado (Tab + Enter) e auditável, como exige
  `crm/views.py`. Arrastar-e-soltar exigiria uma biblioteca externa e
  removeria o caminho por teclado.
- **Escala-alvo de desempenho.** O CSS do tema tem 443 KB (63 KB
  comprimidos com gzip pelo `prepare_staticfiles`); a medição na
  escala-alvo continua pendente como registrado em
  `docs/homologation/performance.md`.
