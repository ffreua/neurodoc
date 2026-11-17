---
avalia: PD-2026-11-15-13
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: conferência dos 49 blobs contra o manifesto, feita à mão
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
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado, confirmado byte a byte:** 0 de 49 blobs batiam com o manifesto
(a cópia de trabalho do Windows, com CRLF, batia 49 de 49 — por isso nenhum
roteiro local acusou). Correção: `tiss/xsd/**/*.xsd -text` no
`.gitattributes` e os 49 regravados com os bytes oficiais; o índice do commit
confere 49 de 49. O `MANIFESTO.json` fica com o tratamento normal.

**Pode importar mais aqui do que o ProntDoc supôs:** a imagem de produção é
construída do clone da VPS (LF), e o TISS foi liberado para clínicas na 1.30.
Se a chave da instalação estiver ligada, a geração de lote está sendo recusada
em produção hoje. **A conferir na VPS** (não feito nesta avaliação, sem acesso):
os 49 hashes no clone depois do `git pull` e o estado de
`tiss.Configuracao.ativo`.
