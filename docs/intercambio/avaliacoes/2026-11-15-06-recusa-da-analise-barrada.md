---
avalia: PD-2026-11-15-06
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §2
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
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado.** Aqui a recusa do apoio diagnóstico mora em `ai/jobs/<id>/`
(`ArtifactRejectView`), e `reject_artifact` passava pelo `_guard` com a
conferência de versão. Corrigido: `_guard(..., conferir_versao=False)` na
recusa; aprovar continua exigindo o prontuário inalterado. As views de
aceitar, recusar e pedir resumo devolvem aviso na tela em vez de
`HttpResponseForbidden(str(exc))`.

**Ficou de fora, de propósito:** as telas do relatório do paciente
(`RelatorioAprovarView`, texto vazio ou com marcador) ainda respondem 403
cru — o `check_relatorio_ia` cobra esse 403. Registrado como
ND-2026-11-17-03, aberto nos dois.
