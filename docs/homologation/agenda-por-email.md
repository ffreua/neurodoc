# Agenda do dia seguinte por e-mail — homologação

Versão **1.36** (2026-11-05). O mecanismo está em
`scheduling/agenda_por_email.py`.

## 1. O que o médico recebe

Às 19h de Brasília (`AGENDA_POR_EMAIL_HORA`), no e-mail da própria conta,
um e-mail por clínica em que tem horário amanhã: horário (início e fim),
paciente, tipo de consulta, "Confirmado" ou "A confirmar" e o encaixe
marcado, com o total e quantos já confirmaram. Em texto e em HTML, com um
botão que abre a agenda daquele dia.

**É agenda, não prontuário:** o mesmo que a grade mostra à secretária (nome,
horário, tipo). Nada clínico. E vai ao e-mail da conta do médico — o mesmo
que recebe a recuperação de senha.

## 2. Decisões

- **Uma mensagem por médico e por clínica.** Quem atende em duas recebe duas:
  são duas agendas e duas recepções.
- **Dia sem horário não gera e-mail.** "Amanhã você não tem ninguém" todo
  sábado ensina a ignorar a próxima mensagem.
- **Cancelado e falta ficam de fora**; o resto do que ocupa a grade entra.
- **A clínica suspensa recebe, a encerrada não.** Suspensão congela a
  escrita, não a agenda.
- **Sai pela clínica, não pelo médico** (`send_email(tenant_id=...)`): o
  servidor da clínica se ela cadastrou, senão o da instalação — a cadeia de
  §7-G do `CLAUDE.md` a partir da clínica. O remetente pessoal do médico
  existe para falar com os pacientes dele.
- **Ligado por padrão, desligado pelo próprio médico**, por clínica
  (`Membership.agenda_por_email`), pelo link do rodapé. O vínculo vai na
  rota: quem atende em duas clínicas pode estar com a outra aberta na
  sessão. O vínculo de outra pessoa é 404.
- **19h**: a agenda de amanhã já está quase fechada, e o médico ainda lê
  antes de dormir. O e-mail diz a hora em que a lista foi tirada.

## 3. Uma vez por dia

`AgendaPorEmailEnvio` tem `UNIQUE (médico, dia)` e é gravada **antes** do
envio: duas rodadas — publicação no meio, beat reiniciado — mandam uma vez.
A falha ao enfileirar fica na linha (`erro`) e não se repete no dia
seguinte: a agenda de ontem já não serve. A linha guarda quantos horários,
não quais.

## 4. O idioma

No worker não há requisição, e o idioma não vem ativado: o `date:"l"` do
modelo escreveria o dia da semana em inglês. O envio renderiza sob
`translation.override(LANGUAGE_CODE)`, e o roteiro roda também com o idioma
desligado.

## 5. Resultado do roteiro

`checks/check_agenda_por_email.py`, oito seções, dentro de uma transação
desfeita e com o envio interceptado:

1. o que entra: três de sete horários (cancelado, falta, hoje e depois de
   amanhã de fora), em ordem, com a confirmação em português;
2. quem recebe: o médico ativo sim; quem desligou, o revogado e a secretária
   não; a suspensa sim e a encerrada não;
3. o e-mail: pela clínica e sem o vínculo do médico, o assunto com o dia e a
   clínica, os pacientes em ordem, tipo, confirmação, encaixe, o resumo, o
   dia por extenso, a hora da lista, os dois links e o HTML; o registro com
   o número de horários;
4. a segunda rodada sem envio;
5. às 23h30 (amanhã em UTC), a agenda de amanhã de Brasília;
6. a falha registrada e não repetida;
7. a tela: o próprio médico desliga e religa, com a trilha; o vínculo alheio
   e a secretária em 404, e o POST alheio sem mudar nada;
8. o agendamento na hora do `settings`.
