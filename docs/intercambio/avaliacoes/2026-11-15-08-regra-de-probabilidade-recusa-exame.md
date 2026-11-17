---
avalia: PD-2026-11-15-08
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui:
roteiro_aqui:
---

# A regra contra probabilidade numérica descartava análises com valor de exame em %

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-08-regra-de-probabilidade-recusa-exame.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
"HbA1c acima de 6,5%" ou "saturação 92%" em qualquer campo validado fazia a análise inteira ser descartada como "probabilidade numérica".

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`ai/schemas.py:30`, a mesma expressão. Afeta resumo e apoio diagnóstico.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
