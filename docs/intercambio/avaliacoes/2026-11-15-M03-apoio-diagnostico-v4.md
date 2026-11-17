---
avalia: PD-M-2026-11-15-03
data_do_registro: 2026-11-15
tipo: mudança
origem: prontdoc
conclusao: nao_adotar          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: avaliar     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: 
roteiro_aqui: 
---

# Apoio diagnóstico: o médico aceita ou recusa cada hipótese; prompt v4

**Registro original:** ProntDoc, `docs/intercambio/mudancas/2026-11-15-M03-apoio-diagnostico-v4.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
(ver o registro original)

## O que o ProntDoc leu neste repositório
O apoio diagnóstico do NeuroDoc é o mesmo módulo; lá o contexto também
leva achados do exame estruturado e escalas, que o prompt v4 não menciona.

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Não adotado agora; adotado só o pedaço que era defeito.** A regra do "%"
(PD-08) entrou. Aceitar/recusar por hipótese e o prompt v4 mudam o fluxo de
revisão e o esquema do artefato (`decisoes`, `origin`, `evidence_strength`),
e o contexto daqui leva achados do exame estruturado e escalas, que o v4 não
menciona. Reavaliar depois de o ProntDoc ter uso real com ele.
