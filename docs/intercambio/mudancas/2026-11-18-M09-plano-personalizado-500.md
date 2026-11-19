---
id: MD-2026-11-18-06
data: 2026-11-18
origem: sessao-unica
tipo: defeito
sigiloso: nao
estado_aqui: corrigido e verificado no ambiente local
roteiro_aqui: checks/check_renovacao.py
no_outro: feito na mesma rodada — PD-M-2026-11-18-07
---

# Plano e renovação dava 500 para o plano Personalizado

**Sintoma.** Organização → Plano e renovação (`/app/org/plano/`) respondia
500 para a clínica no plano Personalizado sem período (a do titular, nos
dois sistemas).

**Causa.** Desde a renovação pelo sistema (NeuroDoc 1.47; ProntDoc a
partir da derivação), `PlanoView._contexto` montava o `RenovarForm` para
qualquer plano. O formulário calcula o preço de cada período, e
`preco_na_periodicidade` devolve `None` para o Personalizado (sem preço de
tabela): `TypeError` antes de a página sair. O Gratuito não quebrava
(preço zero). O botão Renovar nunca aparece para esses planos
(`renovacao_disponivel` exige plano de tabela), e o `post` já recusava.

**Correção.** O formulário só é montado quando `plano_contratavel(plano)`.
Nada muda para plano de tabela.

**Roteiro.** `check_renovacao`, seção 7: Personalizado e Gratuito abrem a
página com 200 e sem o campo do período. Antes da correção, o mesmo
formulário levanta o `TypeError` do log de produção (conferido no shell).
