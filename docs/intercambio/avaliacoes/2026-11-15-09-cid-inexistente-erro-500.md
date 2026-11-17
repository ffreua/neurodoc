---
avalia: PD-2026-11-15-09
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §5
---

# Hipótese com identificador de CID inexistente dava erro 500

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-09-cid-inexistente-erro-500.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
`diagnosis_code_id` vem de campo oculto; um id que não está no catálogo (forjado ou de carga trocada) gerava `IntegrityError`.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`clinical/forms.py` sem a conferência.

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado.** `DiagnosisForm.clean` zera o id que não está no catálogo; a
hipótese entra pelo código e pela descrição digitados.
