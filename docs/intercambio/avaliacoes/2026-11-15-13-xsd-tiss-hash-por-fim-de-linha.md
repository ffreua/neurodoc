---
avalia: PD-2026-11-15-13
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui:
roteiro_aqui:
---

# Os pacotes XSD da TISS não batem com o manifesto SHA-256 no repositório

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-13-xsd-tiss-hash-por-fim-de-linha.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
`tiss/versoes.py` confere cada XSD pelo SHA-256 do `MANIFESTO.json` e recusa o que não bate: num checkout Linux, **todo** XML de lote seria recusado ao ligar o TISS.

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

**Verificado**: no NeuroDoc, 0 de 49 blobs batem com o manifesto. O TISS está desligado em produção lá, por isso não apareceu. Corrigir antes de ligar.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
