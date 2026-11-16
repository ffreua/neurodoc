---
avalia: PD-2026-11-15-12
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 2640f2c
commit_aqui:
roteiro_aqui:
---

# Apoio diagnóstico pedido em atendimento já finalizado

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-12-analise-em-atendimento-finalizado.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
Depois de finalizado, "Analisar de novo" rodava uma análise nova — que lia as conclusões do próprio médico e nada dela podia mais entrar no registro.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`clinical/views.py::DiagnosticSupportRequestView` sem a conferência.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
