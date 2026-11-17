---
avalia: PD-2026-11-15-01
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-provavel     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §7–9
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
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado, e corrigido nos dois tipos de atendimento.** O mesmo
`atendimento.js` e o mesmo `_encounter_modals.html`. Aqui o defeito era
maior que no ProntDoc: na tela **estruturada** não havia "salvar antes" de
espécie nenhuma (o ouvinte saía cedo sem o formulário `nd-atendimento-livre`),
então finalizar com a conduta digitada e não salva selava a versão anterior.

Correção adaptada: `gravarAtendimento()` grava o texto pendente nos dois tipos
(no estruturado monta o envio com os campos que mudaram, como a emissão por
modelo já fazia); o ouvinte foi para o `document`; o formulário de finalizar
leva o atributo; o clique em "Finalizar" com mudança pendente grava e reabre
com `?finalizar=1` — e tira o parâmetro do endereço em seguida, para recarregar
não reabrir o modal (diferença em relação ao ProntDoc, que o deixa).
