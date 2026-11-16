---
avalia: PD-2026-11-15-01
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-provavel     # o que o ProntDoc viu ao ler este repositório em 2640f2c
commit_aqui:
roteiro_aqui:
---

# Finalizar selava a última versão salva e perdia o que foi digitado depois

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-01-finalizar-perde-texto.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
O médico digita, o salvamento automático ainda não gravou, clica "Finalizar atendimento" e confirma. O atendimento é finalizado com a versão anterior, o `content_hash` sela essa versão, e o texto novo fica só no navegador — sem como gravar, porque o registro já é imutável. O modal ainda dizia "falta preencher" com o texto digitado na tela.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

Mesmo `atendimento.js` (ouvintes em `raiz.addEventListener('submit'` — três ocorrências) e o mesmo `_encounter_modals.html` sem o atributo. Vale para a tela de texto livre; na estruturada, conferir se o botão Finalizar abre o mesmo modal.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
