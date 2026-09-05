# Design system — inventário de tokens e componentes

P-01 estava aberta na elaboração do PRD porque `design_system/design-system.html`
não havia sido fornecido. O arquivo já está disponível no repositório — este
documento cataloga o que foi efetivamente inspecionado nele e nos assets em
`design_system/refs/duralux/`, sem inventar identidade visual. Qualquer
divergência entre este inventário e o arquivo real deve ser corrigida aqui, não
no código de aplicação.

**Origem:** `design_system/design-system.html` (1618 linhas), "Duralux — Living
Design System & Pattern Library", que referencia:

- `design_system/refs/duralux/assets/8e9772f3f995c787_css2.css` — fonte Google (Inter).
- `design_system/refs/duralux/assets/f1bb68a482b802d8_index-D1a-T4mr.css` — folha de
  estilo principal (Bootstrap 5.3 + tokens/componentes Duralux).
- Ícones inline SVG no padrão Feather Icons (`stroke="currentColor"`, `stroke-width="2"`).

O documento HTML está organizado em 9 seções vivas (âncoras `#section-0` a
`#section-9`): Shell, Tipografia, Cores & Estados, Navegação, Formulários,
Tabelas & Dados, Componentes UI, Layout & Grids, Motion e Ícones.

## 1. Tipografia

Fonte primária: `'Inter', sans-serif`. Fonte monospace do sistema
(`--bs-font-monospace: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace`)
para dados tabulares/códigos.

| Papel | Classes | Tamanho / Line-height / Peso |
| --- | --- | --- |
| Page Title (H5) | `h5, .page-header-title h5` | 20px / 28px / 600 |
| Section Heading (H4) | `h4, .fw-bold` | 24px / 32px / 700 |
| Display Metric (H3 / FS-4) | `.fs-4, .fw-bold, .text-dark` | 28px / 34px / 700 |
| Card Title | `.card-title, .fs-16, .fw-semibold` | 16px / 24px / 600 |
| Subtitle / Section Sub | `.fs-13, .text-muted` | 13px / 18px / 400 |
| Table Header | `th, .fs-12, .fw-semibold, .text-muted` | 12px / 16px / 600 |
| Body Text (Regular) | `body, p, .text-body, .fs-14` | 14px / 21px / 400 |
| Body Text Small | `.fs-12, .text-muted` | 12px / 16px / 400 |
| Form Label | `.form-label, .fw-semibold` | 13px / 18px / 600 |
| Caption / Helper Text | `.fs-11, .text-muted, .form-text` | 11px / 15px / 400 |
| Truncated Text | `.text-truncate` | 13px / 18px, ellipsis |
| Monospace / Code Data | `code, .font-monospace, .fs-12` | 12px / 16px, mono |

## 2. Cores, superfícies e estados semânticos

### 2.1 Cores de interface

| Papel | Hex | Classe |
| --- | --- | --- |
| Body Background | `#F0F2F8` | `.bg-body` |
| Card / Panel Surface | `#FFFFFF` | `.card, .bg-white` |
| Primary Brand | `#3454D1` | `.bg-primary` |
| Dark / Sidebar Skin | `#283C50` | `.bg-dark` |
| Gray Neutral / Soft | `#E9ECEF` | `.bg-gray-200` |
| Darken Accent | `#001327` | `.bg-darken` |

Confirmado também na folha de estilo (`--bs-*` custom properties do Bootstrap
customizado): `--bs-body-bg: #f0f2f8`, `--bs-body-color: #4b5563`,
`--bs-border-color: #e5e7eb`.

### 2.2 Cores semânticas de estado

| Estado | Hex | Uso documentado |
| --- | --- | --- |
| Success | `#17C666` | `.badge.bg-soft-success`, `.alert-success`, `.btn-success` / `.btn-light-success` |
| Warning | `#FFA21D` | idem, variante warning |
| Danger / Error | `#EA4D4D` | idem, variante danger |
| Info | `#3DC7BE` | idem, variante info |
| Secondary | `#64748B` | `--bs-secondary` |

