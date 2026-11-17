---
avalia: PD-2026-11-15-02
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §9
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
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado, e pior na tela estruturada** — registrado aqui como
ND-2026-11-17-01. No texto livre, o mesmo do ProntDoc. No estruturado, o
`formularioAtivo` pegava o primeiro `<form>` da aba aberta: na aba História
é "Mudar para seguimento/primeira consulta" (trocava a estrutura do
atendimento), na de hipóteses é "Analisar o caso" (um pedido à IA), na de
medicações é incluir medicação em branco.

Correção: sem foco, o alvo é o formulário da aba que carrega `row_version`
(o salvamento do atendimento) ou `nd-atendimento-livre`; aba sem salvamento
próprio, Ctrl+S não faz nada. `botaoDe` acha o botão ligado por `form=`.
