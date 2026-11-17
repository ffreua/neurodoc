---
avalia: PD-2026-11-15-06
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui:
roteiro_aqui:
---

# Recusar a análise da IA era barrado e caía numa página branca

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-06-recusa-da-analise-barrada.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
O médico recusa o apoio diagnóstico e recebe uma página em branco: "O prontuário mudou depois que este rascunho foi gerado". A análise continua na tela. Achado do titular, no celular.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`ai/review.py` (`reject_artifact` chama `_guard`) e `ai/views.py` (sete `return HttpResponseForbidden(str(exc))`).

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
