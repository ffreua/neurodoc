---
avalia: PD-2026-11-15-11
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: avaliar     # o que o ProntDoc viu ao ler este repositório em 2640f2c
commit_aqui:
roteiro_aqui:
---

# "Analisar de novo" devolvia a análise antiga depois de mudar hipótese, medicação ou exame

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-11-reanalise-devolve-a-antiga.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
Registrar uma hipótese ou incluir um exame e pedir nova análise devolvia a anterior com "o caso não mudou".

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`ai/services.py::create_job` com a mesma chave. No estruturado, achados do exame sobem a versão? Avaliar antes de corrigir.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
