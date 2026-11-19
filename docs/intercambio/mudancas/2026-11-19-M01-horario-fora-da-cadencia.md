---
id: MD-2026-11-19-01
data: 2026-11-19
origem: sessao-unica
tipo: defeito
sigiloso: nao
estado_aqui: corrigido e verificado no ambiente local
roteiro_aqui: checks/check_horario_fora_da_cadencia.py
no_outro: feito na mesma rodada — PD-M-2026-11-19-01
---

# Incluir horário fora da cadência deixava um período invisível e recusado

**Sintoma (produção, uma clínica).** Numa agenda de quarta das 13h30 com
células de 45 min, a secretária excluiu 14h15 e 15h00 e incluiu 14h30. A
14h30 não apareceu, o dia ficou vazio no mês, e toda nova tentativa de
incluir 14h30 era recusada: "Das 14:30 às 15:15 já é horário de
atendimento neste dia". Republicar a agenda não resolvia (o horário
excluído é exceção da data e continua valendo).

**Causa.** Duas, juntas.

1. `include_extra_hours` reabria o pedaço dos horários excluídos
   (14h30–15h15) e não gravava extra, porque o período estava dentro da
   janela da regra. Mas `day_grid` só desenha células na cadência da regra
   (13h30 + 45 min): nenhuma cabia ali. O período ficou aberto e sem
   célula — invisível, sem como marcar.
2. A recusa "já é horário de atendimento" era calculada pela janela
   declarada menos os excluídos, e contava esse período fantasma como
   atendimento.

**Correção.**

- `day_grid`: o atendimento extra vence a cadência da semana — as janelas
  de extra são desenhadas primeiro, e a célula da regra que se sobrepõe a
  uma célula já desenhada não entra (antes, só o mesmo início era
  evitado).
- `include_extra_hours`: recusa só quando o pedido toca uma **célula que a
  grade desenha** (livre, ocupada, passada); bloqueio de data mantém a
  recusa própria e o almoço continua não recusando. Depois de reabrir os
  excluídos, a grade é simulada com os blocos que seriam gravados; se as
  células pedidas não aparecem no lugar pedido, o pedido inteiro vira
  atendimento extra.
- Continua igual: excluir e incluir no mesmo lugar é desfazer (nada
  gravado), e estender além do fim da janela grava só o pedaço de fora.

**Roteiro.** `check_horario_fora_da_cadencia` (novo): o caso exato, o
estado que ficou em produção (o fantasma), as recusas que continuam, o
desfazer, a extensão, o almoço, excluir a célula incluída e a semana, o
mês e a lista de livres. Reprovou no código antigo com a mensagem exata de
produção. Passaram também `check_incluir_horario`, `check_excluir_horario`,
`check_bloquear_horario`, `check_semana_em_lote`,
`check_intervalos_e_ficha`, `check_mes_e_estatisticas`,
`check_agenda_balcao_e_mes`, `check_tipo_de_consulta`,
`check_lista_de_espera` e `check_teleatendimento`.

**No outro lado.** `scheduling/services.py` e `scheduling/availability.py`
eram idênticos no ProntDoc: mesma correção e mesmo roteiro, verificados lá.
