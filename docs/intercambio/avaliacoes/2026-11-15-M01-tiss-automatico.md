---
avalia: PD-M-2026-11-15-01
data_do_registro: 2026-11-15
tipo: mudança
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: avaliar     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui:
roteiro_aqui:
---

# TISS e agenda de exames ligados automaticamente com o plano contratado

**Registro original:** ProntDoc, `docs/intercambio/mudancas/2026-11-15-M01-tiss-automatico.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
O TISS tinha **três chaves**: o plano (Completo e Personalizado), a
liberação da clínica no console (`Tenant.tiss_liberado`, nascia `False`) e a
chave da instalação (`tiss.Configuracao.ativo`). A clínica que pagava o
Completo via o TISS anunciado e não o achava no menu até alguém do suporte
liberar no console. A agenda de exames vem no mesmo contrato e ficava
escondida junto.

## O que o ProntDoc leu neste repositório
O código é o mesmo (`tenancy/services.py`, `ops/superadmin.py`). Lá o TISS
está desligado na instalação e há um defeito anterior a resolver antes de
ligá-lo (PD-2026-11-15-13, os XSD com o hash errado). A decisão comercial é
de cada produto: este registro diz o que o ProntDoc fez, não o que o
NeuroDoc deve fazer.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
