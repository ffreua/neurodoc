---
avalia: PD-2026-11-15-07
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui:
roteiro_aqui:
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
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