Cada estado tem três formas de uso: badge sólido, badge soft (`bg-soft-*` +
`text-*`) e botão (`btn-*` sólido e `btn-light-*` soft). Não usar apenas cor
para indicar estado — sempre acompanhar de ícone e/ou texto (ver seção 16 do
PRD, requisito de acessibilidade WCAG 2.2 AA).

### 2.3 Superfícies, bordas e elevação

| Elemento | Especificação | Classe |
| --- | --- | --- |
| Default Border | `1px solid #E5E7EB` | `.border, .rounded-3` |
| Dashed Border | Dropzone/upload | `.border.border-dashed` |
| Card/Dropdown Shadow | `0 0.125rem 0.25rem rgba(0,0,0,.075)` | `.shadow-sm, .card` |
| Modal Elevation Shadow | `0 0.5rem 1rem rgba(0,0,0,.15)` | `.shadow, .modal-content` |

Raios de borda (Bootstrap customizado): `--bs-border-radius: 4px` (padrão),
`--bs-border-radius-sm: 2px`, `--bs-border-radius-lg: 6px`,
`--bs-border-radius-xl: 1rem`, `--bs-border-radius-2xl: 2rem`,
`--bs-border-radius-pill: 50rem`.

## 3. Navegação e estrutura

- Menu lateral (`nxl-navigation` / `nxl-navbar`) com item ativo em
  `bg-primary text-white`, item padrão em `text-gray-400`, submenu expansível
  (`nxl-hasmenu`/`nxl-trigger`) com itens em `text-gray-400`/`text-primary`.
- Breadcrumbs (`.breadcrumb`) com item ativo via `aria-current="page"`.
- Abas: `.nav.nav-tabs` (incluindo estado `disabled`) e `.nav.nav-pills`.
- Paginação: `.pagination.pagination-common-style`, com variante `.pagination-sm`.

## 4. Formulários

Estados documentados lado a lado para todo input: **default**, **filled**,
**error/invalid** (`.is-invalid` + `.invalid-feedback`), **disabled**,
**read-only**. Tamanhos: `.form-control-sm`, padrão, `.form-control-lg`.
Componentes: `.form-select`, `textarea.form-control`, `.form-check`
(checkbox/radio, incl. `disabled`), `.form-check.form-switch` (toggle).
Padrão de formulário completo (`4.7`) usa `row g-3` com `col-md-6`/`col-md-4`,
asterisco `text-danger` para obrigatórios, e barra de ação final
(`btn-light-secondary` "Cancelar" + `btn-primary` "Salvar").

## 5. Tabelas e exibição de dados

- Cards de KPI (`short-info-card`): ícone em `avatar-text avatar-lg
  bg-gray-200`, valor em `.fs-4.fw-bold`, rótulo em `.fs-13.text-muted`,
  variação em badge soft (verde alta, vermelho queda), barra `.progress` com
  cor correspondente ao KPI.
- Tabela de dados (`.table.table-hover.align-middle`): cabeçalho
  `bg-gray-100`, avatar/iniciais do usuário na primeira coluna, badges de
  status (`bg-soft-success/warning/danger`), barra de progresso por linha,
  ações em `btn-icon btn-sm btn-light` (editar) e `... text-danger` (excluir).
  Rodapé com contagem de registros + paginação `pagination-sm`.
- Container de gráfico: título + subtítulo, seletor de período
  (`btn-group btn-group-sm`), legenda por cor (badge circular + rótulo),
  placeholder de canvas (ApexCharts).

## 6. Componentes de UI

- **Botões**: variantes sólidas (`btn-primary` … `btn-light`), soft
  (`btn-light-primary` … `btn-light-dark`), outline (`btn-outline-*`);
  estados `active`/`disabled`/loading (`spinner-border-sm` + texto);
  tamanhos `btn-sm`/`btn-md`/`btn-lg`/`btn-icon`.
