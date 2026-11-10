# Teleatendimento na agenda (1.43)

Pedido do Dr. Fernando em 2026-11-10: a secretária marca o horário como
**teleatendimento**, e a marca aparece no horário aberto e em toda tela que
lista agendamento, como o ✓ do confirmado. Serve para o médico e a recepção
saberem que aquele paciente não vem ao balcão.

## O que é

Uma **marca de agenda**. O horário marcado mostra uma câmera:

| Onde | Como aparece |
| --- | --- |
| Agenda da semana | câmera antes do nome do paciente, e na legenda |
| Agenda do dia | câmera antes do nome, e a palavra na linha de baixo |
| Agenda do mês | câmera ao lado da hora (junto do ✓ do confirmado), e na legenda |
| Horário aberto (modal) | crachá **Teleatendimento** ao lado do tipo e da situação |
| Balcão do dia | crachá com a palavra, que sai também na impressão |
| Ficha do paciente → Agendamentos futuros | câmera e a palavra |
| Agenda do dia seguinte por e-mail | a palavra, por extenso |

## Como se marca

- **Ao agendar**: a caixa **Teleatendimento (consulta por vídeo)** no modal de
  marcar. Nasce desmarcada, e é limpa a cada abertura do modal.
- **No horário já marcado**: o botão **Marcar como teleatendimento**; em quem
  já tem a marca, o botão é **Retirar a marca de teleatendimento**. Um de cada
  vez.

Quem pode: quem já marca horário (`Capability.SCHEDULE`) — os quatro papéis.

## O que ela não é

- **Não é um tipo de consulta.** Primeira consulta e seguimento acontecem dos
  dois jeitos, e o tipo decide a duração e a cobrança. Por isso é um campo ao
  lado de `type` (`Appointment.teleatendimento`), e não um valor novo.
- **Não muda nada no horário**: nem tipo, nem duração, nem cobrança, nem
  situação, nem `row_version` — mudar a versão calaria os lembretes já
  agendados, como na forma de cobrança.
- **Não avisa o paciente** e não muda o texto da confirmação, do lembrete nem
  do WhatsApp da recepção.
- **O sistema não faz a chamada de vídeo.** Não há sala, link nem gravação.
- **Não entra no prontuário.** O atendimento aberto a partir do horário é o de
  sempre.

## Decisões

- **Duas ações com nome** (`teleatendimento` e `presencial`), e não um
  alternador: o clique repetido, ou a aba velha de outra pessoa, não desfaz o
  que acabou de ser marcado. Repetir a mesma ação não grava nem entra na
  trilha.
- **Só por POST**, como toda ação do horário; sem pergunta antes, porque nada
  é enviado e a volta está no mesmo lugar.
- **Vale até o atendimento**: agendado, confirmado, chegou e em atendimento.
  Concluído, cancelado e falta são história, e a troca é recusada.
- **Remarcar mantém a marca** (é o mesmo horário, do mesmo paciente).
  **Trocar o paciente a retira**: ela foi combinada com o anterior.
- **A câmera é um SVG num arquivo só** (`templates/scheduling/_tele.html`),
  com nome para o leitor de tela. No e-mail vai a palavra: cliente de e-mail
  descarta SVG.
- **No balcão vai a palavra, e não só a câmera**: é a lista que se imprime.
- **O padrão está também no banco** (`db_default`): durante a troca de versão
  e depois de um rollback, o código anterior grava horário sem conhecer a
  coluna.
- A trilha registra `scheduling.appointment_teleatendimento_changed` com
  ligado ou desligado, sem nome nem contato.

## Verificação

`checks/check_teleatendimento.py`, com agendamentos e pacientes criados e
apagados pelo próprio roteiro.
