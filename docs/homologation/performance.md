# Homologação — Desempenho e índices (S14)

## Medição realizada

Máquina: ambiente de desenvolvimento local (Docker Desktop, Windows),
**não** o hardware de produção proposto (8 vCPU/16 GiB, ver
`docs/operations/environment.md`). Dados: o conjunto sintético de
`seed_demo` (poucos pacientes/atendimentos, não os 50 mil pacientes/500 mil
atendimentos de RNF-01.01). Um único usuário sequencial via
`django.test.Client` (medição em processo, sem a rede real) — **não** 20
usuários concorrentes.

| Página | p50 | p95 (5 amostras) |
| --- | --- | --- |
| Painel de indicadores (`reporting:dashboard`) | 36,8 ms | 125,2 ms |
| Painel de CRM (`crm:board`) | 13,2 ms | 20,5 ms |
| Visão financeira (`finance:overview`) | 10,1 ms | 12,5 ms |
| Lista de sessões de chat (`ai:chat-list`) | 7,9 ms | 18,1 ms |

Contagem de consultas SQL do painel de indicadores (o mais pesado, soma
~10 seletores diferentes): 22 consultas por carga de página.

## Revisão de índices

Tabelas de maior tráfego (`clinical_encounter`, `patients_patient`,
`scheduling_appointment`) já têm índice composto dedicado desde a sprint
que as criou (`clinical_encounter_lookup_idx` em
`(tenant,patient,occurred_at)`, `patients_patient_name_idx`,
`patients_obs_lookup_idx`), além do índice automático do Django em toda
FK. Nenhum gargalo novo foi identificado nesta revisão que justificasse
uma migration adicional agora.

## Decisões de escopo

- **Estes números não validam RNF-01.01** (p95 até 800 ms com 20 usuários
  concorrentes e 50 mil pacientes/500 mil atendimentos sintéticos) — essa
  escala exigiria gerar um volume de dados sintéticos e uma ferramenta de
  carga (k6/Locust) que não foram montadas nesta execução. O que esta
  medição demonstra: a aplicação não é patologicamente lenta na escala
  atual (ordem de dezenas de milissegundos, não segundos), o que é uma
  base razoável, mas a meta formal de RNF-01.01 permanece **medição
  pendente**, exatamente como o próprio requisito já registra
  ("medição pendente").
- `reporting.patients.returning_patients_count` faz uma consulta por
  atendimento no período (documentado como limitação desde
  `docs/homologation/reports-capture.md`, S13) — o candidato mais provável
  a gargalo real numa base de 500 mil atendimentos; uma versão agregada
  em uma única consulta é a otimização recomendada antes de medir contra
  o volume alvo.
- RNF-01.02 (busca/autocomplete), RNF-01.03 (autosave) e RNF-01.04 (fila)
  não foram remedidos nesta sprint especificamente — o autosave já foi
  testado funcionalmente em S05 (conflito de versão); uma medição de
  latência formal desses três fica pendente junto com RNF-01.01, sob a
  mesma limitação de escala/ferramenta de carga.
