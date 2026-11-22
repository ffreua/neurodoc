# 2026-11-22 — Painel de indicadores completo e a naturalidade

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc 1.56, na mesma rodada que o ProntDoc |
| Tipo | mudança (pedido do titular) |

**Indicadores** (`/app/reporting/`): cartões de **Seguimentos** e
**Retornos** pelo tipo marcado na agenda, com check-in; a linha "Consultas
atendidas por tipo"; a contagem antiga ("retornos" inferidos do histórico)
desceu para a tabela como "Atendimentos de quem já era paciente". Quadro
**Receita por tipo de atendimento** (`operations.receita_por_tipo`):
primeira consulta, seguimento, retorno e cada procedimento pelo código
TUSS, com quantidade, valor, médio e porcentagem; a consulta sem horário
entra pelo tipo da regra de honorário, e sem nenhum dos dois em "sem tipo";
o total fecha com a receita por competência.

**Taxa de falta** (achado na mesma rodada): contava só "Concluído", e a
clínica fecha pelo check-in — saía "sem dados". Agora usa a regra das
estatísticas da agenda (`scheduling.estatisticas.ATENDIDOS`), também no
Dashboard.

**Dashboard**: cartões de **naturalidade** (país de nascimento, com a
célula pequena; Brasil só com cidade ou UF de nascimento, porque o campo
nasce "BR" em todo cadastro) e **UF de nascimento**, com CSV.

Igual nos dois lados (código idêntico). Roteiro: `check_indicadores_por_tipo`.
