---
avalia: PD-2026-11-15-11
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: avaliar     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §6
---

# "Analisar de novo" devolvia a análise antiga depois de mudar hipótese, medicação ou exame

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-11-reanalise-devolve-a-antiga.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
Registrar uma hipótese ou incluir um exame e pedir nova análise devolvia a anterior com "o caso não mudou".

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`ai/services.py::create_job` com a mesma chave. No estruturado, achados do exame sobem a versão? Avaliar antes de corrigir.

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado.** A chave era `tipo:atendimento:row_version`, e aqui também
hipóteses, medicações, exames e analitos não sobem a versão — nem os
**achados do exame estruturado**, que o ProntDoc não tem. `_assinatura_do_caso`
entra na chave com os cinco (contagem e última alteração) e as análises
recusadas. A porta da privacidade (`risco_confirmado`) continua achando o
pedido bloqueado, porque sem mudança a assinatura é a mesma.
