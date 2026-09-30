# Retorno programado

**Roteiro:** `checks/check_retorno.py` · **Migrações:**
`scheduling/0004_retorno_previsto`,
`communications/0007_retorno_como_alvo_de_entrega`

"Volta em seis meses" era decisão clínica que morria na cabeça de quem
atendeu. Ninguém a registrava, ninguém a cobrava, e o paciente crônico
sumia até a próxima crise — numa especialidade feita de seguimento longo,
isso é paciente perdido, não comodidade perdida.

O recurso tem três partes, e cada uma existe porque a anterior sozinha não
resolve: o médico **registra** no fechamento, o sistema **avisa** o
paciente, e a recepção **trabalha** a lista.

---

## 1. Onde o retorno é escolhido

No **modal de finalização do atendimento**, e não numa tela depois.

É o único instante em que a conduta está inteira na cabeça de quem
atendeu. Qualquer tela posterior depende de alguém lembrar de abri-la — e
o recurso inteiro passa a valer o quanto vale essa lembrança.

O padrão é **"Sem retorno programado"**. Nem toda consulta gera retorno, e
um valor pré-escolhido produziria uma fila de retornos que ninguém pediu,
que a secretária aprenderia a ignorar em duas semanas.

Os intervalos oferecidos vêm de `scheduling.returns.INTERVALOS_MESES`
(1, 2, 3, 4, 6, 9, 12, 18 e 24 meses) — uma lista só, e não uma no módulo e
outra no template. Estão em **meses** porque é como a conduta é pensada e
dita: "volta em três meses", nunca "volta em 90 dias".

**O retorno nasce depois da finalização.** Se a finalização for recusada
por requisito faltando, não pode sobrar um retorno previsto de um
atendimento que não fechou.

## 2. A data

`scheduling.returns._somar_meses` soma meses de calendário, e não dias.

31/01 mais um mês é **28/02**, e não 03/03. `timedelta(days=30)` erraria
sistematicamente, e o erro apareceria como retorno previsto para o dia
errado — pequeno em um caso, constante em todos. O roteiro cobra os cinco
casos de borda, inclusive fevereiro em ano bissexto, e tem uma asserção
explícita contra a "simplificação" para 30 dias fixos.

**Um atendimento gera um retorno, não dois.** `agendar_retorno` é
idempotente por atendimento (`update_or_create` sobre `origin_encounter`):
reenviar o formulário ou finalizar de novo **atualiza** o prazo, porque a
intenção mais recente é a que vale.

## 3. O aviso ao paciente

Tarefa Celery diária, `scheduling.tasks.avisar_retornos`, às 6h.

| Decisão | Por quê |
| --- | --- |
| **20 dias de antecedência** | Quem precisa de retorno em seis meses costuma ter agenda cheia, e o médico também. Uma semana descobre que não há vaga; três ainda dão tempo de encaixar. |
| **Não é configurável por clínica** | Multiplicaria os casos da tarefa diária sem que ninguém soubesse responder qual é o prazo certo — e o prazo certo é "com folga para achar vaga". |
| **`due_on <= hoje + 20`, e não `== hoje + 20`** | A tarefa pode não ter rodado ontem. A igualdade deixaria aquele dia sem aviso **para sempre**, e nada indicaria. |
| **`notified_at` marcado depois do envio** | É o que impede o paciente de receber um e-mail por dia durante as três semanas. Marcar antes perderia o aviso de vez se o envio estourasse. |
| **Exceção contida por registro** | Um endereço inválido não pode cancelar os outros cinquenta avisos da manhã. A tarefa devolve `{avisados, sem_contato, falhas}`. |
| **Roda no worker** | O processo `app` não tem saída para a internet nesta topologia. |

**Só e-mail, nunca SMS.** O e-mail carrega descadastro; o SMS, não. Um
aviso de retorno é mensagem que se repete ao longo de anos de seguimento,
e mensagem que se repete sem saída é a definição do que a LGPD trata como
abusivo.

