---
avalia: PD-2026-11-15-05
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-provavel     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §7
---

# Atendimento finalizado com os campos abertos e oferecendo rascunho

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-05-finalizado-editavel.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
No finalizado, a caixa de texto aceitava digitação (o servidor recusava gravar) e a faixa oferecia "Restaurar" rascunhos antigos num registro imutável.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`clinical/views.py` sem `_formulario_da_tela`; o mesmo `atendimento.js`.

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado, nos dois tipos.** `_formulario_da_tela(classe, encounter)` põe
`readonly` no formulário do finalizado (livre e estruturado); o rascunho
local só é lido quando o atendimento é editável.
