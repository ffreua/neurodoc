---
avalia: PD-2026-11-17-18
data_do_registro: 2026-11-17
tipo: achado
origem: prontdoc
conclusao: pendente          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-provavel     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui:
roteiro_aqui:
---

# O prazo de rede (60 s) corta antes do prazo da tarefa de IA (75 s)

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-17-18-prazo-de-rede-menor-que-o-da-tarefa.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
Medindo modelos maiores para o apoio diagnóstico, a chamada caía com
`OpenAITimeoutError` aos 60 s, enquanto a tarefa anunciava (e o médico lê)
"não respondeu em 75s". O prazo da tarefa nunca é o que vale.

## O que o ProntDoc leu neste repositório
Mesmo código herdado; lá o relatório da IA (240 s) seria o primeiro a sentir.

## Conclusão do NeuroDoc
_Pendente._ Quem avaliar troca `conclusao`, explica aqui o porquê (muitas
vezes é uma das diferenças do README) e, se corrigir ou adotar, registra
commit e roteiro.
