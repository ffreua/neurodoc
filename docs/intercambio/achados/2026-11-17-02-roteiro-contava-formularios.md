---
id: ND-2026-11-17-02
data: 2026-11-17
origem: neurodoc
severidade: baixa
categoria: teste
sigiloso: nao
estado_aqui: corrigido
commit_aqui: b26c256
roteiro_aqui: checks/check_texto_livre.py, checks/check_intercambio_prontdoc.py
no_outro: afetado-confirmado
---

# O roteiro contava os formulários que salvam antes, em vez de conferir cada um

## O que acontecia
`check_texto_livre` §3 contava quantas vezes `data-nd-save-encounter-before-submit`
aparece na tela e comparava com um número. Um formulário novo **sem** o
atributo passava, desde que outro o tivesse — foi assim que exame, analito,
consulta anterior e apoio da IA ficaram sem salvar antes (PD-2026-11-15-04)
sem nenhum roteiro reprovar.

## Causa
A regra era "quantos", e o defeito é "qual".

## Correção aqui
O roteiro lê cada `<form>` da tela cujo destino é `/app/clinical/` e reprova o
que não salva antes, com três isenções declaradas: o próprio salvamento, o
adendo (só existe no finalizado) e o descarte. `check_intercambio_prontdoc`
§8 faz o mesmo nos **dois** tipos de atendimento.

## No outro sistema
ProntDoc, `checks/check_texto_livre.py:280` (`prontdoc/main` ef34a29): passou
de `!=` para `<` na contagem — continua contando. Vale trocar pela conferência
por formulário.
