---
id: ND-2026-11-17-01
data: 2026-11-17
origem: neurodoc
severidade: alta
categoria: perda-de-dado
sigiloso: nao
estado_aqui: corrigido
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py
no_outro: nao_afetado
---

# Ctrl+S na tela estruturada enviava o primeiro formulário da aba

## O que acontecia
Com o atendimento estruturado aberto e o foco fora de um campo (logo depois
de clicar numa aba, por exemplo), Ctrl+S não salvava o texto: enviava o
**primeiro formulário da aba aberta**. Na aba História era "Mudar para
seguimento" (ou "Mudar para primeira consulta") — o atendimento trocava de
estrutura; na de hipóteses, "Analisar o caso", um pedido à IA; na de
medicações, incluir medicação com os campos vazios (recusa). O texto
digitado ficava só no navegador.

## Causa
`static/clinical/atendimento.js::formularioAtivo` — sem foco, devolvia
`painel.querySelector('form')`, contando que o formulário de salvar fosse o
primeiro de cada aba. Deixou de ser quando a troca de estrutura (1.41) e o
apoio da IA entraram acima dele. Achado ao avaliar PD-2026-11-15-02.

## Correção aqui
Sem foco, o alvo é o formulário da aba que carrega `row_version` — o
salvamento do atendimento — e, no texto livre, `nd-atendimento-livre`. Aba
sem salvamento próprio (medicações, exames, adendos): Ctrl+S não faz nada.
O roteiro confere que o script não procura mais "o primeiro formulário".

## No outro sistema
ProntDoc só tem o texto livre, sem abas (`templates/clinical/detail_livre.html`
lido em `prontdoc/main` ef34a29): o caminho da aba nunca é tomado, e o
`return raiz.querySelector('form')` do fim já foi corrigido lá
(PD-2026-11-15-02). Se o ProntDoc um dia ganhar abas, o mesmo
`painel.querySelector('form')` (`static/clinical/atendimento.js:358`) volta a
valer.
