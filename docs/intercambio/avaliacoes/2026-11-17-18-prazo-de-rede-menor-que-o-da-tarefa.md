---
avalia: PD-2026-11-17-18
data_do_registro: 2026-11-17
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-provavel     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: 3858ce4
roteiro_aqui: checks/check_intercambio_prontdoc.py §11
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
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado, e corrigido sem esperar a D-3.** `REQUEST_TIMEOUT_SECONDS = 60`
em `ai/providers/__init__.py` cortava toda tarefa aos 60 s; aqui o relatório
do paciente (240 s) é o mais exposto. Agora `get_chat_model` e
`installation_reserve_model` aceitam `timeout`, e `services.run_job` passa o
prazo da tarefa mais 15 s — quem decide desistir é
`graphs._invoke_with_timeout`, como o texto da falha já dizia. O chat, que
transmite e não tem prazo de tarefa, continua com os 60 s.
