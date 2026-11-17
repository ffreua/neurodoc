---
avalia: PD-2026-11-15-07
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §3
---

# O aviso do sino abria o apoio diagnóstico numa tela que o mostrava vazio

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-07-aviso-do-sino-apoio-vazio.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
"A IA terminou" levava a `ai/jobs/<id>/`, que mostrava "Resumo" vazio e "Hipóteses: nenhuma" — a tela foi escrita para o resumo do atendimento e lê `summary`/`qualitative_hypotheses`.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`ai/views.py::AIJobDetailView` sem o redirecionamento; `templates/ai/job_detail.html` igual. No NeuroDoc a âncora do cartão de hipóteses é a aba do estruturado — usar a certa para cada tipo.

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado.** `AIJobDetailView` agora redireciona o apoio diagnóstico
**concluído** para `#tab-hipoteses` do atendimento estruturado. Diferenças:
o texto livre do NeuroDoc não desenha o cartão de apoio, então ali a tela
genérica fica; e o job que **falhou** também fica nela, porque é ela que
mostra o diagnóstico da falha (`failure_diagnostics`).
