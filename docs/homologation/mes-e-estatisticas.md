# A visão de mês, e as estatísticas

**Roteiro:** `checks/check_mes_e_estatisticas.py` ·
**Módulos:** `scheduling/availability.py`, `scheduling/estatisticas.py` ·
**Telas:** agenda do mês · **Agenda → Estatísticas do mês**

---

## 1. A visão de mês mentia sobre o passado

Dois defeitos da mesma família, encontrados em uso real.

### "lotado" num dia que só passou

O rótulo aparecia sempre que não havia vaga livre — e num dia vencido
nunca há. Navegando o mês anterior, **todo dia** dizia "lotado",
desenhando uma agenda cheia que não existiu.

Agora: **"encerrado"** quando o dia passou, com as contagens de atendidos
e de vagos ao lado. "lotado" só quando a agenda está de fato cheia.

### A consulta que aconteceu desaparecia

`COMPLETED` **não está** em `OCCUPYING_STATUSES`, e isso é deliberado:
atendimento encerrado libera a vaga para remarcação.

O efeito colateral era grave: num mês passado, a célula de uma consulta
realizada voltava como `past` — "passou e ninguém usou" —, indistinguível
de um horário vago. **Um mês cheio de trabalho aparecia vazio.**

E isso tornava o conserto do primeiro defeito perigoso: marcar os
passados como "Vago" escreveria *"Vago"* onde um paciente foi atendido —
pior que o problema original.

**A solução foi um quinto status, `done`.** Ele nasce de uma célula que já
seria `past`, e **nenhuma conta de vaga livre olha para `past` nem para
`done`** — por isso a disponibilidade não mudou de comportamento. O
roteiro cobra exatamente isso: `day_grid` sem histórico produz os mesmos
números de antes.

| Status | Cor na tela | Significa |
| --- | --- | --- |
| `free` | verde | dá para marcar |
| `busy` | vermelho | reserva ativa, **com o nome do paciente** |
| `done` | azul | já atendido, ou falta registrada, com o nome |
| `past` | cinza | passou e ninguém usou — **"Vago"** |
| `blocked` | — | feriado, férias ou bloqueio |

O histórico (`COMPLETED`, `NO_SHOW`) é carregado no mesmo lote das demais
reservas e passado a `day_grid` pelo parâmetro `historico`, que é
**opcional**: os outros cinco chamadores não o passam, e por isso nada
mudou para eles.

## 2. O nome do paciente na célula do mês

Pedido de quem usa: a secretária que recebia uma ligação ("é a consulta da
dona Maria?") tinha de abrir o dia para descobrir de quem era cada
horário.

**É consistente com a fronteira que a agenda já tem.** A grade da semana,
a do dia e o balcão já mostram nome, horário e tipo — e nada de
prontuário. A tela exige `SCHEDULE`, a mesma capacidade das outras.

O nome é truncado por **CSS**, com o nome inteiro no `title`. Cortar no
servidor esconderia o final de "ADRIANO TRIGO MONTEIRO DE MATOS SOEIRO
FILHO" de todo mundo, inclusive de quem passa o mouse para conferir.
`min-width: 0` é o que faz o `text-overflow` funcionar dentro de um item
flex — sem ele a célula transborda em vez de cortar.

## 3. Estatísticas do mês

**Aos quatro papéis, com `SCHEDULE`.** A tela mostra **contagens** —
nenhum nome de paciente, nenhum diagnóstico, nenhum valor. É operação do
consultório, e quem o opera é a recepção tanto quanto o médico. O roteiro
tem asserção de que nenhum nome aparece ali.

Os indicadores de `reporting` continuam exigindo `MANAGERIAL_DASHBOARD`:
aqueles cruzam faturamento, e dinheiro é outra conversa.

### Mês a mês, nunca acumulado

Uma média de doze meses esconde o que interessa: o mês em que as primeiras
consultas caíram pela metade. A comparação com o mês anterior vem ao lado,
e é a única comparação que a tela faz.

### Quatro colunas que não se somam

| Coluna | O que é |
| --- | --- |
| **Atendidos** | o paciente veio — `Concluído`, `Em atendimento`, `Check-in feito` |
| **Agendados** | ainda na agenda. Num mês passado isto é resíduo, e ver o número é o caminho para corrigir |
| **Faltas** | `NO_SHOW` |
| **Cancelados** | `CANCELLED` |

Somar falta e cancelamento ao movimento infla o mês com gente que não
apareceu — e um relatório de produtividade que conta quem faltou não serve
para decidir nada.

Por tipo: Primeira consulta, Seguimento, Retorno, Procedimento, Outro.

### A ocupação vem da mesma grade da agenda

`month_summary`, e não uma segunda conta. Duas contas do mesmo número
divergem no primeiro ajuste de regra de horário, e aí a tela e a agenda
passam a discordar sobre quantas vagas existem.

Horários · Ocupados · Atendidos · **Vagos** · Livres · Bloqueados, por
médico e somados.

A taxa usa o total de horários **que existiram** no mês, e não só os
vencidos: do contrário um mês mal começado mostraria 100% de ocupação por
ter uma consulta e nenhum horário passado.

## 4. O que o roteiro cobra

`rodar_roteiros mes_e_estatisticas`

| Seção | Asserções |
| --- | --- |
| 1 | a célula atendida vira `done`, traz o paciente, **não conta como reserva ativa**, e as vagas livres **não mudam** |
| 2 | a célula ocupada traz o nome e é marcada como início da reserva |
| 3 | **`day_grid` sem histórico produz exatamente o que produzia** — a oferta de vaga não mudou |
| 4 | a tela mostra o nome, chama o vago de "Vago", e o dia encerrado não diz "lotado" |
| 5 | marcado conta como agendado e não como atendido; concluído conta como atendido; falta e cancelamento ficam fora do movimento |
| 6 | a secretária abre, vê contagens, **não vê nome**, e mês/ano/médico inválidos não derrubam a tela |
