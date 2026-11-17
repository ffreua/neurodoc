---
avalia: PD-2026-11-15-12
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §7
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
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado.** `DiagnosticSupportRequestView` recusa no finalizado, e o botão
"Analisar de novo" some; a última análise fica para leitura.
