# A duração que acompanha o tipo, o horário extra pela agenda, e a idade ao lado do nome

**Versão:** 1.13 · **Data:** 2026-10-13 ·
**Roteiros:** `check_tipo_de_consulta.py` (reescrito), `check_incluir_horario.py`,
`check_idade.py` (novos)

## 1. Trocar o tipo muda a duração

### O que aconteceu

Uma primeira consulta marcada às 17h ocupa duas células de 40 min (80
min). Trocada para retorno (40 min), a visão de mês continuava mostrando
o próximo horário livre às 18h20, e não às 17h40.

### Por quê

Não era defeito de desenho da tela: era a regra. Desde a 1.10,
`services.change_appointment_type` trocava **só o tipo** e deixava o
horário intacto, com dois argumentos — esticar podia invadir o horário
seguinte, e encolher "liberaria uma sobra que ninguém pediu". O roteiro
conferia exatamente isso. O uso real mostrou que a sobra é pedida: a
duração é do tipo em toda outra porta (`reserve_from_grid`), e só aqui
ficava presa ao tipo anterior.

### O que entrou

O início não muda; o fim passa a ser início + duração do novo tipo
(configurada por médico em `AppointmentTypeDuration`).

| Caso | Resultado |
| --- | --- |
| Tipo mais curto | Encolhe; as células do fim voltam a ficar livres na hora |
| Tipo mais longo, tempo seguinte livre | Estica |
| Tipo mais longo sobre outro paciente, bloqueio ou fim do expediente | **Recusa inteira**, dizendo o motivo e o caminho ("remarque para um horário em que ele caiba"); tipo e fim ficam como estavam |
| Encaixe | Estica sem passar pela grade, como foi marcado |
| Reserva com intervalo pós-consulta | O intervalo é preservado, medido do novo fim |

A conferência ao esticar é a mesma de quem marca, `availability.fits`,
que ganhou `ignorar=` para não ver a própria consulta como obstáculo.
A remarcação passou a usar o mesmo parâmetro: antes, adiantar uma
primeira consulta em 40 min era recusado com "às 17h40 o horário já está
ocupado" — por ela mesma. A corrida entre a conferência e a gravação é
pega pela `ExclusionConstraint` e vira a mesma recusa, em português.

O seletor do modal mostra os minutos de cada tipo, e a trilha
(`scheduling.appointment_type_changed`) guarda o fim anterior e o novo.

## 2. Incluir horário, ao lado do dia

### O pedido

Nas visões de mês, semana e dia, um botão ao lado do dia para a
secretária (ou quem puder) incluir um horário extra de atendimento.

### O que entrou

O botão (**+** no mês, **+ horário** no cabeçalho de cada dia da semana,
**+ Incluir horário** no dia) abre um modal com **início** e
**quantidade de horários**. Grava o mesmo `ScheduleBlock` de
"Atendimento extra" que Configurar horários já gravava —
`services.include_extra_hours`, `POST /app/scheduling/<médico>/incluir-horario/`.
O início vem sugerido com o fim do último horário do dia, que é o caso
comum ("vou ficar até mais tarde").

**Quantidade, e não hora de fim.** O fim é a célula do dia ×
quantidade. Um fim digitado que não fechasse a célula abriria uma janela
em que nenhuma consulta cabe: o extra seria gravado e não apareceria na
grade.

**Recusas**, todas com o motivo na tela:

- horário que já é de atendimento (as células se sobreporiam);
- horário sob bloqueio de data (o bloqueio vence o extra, e nada
  abriria) — a recusa diz qual bloqueio;
- passado; e o que atravessa a meia-noite.

**Quem pode:** a mesma regra de Configurar horários, por objeto
(`can_configure_agenda_of`) — dono, gestor e secretária em qualquer
agenda; o médico só na dele. O botão nem é desenhado para quem não pode,
e a view confere de novo. Outra clínica recebe 404.

**Desfazer:** o horário incluído aparece em Configurar horários, na
lista de bloqueios e extras, de onde se remove. A mensagem de sucesso diz
isso.

## 3. A idade ao lado do nome, e o fim do "versão N"

**Idade:** filtro `nd_idade` (`base/templatetags/nd.py`), um só para as
telas. Na **ficha**, a idade de hoje, logo depois do nome. No
**cabeçalho do atendimento**, a idade **na data do atendimento** — quem
relê a consulta de 2019 de uma criança precisa saber que ela tinha 4
anos ali. Também na linha do tempo do prontuário. Abaixo de um ano sai em
meses; ano de nascimento estimado sai com "~"; sem dado, nada.

**"versão 7" ao lado do nome do paciente** era `encounter.row_version`, o
contador interno de gravações que impede dois salvamentos de se
atropelarem. Não diz nada ao médico e foi retirado da tela. A trava
continua funcionando — ela nunca dependeu do selo.

## Verificação

- `check_tipo_de_consulta.py`: §1 e §9 provam o encolher (inclusive a
  célula liberada na grade, o caso das 17h), o esticar onde cabe, a
  recusa sem efeito sobre paciente vizinho e sobre o fim do expediente,
  o encaixe e o intervalo pós-consulta; §10, a mensagem da tela.
- `check_incluir_horario.py`: células livres e consulta de duas células
  cabendo, as cinco recusas, a fronteira de permissão e entre clínicas,
  e o modal presente nas três visões.
- `check_idade.py`: a conta (aniversário, meses, estimado, vazio), a
  idade da data do atendimento, e o selo retirado.
