---
avalia: PD-2026-11-15-16
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §10
---

# Promessas da página de vendas que o código não cumpre

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-16-promessas-da-vitrine.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
"Trilha de quem viu o quê" (a trilha registra escrita e emissão, não leitura); "atestado" e "declaração de comparecimento" assinados (não há tipo atestado; a declaração é impressa); "a chave do backup é do responsável pela clínica" (é da mantenedora).

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`base/content.py:247` ("quem viu o quê"), `:249`, `:293` e `:426` (atestado).

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado, em parte.** Corrigido aqui: "a trilha de quem viu o quê" (a trilha
do NeuroDoc registra alteração e emissão, não leitura); "atestado" e
"declaração de comparecimento" assinados (não há tipo atestado; a declaração
é impressa) — na vitrine, no FAQ e na descrição de `/verificar/`; "a chave de
recuperação é do responsável pela clínica" (é da mantenedora); "o exame
realizado vira cobrança e guia" (só com honorário do procedimento); e o
rebaixamento que "apenas deixa de aceitar cadastro novo" (desde a 1.47 o
vencimento leva ao Gratuito com a regra dos médicos).