- **Badges/tags**: sólidos (`badge bg-*`) e soft (`badge bg-soft-* text-*`),
  com ou sem ícone inline.
- **Avatares**: `avatar-text` em tamanhos `avatar-xs` a `avatar-xl` (iniciais
  sobre cor sólida ou soft) e `avatar-image` (foto circular, ex. 44px).
- **Alertas**: `alert alert-primary/success/danger` com ícone + texto em
  negrito para o rótulo do estado.
- **Loading/skeleton**: `spinner-border`/`spinner-grow` por cor semântica;
  skeleton via `.placeholder-glow` (estático) e `.placeholder-wave` (onda).

## 7. Layout e espaçamento

Três padrões de layout reais documentados:

1. **Dashboard**: KPIs em linha de 4 colunas, gráfico principal (`col-8`) +
   feed lateral (`col-4`), tabela de transações recentes (`col-12`).
2. **Listagem**: cabeçalho + breadcrumbs, barra de busca/filtros + exportação,
   `.table-responsive`, barra de paginação.
3. **Formulário/edição**: título + badge de status, campos em grid (`col-6`
   duplo + largura total), barra de ação final alinhada à direita.

Grid Bootstrap padrão de 12 colunas; gutters `g-0` a `g-5` (`.25rem` a `3rem`).

## 8. Motion e interação

| Interação | Especificação |
| --- | --- |
| Sidebar toggle | `transition: all 0.3s ease-in-out` |
| Progress animado | `.progress-bar-striped.progress-bar-animated` |
| Spinner | `@keyframes spin` (`.spinner-border`) |
| Skeleton em onda | `.placeholder-wave` |

Regra geral (seção 16 do PRD): streaming de chat não deve roubar foco;
Markdown malicioso não pode executar script.

## 9. Ícones

Feather Icons via SVG inline, `stroke="currentColor"`, `stroke-width="2"`,
tamanhos típicos 12–20px. Categorias inventariadas: navegação (dashboard,
reports, users, settings, mail), ações (add, edit, delete, filter, search),
status/métricas (check, x-circle, trending up/down, dollar sign).

## Regras de interação por área (seção 16 do PRD)

| Área | Especificação de interação | Critério manual |
| --- | --- | --- |
| Menu | Itens por permissão; clínica ativa sempre visível | Usuário não confunde tenants e não descobre conteúdo proibido via contadores |
| Formulários | Label persistente, máscara não destrutiva, erro no campo e resumo no topo | Cadastro completo por teclado |
| Exame | Seções progressivas, lado explícito, alternativas mutuamente exclusivas | Não há normalidade automática ou valores invisíveis |
| Agenda | Semana/dia no desktop; lista e dia no celular; não depender só de drag-and-drop | Agendar/remarcar por botão e teclado |
| Jobs | Loading local no botão, status acessível e notificação persistente | Navegação permanece disponível |
| Documentos | Revisão de paciente/emissor/conteúdo/destinatário antes de assinar | Nenhuma emissão por clique acidental em ação administrativa |
| Gráficos | Título, unidade, período, legenda e tabela alternativa | Informação compreensível sem depender apenas de cor |
| Chat | Streaming sem roubar foco, anúncio de conclusão e cancelamento | Markdown malicioso não executa script |

Convenções obrigatórias: datas `DD/MM/AAAA`, valores monetários em `R$`, fuso
`America/Sao_Paulo`. Código e schemas continuam em inglês. Novas telas devem
reutilizar estes tokens e componentes — não introduzir uma paleta ou
biblioteca de componentes paralela.

## Próximos passos (fora do escopo de S01)

- S03 converte os componentes acima em templates Django reutilizáveis
  (`templates/`, `static/`) conforme as telas de cada app de domínio forem
  implementadas.
- S14-T02 revisa a aderência visual final de todas as jornadas contra este
  inventário.
