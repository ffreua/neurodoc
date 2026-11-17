---
id: ND-2026-11-17-03
data: 2026-11-17
origem: neurodoc
severidade: baixa
categoria: tela
sigiloso: nao
estado_aqui: aberto
commit_aqui:
roteiro_aqui: checks/check_relatorio_ia.py (cobra o 403 de hoje)
no_outro: afetado-confirmado
---

# O relatório da IA ainda recusa com página em branco

## O que acontecia
Na tela do relatório do paciente, aprovar com o texto vazio, com um marcador
de desidentificação colado, com o prontuário alterado depois ou sem CRM no
perfil devolve uma página em branco com a frase solta (403) — o mesmo defeito
de tela que PD-2026-11-15-06 corrigiu na recusa do apoio diagnóstico. O médico
perde o texto que editou na caixa.

## Causa
`ai/views.py::RelatorioAprovarView`, `RelatorioRequestView` e
`RelatorioRejeitarView` devolvem `HttpResponseForbidden(...)`.

## Correção aqui
**Aberto, de propósito nesta rodada.** `check_relatorio_ia` §6 cobra o 403
como comportamento; mudar para aviso na tela pede rever o roteiro e devolver
o formulário com o texto editado (senão a recusa apaga a edição). Fica para a
próxima rodada do intercâmbio.

## No outro sistema
ProntDoc, `ai/views.py:252, 328, 373, 375, 426` (`prontdoc/main` ef34a29): o
mesmo código.
