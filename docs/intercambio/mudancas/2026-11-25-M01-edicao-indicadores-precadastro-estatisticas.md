# 2026-11-25 — Editar exame/diagnóstico, % por subtipo, nascimento no pré-cadastro e livres por tipo (Leva A)

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc, na mesma rodada que o ProntDoc |
| Tipo | mudança (quatro ajustes pedidos pelo titular), feita nos dois |
| Origem | pedido do titular — primeira leva de um conjunto maior; a segunda (teleatendimento) fica para a rodada seguinte |

Quatro ajustes de dentro do atendimento e da agenda, **sem migração** (todos
usam campos que já existiam). Verificados nos dois sistemas.

**1. Editar o exame e o diagnóstico já lançados.** Antes só a medicação tinha
o lápis por linha; o exame e o diagnóstico eram só inclusão. Agora os dois se
editam no lugar, pelo mesmo padrão da medicação — inclusive **mudar a certeza
da hipótese de suspeita para confirmada** (e voltar). A trilha guarda o
**nome** do campo que mudou, nunca o conteúdo clínico; a edição é recusada em
atendimento finalizado, para a secretária, em outra clínica e em item de outro
atendimento. Formulários novos em `clinical/forms.py` (`ExamResultEditForm`,
`DiagnosisEditForm`), views `DiagnosisUpdateView`/`ExamResultUpdateView`
espelhando `MedicationUpdateView`, duas rotas novas em `clinical/urls.py`, e o
lápis + formulário recolhido em `templates/clinical/_exam_results.html` e nas
tabelas de hipóteses.

**2. % de cada subtipo de consulta nos indicadores.** Além do valor, o
percentual de cada subtipo (primeira consulta, seguimento, retorno,
procedimento) ao lado. `reporting/views.py` passa `atendidos_por_tipo_pct`; o
`templates/reporting/dashboard.html` mostra.

**3. Data de nascimento no pré-cadastro da agenda.** Para a idade aparecer já
no pré-cadastro: campo opcional `new_birth_date` no `BookingForm`; quando
informado, `scheduling.services.quick_register_patient` grava a data e tira o
motivo "a completar na recepção". Sem data, segue como antes.

**4. Quantas consultas de cada tipo cabem no tempo livre.** Nas estatísticas
do mês, ao lado dos horários livres, quantas consultas de cada tipo cabem,
pela **divisão inteira** (arredondando para baixo) do tempo livre de cada
médico pela duração do tipo, somada entre os médicos. `_ocupacao` em
`scheduling/estatisticas.py` passou a devolver também `cabem`, e `do_mes`
devolve `cabem_por_tipo`; a tela mostra em `templates/scheduling/estatisticas.html`.

**Verificação.** Dois roteiros novos nos dois sistemas —
`check_editar_exame_diagnostico` (o lápis, a certeza, a trilha só com o nome
do campo, as recusas) e `check_precadastro_e_livres` (a data gravada e o
motivo retirado; `cabem_por_tipo` presente e coerente com os livres) — passando
nos dois, além dos vizinhos de regressão (medicação, estatísticas/mês, agenda,
painel, celular, rótulos, texto livre, CSP, idioma).

**Diferença entre os lados.** No NeuroDoc a edição da hipótese entra também na
tela do prontuário estruturado (`detail.html`); no ProntDoc só há texto livre
(`detail_livre.html`). O bloco de imports do `clinical/views.py` diverge (o
ProntDoc não tem `FindingForm`), então o patch foi adaptado em cada lado, não
copiado às cegas.

**VERSION:** NeuroDoc **1.57**, ProntDoc **1.11.0** — é funcionalidade nova e
compatível, então a versão menor avança.
