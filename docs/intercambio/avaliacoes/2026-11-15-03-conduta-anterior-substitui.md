---
avalia: PD-2026-11-15-03
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §1
---

# Trazer a conduta anterior substituía a conduta de hoje

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-03-conduta-anterior-substitui.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
O médico emite um pedido por modelo (a emissão acrescenta "[Pedido de exames · emitido …]" à conduta) e depois aceita a conduta da consulta anterior: a conduta de hoje some, com a menção ao documento emitido.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`clinical/carry_forward.py:219`, a mesma linha. Vale também para os campos do estruturado que são texto.

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado** — `clinical/carry_forward.py`, a mesma linha. Corrigido como
no ProntDoc (acrescenta quando o campo de hoje tem texto, não repete o mesmo
texto). Vale para todo campo de texto do estruturado que passa por ali.
