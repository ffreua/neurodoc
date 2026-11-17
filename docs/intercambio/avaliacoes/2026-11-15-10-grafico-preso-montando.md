---
avalia: PD-2026-11-15-10
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: 
---

# Gráfico de evolução preso em "Montando o gráfico…" depois da primeira série

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-10-grafico-preso-montando.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
Trocar de série com a resposta perdida deixava o modal esperando para sempre.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`static/clinical/evolucao.js:24`, igual.

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado** — `static/clinical/evolucao.js`, idêntico. Corrigido igual
(`carregado = false` a cada série). Sem roteiro: é comportamento de
navegador.
