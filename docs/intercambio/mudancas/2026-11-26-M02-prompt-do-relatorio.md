# MD-2026-11-26-02 — Prompt de sistema do relatório por IA

**Data:** 2026-11-26. **Tipo:** mudança. **Feito nos dois na mesma rodada** (PD-M-2026-11-26-02).
Prompt idêntico nos dois; `PROMPT_VERSION` v3 → v4.

## O que mudou

- `ai/graphs.py`: o relatório passa a ir em **duas mensagens**, `REPORT_SYSTEM_PROMPT`
  (regras) e `REPORT_PROMPT` (destinatário, orientação, `<pedido>`, seções sugeridas e
  `<prontuario>`). A redação parte da proposta do titular: escrita de médico experiente,
  cronologia longitudinal, raciocínio clínico, repercussão funcional, integridade, adaptação à
  finalidade, revisão final silenciosa. As outras tarefas continuam em texto único.
- `ai/relatorio.py::montar_contexto`: cada atendimento ganha `autoria`
  (`medico_que_assina`, `outro_profissional`, `nao_registrada`), comparando o médico do
  atendimento com quem pediu o relatório. Sem nome do colega. É o que permite a primeira
  pessoa ("avaliei", "optei") sem atribuir ao signatário a consulta de outro.

## Onde a proposta foi adaptada, e por quê

- A saída continua JSON validado (`PatientReportArtifact`): o "corpo" vai em `secoes`, e o
  que falta vai ao médico em `informacao_faltante`, não ao papel.
- Mais estrito que a proposta: a IA não conclui sobre incapacidade, aptidão, afastamento,
  benefício ou prognóstico definitivo; só reproduz, atribuída, a conclusão que o médico
  registrou. Não recomenda conduta que o prontuário não traga.
- O prontuário (que inclui texto do paciente pelo portal) é declarado dado, nunca instrução.
- Acrescentado depois do primeiro teste real: não escrever seção só para dizer que não há
  dado, nem frases como "não consta"/"não é objeto deste relatório"; cada dado uma vez só.

## Verificação

- `check_relatorio_ia` seção 17 (12 conferências): duas mensagens, prontuário fora do
  sistema, pedido delimitado, autoria correta, nome do colega ausente, grafo entrega as
  mensagens e valida o esquema. Passam também `check_ia_plano`, `check_relatorio_pelo_sino`,
  `check_ia_reserva` e `check_ia_assincrona`, nos dois.
- Teste real (worker de produção do NeuroDoc, caso **fictício** de perícia do INSS com uma
  consulta de colega e uma instrução escondida no texto da paciente): primeira pessoa só nas
  consultas do signatário, a do colega atribuída à equipe, a instrução ignorada e apontada
  ao médico, nenhuma conclusão de incapacidade. `z-ai/glm-5.3`: 168 s e 210 s (o prazo do
  relatório é 240 s; o do apoio diagnóstico, 150 s). `deepseek/deepseek-v4.1-flash`: 29 s,
  qualidade equivalente.
