---
avalia: PD-2026-11-15-02
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 2640f2c
commit_aqui:
roteiro_aqui:
---

# Ctrl+S sem foco acionava o primeiro formulário da página ("Trazer tudo")

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-02-ctrl-s-primeiro-formulario.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
Com a página recém-aberta e itens da consulta anterior pendentes, Ctrl+S submetia "Trazer tudo": copiava conduta e impressões antigas por cima e não salvava o texto. Com o foco no texto, Ctrl+S não fazia nada.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`static/clinical/atendimento.js:356` (`return raiz.querySelector('form');`) e `:362` (`form.querySelector('button[type="submit"]...`). Na tela estruturada o caminho da aba ativa vem antes — avaliar qual formulário é o primeiro em cada aba.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
