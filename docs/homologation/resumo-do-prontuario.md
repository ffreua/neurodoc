# Resumo do prontuário: deste atendimento ou de todos (1.42)

Pedido do Dr. Fernando em 2026-11-09: no botão **Resumo do caso**, a opção do
atendimento atual ou de todos os atendimentos, "com o último em primeiro lugar
na página e os demais na sequência".

## O que existe

| Opção | Rota | Página |
| --- | --- | --- |
| Este atendimento | `clinical:summary` | `templates/clinical/summary.html` (como antes, com o link para a outra) |
| Todos os atendimentos | `clinical:resumo-todos` (`patients/<id>/resumo/`) | `templates/clinical/summary_todos.html` |

O botão das duas telas de atendimento virou um menu
(`templates/clinical/_botao_resumo.html`). No texto livre ele continua com o
nome **Imprimir**. No celular, as duas opções aparecem como botões no painel
de ações, porque um menu suspenso dentro do painel que rola sai cortado. As
duas abrem em janela própria com a proporção de uma folha. Esse comportamento
morava num `<script>` da tela estruturada e faltava na de texto livre; agora
fica em `static/duralux/nd-inline.js` e vale para todo link `data-nd-window`.

## Decisões

**Um corpo só para as duas folhas.** O que se imprime de cada atendimento
está em `templates/clinical/_resumo_corpo.html`: história, evolução ou texto
livre, medicação, exame, resultados, hipóteses, impressões, conduta e
adendos. As duas folhas incluem esse parcial, e o estilo fica em
`_resumo_estilo.html`. Com o corpo copiado nas duas, a primeira seção nova
entraria numa e não na outra.

**A ordem é a do pedido: do mais recente ao primeiro.** É a ordem em que se
lê um prontuário para decidir a consulta de hoje. Um sumário no alto leva a
cada atendimento e, na impressão, serve de índice.

**Sem quebra de página forçada entre atendimentos.** Num paciente com dezenas
de retornos (o histórico do iClin), uma folha por consulta imprimiria muito
papel em branco. O cabeçalho de cada atendimento não se separa do que vem
logo abaixo dele.

**Tudo em lote, num número fixo de consultas ao banco.** Montar cada
atendimento como a folha de um atendimento monta custaria seis consultas por
atendimento. `PatientSummaryView` busca achados, medicação, resultados,
hipóteses e adendos de todos os atendimentos de uma vez e agrupa na memória.
O roteiro mede 2 e 8 atendimentos e exige o mesmo número de consultas.

**Os atendimentos são os da linha do tempo.** A folha mostra os mesmos
atendimentos da tela do prontuário, inclusive os não finalizados, e cada um
destes sai marcado como *ainda editável*. A leitura vai para a trilha
(`clinical.patient_summary_viewed`, com o número de atendimentos), e a
capacidade exigida é a de ler o prontuário, a mesma da folha de um
atendimento.

**Não é documento assinado.** O rodapé diz isso, como na folha de um
atendimento.

## Verificação

`checks/check_resumo_do_caso.py`, dentro de uma transação desfeita. O roteiro
confere:

- a ordem, pela posição de cada atendimento na página;
- que cada atendimento mostra só a sua medicação, hipótese, escala e adendo;
- os três tipos desenhados como na folha de um atendimento;
- o mesmo número de consultas ao banco com 2 e com 8 atendimentos;
- que a folha de um atendimento continua igual e ganhou o link para todos;
- os botões nas duas telas de atendimento, no computador e no celular;
- a fronteira (outra clínica e secretária), a trilha, o paciente sem
  atendimento e a recusa do POST.
