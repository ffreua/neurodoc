# Homologação — Relatórios e registro histórico da captura retirada (S13)

> **Documento histórico.** A parte de relatórios continua vigente. A captura
> local descrita na homologação original foi integralmente retirada em
> 29/09/2026 pela DEC-53: agente, serviços, rotas, telas e artigo de ajuda não
> existem mais. Anexos digitalizados entram somente por upload manual. Os
> modelos antigos permanecem sem uso e somente leitura para preservar a
> proveniência de instalações que possam ter registros anteriores.

As evidências de relatórios foram coletadas via scripts de verificação
(`python manage.py shell`) com totais sintéticos conhecidos e via
`django.test.Client` contra as views reais.

## H-15 — Relatórios

- [x] **Numeradores/denominadores da seção 13 conferidos com totais
  conhecidos**: criados 2 pacientes com datas de atendimento controladas —
  `patients_seen` contou corretamente ambos no período; `new_patients_count`
  identificou a primeira consulta de cada um caindo na janela;
  `returning_patients_count` identificou exatamente 1 retorno (a segunda
  consulta do primeiro paciente). `no_show_rate` com 3 `completed` e 1
  `no_show` sintéticos retornou `n=4`, `rate=0.25` — exatamente
  `no_show/(completed+no_show)`, com `n` sempre disponível ao lado da taxa.
- [x] **Financeiro com valores conhecidos**: uma tabela de preço de
  R$400,00 (repasse R$320,00) aplicada a um atendimento finalizado gerou
  um `Receivable` com `charged_amount=400.00`; `revenue_by_competence`
  (por `competence_date`), `cash_received` (por `paid_at`, após registrar
  o pagamento) e `doctor_share_forecast` (do snapshot congelado) bateram
  com os valores esperados — cada um usando sua própria data de
  referência, nunca confundidas.
- [x] **Células pequenas agregadas**: uma distribuição sintética com uma
  célula de 2 e uma de 1 (abaixo do limiar de 5) foi corretamente
  agregada em "Outros" preservando a soma total (13 = 10+2+1) — a única
  célula grande (10) permaneceu visível individualmente.
- [x] **CSV protegido contra fórmula**: um valor começando com `=` e outro
  com `+` (vetores clássicos de CSV injection, ex. `=cmd|"/c calc"`)
  saíram do exportador com um apóstrofo prefixado — qualquer planilha
  trata isso como texto literal, nunca como fórmula executável; um valor
  normal (`Normal Name`) permaneceu intacto.
- [x] **Exportação síncrona vs. assíncrona**: uma exportação pequena
  (3 linhas) ficou `ready` imediatamente, com o CSV real gravado em
  armazenamento privado por tenant (`/data/media/<tenant>/reports/`,
  mesmo padrão de anexos) e conteúdo conferido linha a linha.
- [x] **Expiração em 24h**: `expires_at` retroagido manualmente e a
  varredura de expiração (`reporting.tasks.expire_exports`, agendada a
  cada 5 min) removeu o arquivo físico e marcou o registro `expired` —
  confirmado que o arquivo realmente não existe mais em disco depois.
- [x] **Isolamento por tenant**: uma exportação da Clínica A não é
  acessível pela Clínica B (404), mesmo tendo o UUID exato do registro.

## H-16 — Inferência elegível

- [x] `ReportDefinition.is_eligible_for_inference()` exige status
  `approved`, um `approved_by` real e todos os campos obrigatórios
  (pergunta, população, desfecho, unidade de análise, método,
  pressupostos) preenchidos — a ausência de qualquer um deles impede o
  relatório de ser considerado elegível; não existe nenhum botão de
  "calcular significância" genérico em lugar nenhum do produto.

## H-11 — Captura local (encerrado)

- [x] Agente, serviços, rotas autenticadas/públicas, templates e recurso de
  ajuda foram removidos.
- [x] Menu e navegação não oferecem pareamento nem captura.
- [x] `/capture/...`, `/app/integrations/capture/...` e `/ajuda/scanner/`
  não são superfícies ativas.
- [x] O upload manual de anexos continua passando pela quarentena,
  validação de MIME e verificação antimalware já homologadas em H-10.
- [x] `checks/check_captura_removida.py` protege esse contrato.

## Decisões de escopo

- **P-08 foi encerrada, não adiada.** Hardware e software de digitalização
  ficam fora do perímetro do produto. A clínica digitaliza externamente e
  envia o arquivo pronto por Anexos; não existe plano ativo de reativar o
  agente antigo.
- `active_patients_count` reflete o status **atual** do paciente
  (`PatientStatus.ACTIVE`), não uma reconstrução histórica exata "na data
  de corte" — o status não é versionado ao longo do tempo neste modelo;
  documentado como limitação, não escondido.
- `returning_patients_count` faz uma consulta por atendimento no período
  (não otimizada para grandes volumes) — aceitável para o volume de dados
  sintéticos desta homologação; uma versão com uma única consulta agregada
  pode substituir a implementação sem mudar a assinatura pública, se o
  volume real exigir.
- O registro de `ReportDefinition` (S13-T06) foi modelado e testado
  estruturalmente (`is_eligible_for_inference`), mas nenhum
  `ReportDefinition` real foi aprovado por um responsável metodológico
  nesta execução — isso depende de um especialista real designado pelo
  produto, fora do escopo de implementação de código.
- Apenas um relatório de exportação (`patients_seen_detail`) foi
  registrado no mecanismo de exportação (`reporting.services.
  register_report`) para demonstrar a máquina completa (síncrono/
  assíncrono, CSV seguro, expiração, notificação); os demais indicadores
  do dicionário da seção 13 têm seletores prontos (`reporting/patients.py`,
  `reporting/operations.py`) mas não foram todos conectados a um botão de
  exportação individual — extensão direta, sem mudança de mecanismo.