**Base legal: art. 11, II, "f" da LGPD** — tutela da saúde, em
procedimento realizado por profissional de saúde. Dispensa consentimento,
e por isso **depende do que a mensagem diz**: um aviso de continuidade do
cuidado está amparado; "sentimos sua falta, agende já" é captação de
clientela com o mesmo texto do outro lado da linha. O roteiro cobra a
redação — que ela diga "previsto", mande ligar para agendar, avise que a
caixa não recebe respostas e que não contém informação clínica — e cobra a
**ausência** de linguagem promocional.

O aviso ainda respeita `email_enabled` e `marketing_opt_out_at` do
contato: quem recusou não é procurado, mesmo com base legal que
dispensaria a recusa.

## 4. A tela da recepção

`/app/agenda/retornos/` — **Agenda → Retornos previstos**.

**Capacidade de agenda (`SCHEDULE`), não capacidade clínica.** A lista
mostra nome, médico e data: a mesma informação que a grade do dia já
mostra. Exigir `READ_CLINICAL` tiraria a tela exatamente de quem faz o
trabalho, e o defeito apareceria como 404 sem explicação.

- **Ordenada por vencimento, com o atrasado no topo.** A pergunta da tela é
  "para quem ligo agora", e a resposta é sempre quem venceu primeiro.
  Ordenar por nome faria a lista parecer um cadastro.
- **Filtro por médico**, porque clínica com três médicos vira três filas na
  prática: quem liga precisa saber para qual agenda está oferecendo horário
  antes de discar. O valor é conferido contra os médicos **daquela**
  clínica — um `?physician=lixo` viraria erro 500, e um UUID de outra
  clínica não pode sequer ser tentado.
- **Três saídas, não duas:** Agendado, Concluído e **Dispensado**. A
  terceira existe porque paciente que mudou de cidade, teve alta ou faleceu
  precisa sair da lista, e lista que nunca esvazia deixa de ser lida.
- **Observação ao dar baixa.** Sem ela, a lista devolve o mesmo nome amanhã
  e quem ligou ontem não tem como dizer "já tentei três vezes, não atende"
  — a informação fica com a pessoa, não com a clínica.
- O `status` do POST é conferido contra as escolhas do modelo **antes** de
  gravar: sem isso, um POST à mão gravaria qualquer string no campo e a
  linha sumiria da fila por não bater com filtro nenhum, sem nunca ter sido
  trabalhada.

## 5. A entrega ganhou um terceiro alvo

`Delivery` aceitava exatamente um de `document` ou `appointment`. O aviso
de retorno não é nenhum dos dois: no momento em que ele sai **não existe
agendamento** — é justamente disso que o e-mail trata.

A coluna `scheduled_return` entrou por isso. Reaproveitar `appointment`
obrigaria a criar um agendamento falso só para ter onde apontar, e ele
apareceria na grade do médico.

A restrição `communications_delivery_single_target` passou a exigir
exatamente **um de três**, escrita por extenso porque `sum(...) == 1` não
existe em SQL de restrição. Foi ela que reprovou a primeira versão deste
recurso: a entrega nascia sem alvo nenhum e o banco recusou a linha.

## 6. O que o roteiro cobra

`docker compose exec app python manage.py rodar_roteiros retorno`

| Seção | Asserções |
| --- | --- |
| 1 | soma de meses nos cinco casos de borda, e a asserção contra 30 dias fixos |
| 2 | idempotência por atendimento; prazo novo vence o antigo; "sem retorno" não cria linha |
| 3–4 | fila por data, atrasado marcado, baixa tira da fila e fica no histórico |
| 5 | janela de 20 dias, dia perdido recuperado, `notified_at` barra o segundo envio, vencido não recebe aviso de antecedência |
| 6 | `email_enabled` e `marketing_opt_out_at` barram; a entrega nasce, é por e-mail, aponta para o retorno e para mais nada; chamar de novo não duplica |
| 7 | a redação do e-mail, e a ausência de linguagem de captação |
| 8 | a tarefa devolve o balanço em vez de estourar |
| 9 | a secretária abre a fila, vê o atrasado, dá baixa com observação; filtro inválido não derruba; status inventado é recusado |
| 10 | os intervalos são meses e incluem os usuais da especialidade |
