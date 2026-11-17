---
avalia: PD-2026-11-15-15
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-confirmado     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui:
roteiro_aqui:
---

# O procedimento de troca da chave da Asaas não funciona como escrito

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-15-troca-da-chave-asaas.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
`docker service update --secret-rm ... celery_worker` é desfeito pelo Swarm (o worker não sobe sem o segredo), e `docker secret rm` falha com "in use".

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

`docs/operations/asaas.md:29`, o mesmo passo.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
