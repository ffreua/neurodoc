---
avalia: PD-2026-11-15-17
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-provavel     # o que o ProntDoc viu ao ler este repositório em 2640f2c
commit_aqui:
roteiro_aqui:
---

# `check_tiss_guias` falhava conforme o que tinha rodado antes

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-17-roteiro-guias-paciente-compartilhado.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
Na bateria completa o roteiro reprovou com `Receivable.DoesNotExist`, e
sozinho passou; uma hora depois falhou sozinho também.

## O que o ProntDoc leu neste repositório
O mesmo roteiro existe no NeuroDoc (`checks/check_tiss_guias.py`, escolha do
paciente por `order_by('created_at').first()`). A fragilidade é a mesma; só
aparece em base de demonstração já usada no dia.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
