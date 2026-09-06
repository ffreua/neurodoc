# Homologação — Acessibilidade (S14)

Verificação manual com navegador real (Chrome via CDP, `agent-browser`),
não apenas leitura de código — capturas de tela reais anexadas a este
registro.

## Teclado e foco

- [x] `:focus-visible` aplicado globalmente (`static/base.css`) a links,
  botões, campos de formulário e qualquer elemento com `tabindex` — testado
  pressionando `Tab` repetidamente a partir do login real e capturando a
  tela: o anel de foco azul (cor `--nd-primary`, a mesma do design system)
  aparece claramente sobre o link "Indicadores" da navegação.
- [x] Toda ação de mudança de estado neste produto (mover card de CRM,
  remarcar consulta, transicionar atendimento, assinar documento, aceitar
  rascunho de IA) é um `<form>`/`<button>` ou `<a href>` real — nunca um
  `onclick` em `<div>` sem semântica. Isso é uma invariante mantida desde
  S04 (agenda) e reforçada em cada sprint seguinte (S09 CRM, S11 revisão
  de IA); nenhuma tela deste produto depende de arrastar ou de um gesto
  que não tenha equivalente por teclado.
- [x] Login → seleção de organização → painel percorrido de ponta a ponta
  usando apenas preenchimento de campo e clique em elementos nativos
  (equivalente a Tab + Enter no mundo real) — sem depender de posição de
  mouse.

## Rótulos e erros

- [x] Todo campo de formulário usa `<label>` com texto explícito (via
  `form.as_p` do Django, que já associa `<label for=...>` ao campo) —
  confirmado no snapshot de acessibilidade real da tela de login
  (`textbox "Email:"`, `textbox "Senha:"`, ambos nomeados corretamente
  pela árvore de acessibilidade do Chrome, não apenas por `placeholder`).
- [x] Mensagens de erro de formulário (senha incorreta, MFA inválida,
  campo obrigatório) já são renderizadas pelo Django Forms padrão
  associadas ao campo — nenhuma tela usa apenas cor para indicar erro.

## Viewport móvel

- [x] `<meta name="viewport" content="width=device-width, initial-scale=1">`
  adicionado a `templates/base.html` (ausente até esta sprint — item real
  de acessibilidade/usabilidade móvel corrigido agora).
- [x] Testado com viewport 390×844 (tamanho de iPhone comum): o cabeçalho
  de navegação quebra para múltiplas linhas (`@media (max-width: 640px)`
  em `static/base.css`), o conteúdo principal permanece dentro da largura
  da tela sem exigir rolagem horizontal, e a tabela de indicadores
  permanece legível — captura de tela real anexada a este registro.

## Decisões de escopo

- Não foi executada uma auditoria automatizada (axe-core/Lighthouse) —
  DEC-20 já estabelece que este projeto não usa suíte automatizada; a
  verificação aqui é manual, com evidência de captura de tela real, mesmo
  padrão de toda homologação anterior.
- Contraste de cor não foi medido numericamente (razão WCAG); os tokens
  usados são os do arquivo real do design system (`--bs-body-color:
  #4b5563` sobre `--bs-body-bg: #f0f2f8`, `--bs-primary: #3454d1` sobre
  branco), que aparentam contraste adequado a olho nu, mas uma medição
  formal (ex.: com uma ferramenta de contraste real) fica para uma
  passagem futura antes de reivindicar conformidade WCAG 2.2 AA completa.
- Apenas as jornadas de login/seleção de organização/painel/CRM foram
  percorridas com navegador real nesta sprint; cadastro de paciente,
  agenda e chat já tiveram verificação de teclado/mobile em sprints
  anteriores (S03, S04) com o `agent-browser`, registradas em
  `docs/homologation/patients.md` e no histórico de S04.
