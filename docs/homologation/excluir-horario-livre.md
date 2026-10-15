# Excluir um horário livre, do modal de marcar

**Versão:** 1.14 · **Data:** 2026-10-15 ·
**Roteiro:** `check_excluir_horario.py` (novo)

## O pedido

Clicar num horário livre abre o modal de marcar: paciente já cadastrado
ou pré-cadastro. Faltava, ali mesmo, **tirar** aquele horário da agenda —
"na terça às 15h o doutor não atende". O avesso do botão Incluir horário
da 1.13, e pela mesma razão: quem recebe o aviso está olhando a agenda, e
Configurar horários pedia início e fim digitados para fechar uma célula.

## O que entrou

Um botão **Excluir este horário** no rodapé do modal, à esquerda e longe
de "Marcar", com confirmação. Só aparece para quem pode configurar
**aquela** agenda (dono, gestor, secretária; o médico, na própria) — a
mesma permissão de Incluir horário, conferida de novo no servidor.

| A célula clicada | O que acontece |
| --- | --- |
| Horário da grade semanal | Vira **bloqueio do tamanho da célula**, com o motivo "Horário excluído pela agenda". A célula continua na grade, fechada e com o motivo |
| Um atendimento extra inteiro (o horário incluído pela agenda, de uma célula) | O extra é **apagado**: incluir e excluir é desfazer, e a célula some |
| Uma célula no meio de um extra maior | Bloqueio só dela; as vizinhas continuam livres |
| Ocupada, já bloqueada, passada ou inexistente | **Recusa**, sem gravar nada: "Este horário não está mais livre" |

Tudo vai para a trilha (`scheduling.block_created` ou
`scheduling.block_deleted`).

## As decisões

**Bloqueio, e não mudar a regra semanal.** A regra vale para todas as
terças; excluir um horário é exceção de um dia, que é exatamente o que o
`ScheduleBlock` de bloqueio já é. E por isso o desfazer é o que já
existia: remover o bloqueio em Configurar horários — a mensagem de
sucesso diz isso.

**A célula continua aparecendo, fechada.** Sumir com ela faria a grade
mostrar um buraco sem explicação, e a secretária seguinte ligaria para o
médico perguntando se dá para encaixar — o mesmo motivo de a célula
bloqueada mostrar o motivo desde a 1.0.

**A exceção é o extra inteiro.** Um bloqueio por cima de um horário que
só existia porque alguém o incluiu deixaria na tela uma célula fechada
num horário em que o médico nunca atendeu. Apagar o extra é o desfazer
certo. Se esse extra estiver sobreposto à grade semanal (Configurar
horários não recusa isso), apagá-lo não fecha nada — e então entra o
bloqueio também, para a célula não continuar livre.

**Só fecha o que está livre, dentro da trava do dia.** A conferência é a
grade montada sob a mesma trava de `reserve_from_grid`. Sem isso, uma
secretária marcando e outra excluindo o mesmo horário gravariam as duas
coisas, e o paciente ficaria num horário que a agenda diz não existir.

**Formulário próprio, fora do de marcar.** O botão pertence a ele pelo
atributo `form=`: formulário dentro de formulário o navegador desfaz.

## Verificação

`check_excluir_horario.py`: as quatro linhas da tabela, nenhuma recusa
gravando nada, a fronteira entre clínicas e entre colegas médicos, o
horário ilegível voltando com aviso em vez de erro 500, e o botão no
modal das três visões só para quem pode.

**Bateria:** 106 roteiros, nenhuma falha (2026-10-15, local, imagem
reconstruída).
