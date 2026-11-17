---
avalia: PD-2026-11-15-08
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §4
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
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado** — `ai/schemas.py`, a mesma expressão. Corrigida igual ao
ProntDoc (percentual só é recusado junto de palavra de probabilidade), sem
trazer o resto da mudança do esquema (v4, ver PD-M-03). Dez casos no
roteiro.
