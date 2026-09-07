# Agenda

A agenda é o segundo ponto crítico do sistema, e o desenho tem uma decisão
central da qual tudo o mais decorre.

## A decisão: uma célula base, ocupação variável

Você descreveu: *"segundas das 08h até as 18h com um horário a cada 1h e
20min as consultas de primeira vez e seguimento e 40min as consultas de
retorno"*.

Duas durações na **mesma** janela de atendimento. Havia dois jeitos de
resolver:

| | Como funcionaria | Por que não |
| --- | --- | --- |
| Uma régua por tipo | Cada tipo com seus horários próprios | Não dá calendário: cada tipo pediria uma coluna, e a secretária não veria de uma vez o que está livre |
| **Célula base** | A grade é de 40 min; uma primeira consulta ocupa **duas** células, um retorno ocupa **uma** | É o que permite um calendário só, com tudo visível — e é como a clínica funciona de fato |

Ficou a segunda. O médico declara a janela e o tamanho da célula; a duração
de cada tipo é configurada por médico. A secretária escolhe o **tipo**, e o
fim da consulta é calculado — nunca digitado.

O tamanho de célula que serve a todas as durações é o **maior divisor comum**
delas: 80 e 40 dão 40. A tela sugere esse valor ao salvar as durações.

`AppointmentType` ganhou `return_visit` ("Retorno") e `follow_up` passou a se
chamar **"Seguimento"**. Eram coisas diferentes na sua descrição com o mesmo
rótulo, e sem separá-las não havia como declarar duas durações.

## Nada é materializado

Publicar a agenda por um ano **não** cria trinta mil linhas de horário. A
grade é calculada das regras, dos bloqueios e das reservas, a cada abertura
da tela. Consequências que importam:

- mudar a regra passa a valer imediatamente, sem regeneração;
- não existe o estado em que a agenda materializada e a regra discordam;
- "publicar por um ano" é só `ends_on` na regra semanal.

Medido: 2.039 horários oferecidos num ano de segunda, terça e quinta — sem
uma linha de horário no banco.

## Ordem de precedência

1. **bloqueio de data** (feriado, férias, bloqueio) tira o horário mesmo
   dentro da janela semanal — é o "exceção de data prevalece sobre regra
   semanal" do RF-06.02;
2. **atendimento extra** acrescenta janela fora da grade (o mutirão numa
   quarta em que você não atende);
3. **reserva** marca a célula — e a célula ocupada continua **visível**,
   porque esconder o horário reservado faria a secretária achar que você não
   atende naquela hora.

## Feriados: calculados, e a decisão é sua

Os nacionais são **calculados**, não baixados. Os fixos são fixos por lei; os
móveis derivam da Páscoa por aritmética (algoritmo gregoriano anônimo):
Carnaval em −47, Sexta-feira Santa em −2, Corpus Christi em +60. Isso vale
para qualquer ano, funciona sem rede e não depende de uma API continuar no
ar — numa agenda publicada para o ano inteiro, essa diferença importa.

Verificado: Páscoa de 2026 em 05/04 e de 2027 em 28/03; Carnaval de 2026 em
17/02; Corpus Christi em 04/06; e os 14 itens calculam para todo ano de 2024
a 2030.

**Estadual e municipal não são calculáveis** — variam por lei local. Esses
são cadastrados na própria tela, com `recurring` para os de data fixa, então
cadastrar uma vez cobre todos os anos. O feriado municipal só vale no
município e o estadual só na UF, comparados sem acento e sem caixa
("São Paulo" = "SAO PAULO"). O lugar vem do endereço da organização; sem
endereço, só os nacionais se aplicam — que é o correto, e não um chute de
localidade.

**O bloqueio é decisão sua.** A tela lista os feriados que caem em dia de
atendimento e pergunta; nada é bloqueado por conta própria. Marcar fecha a
agenda no dia, desmarcar reabre — atender em feriado acontece (plantão,
mutirão, reposição). Se já houver paciente marcado no dia que você bloqueia,
a reserva **não** é apagada: a mensagem avisa quantas existem, para você
remarcar.

Um detalhe deliberado: **ponto facultativo entra desativado.** Carnaval e a
quarta-feira de cinzas não são feriado nacional — são ponto facultativo.
Ligá-los por conta própria seria o sistema afirmar algo que não pode afirmar.
Eles aparecem na lista para você ativar se quiser.

## O painel da secretaria

Grade da semana, **um médico por vez** — horário livre só quer dizer algo
dentro da agenda de quem vai atender. Cor por estado:

| Cor | Estado |
| --- | --- |
| Branco, com "+ marcar" no hover | Livre |
| Azul claro | Agendado |
| Verde-água | Confirmado |
| Laranja | Chegou / em atendimento |
| Verde | Concluído |
| Hachurado | Fechado — com o motivo escrito na célula ("Congresso") |
| Esmaecido | Já passou |

Célula livre é um `<button>` de verdade: chega por Tab, responde a Enter, e o
navegador dá o foco visível. Uma consulta de 80 min mostra o nome só na
primeira célula; a segunda aparece como continuação, sem repetir o paciente.

**Clicar no horário livre abre o modal de marcação**, com paciente já
cadastrado (busca por nome) **ou** pré-cadastro. Clicar num horário marcado
abre as ações: abrir a ficha, check-in, confirmar, remarcar, trocar o
paciente, cancelar.

Dois modais para toda a grade, e não um por célula: uma semana tem centenas
de horários.

## Pré-cadastro e o check-in

Ao telefone a secretária tem **nome e telefone**. Exigir CPF, endereço e
forma de pagamento naquele momento significa perder o agendamento ou inventar
dado para passar da tela.

Então: `Patient.registration_stage = 'preliminary'`, com nome e um contato
telefônico. O motivo de a data de nascimento faltar fica **escrito** no
cadastro ("Pré-cadastro por telefone; a completar na recepção") em vez de o
campo ficar vazio sem explicação — a regra de "data ou motivo" continua
valendo.

O telefone é obrigatório: pré-cadastro sem contato é um horário que ninguém
consegue confirmar depois.

**No check-in o cadastro completo aparece.** Se o paciente é pré-cadastro, o
botão "Chegou" leva direto para a ficha, com a mensagem dizendo o que falta.
Se já é cadastro completo, leva para o prontuário. A grade e o balcão marcam
o pré-cadastro com um crachá.

## Trocar o paciente de um horário

Acontece: marcar no nome errado, ou ligar o pré-cadastro ao paciente que já
existia. Remarcar e cancelar não resolvem — o horário é o mesmo. A troca
registra o paciente anterior no log e reprograma os lembretes.

## O que o sistema recusa, e como explica

A recusa diz **qual** é o problema, e a distinção importa:

| Situação | Mensagem |
| --- | --- |
| Célula ocupada | "Este horário já está ocupado." |
| Célula livre, duração não cabe | "Um atendimento de 80 minutos não cabe a partir daqui: às 08:40 o horário já está ocupado. Escolha um tipo mais curto ou outro horário." |
| Perto do fim do expediente | "…o atendimento deste dia termina às 14:00." |
| Fora da janela do médico | "Fora dos horários de atendimento deste médico." |
| Feriado bloqueado | O nome do feriado |
| Encaixe sem justificativa | "Encaixe exige justificativa." |

O caso do meio foi corrigido durante a verificação: a mensagem dizia
"horário já ocupado" para uma célula visivelmente livre na tela, o que faz a
secretária desconfiar da agenda em vez de escolher outro tipo.

## Concorrência

Nada disso substitui as duas defesas que já existiam e continuam valendo:
`pg_advisory_xact_lock` por (médico, dia) antes de validar, e a
`ExclusionConstraint` sobre (médico, intervalo) no banco. Duas secretárias
clicando no mesmo horário produzem no máximo uma reserva comum (RF-06-A).

A checagem de disponibilidade cobre o que a constraint **não** tem como
saber: feriado, férias, horário fora do expediente.

## Verificação executada

**83 casos, 0 falhas**, reproduzindo exatamente a agenda que você descreveu.

| Verificação | Resultado |
| --- | --- |
| Feriados calculados | Páscoa 2026 = 05/04; 2027 = 28/03; Carnaval 17/02/2026; Corpus Christi 04/06/2026; 14 itens de 2024 a 2030 |
| Grade publicada | Seg e ter 08–18 (15 células de 40 min), qui 08–14 (9 células), qua vazia, vigência de 1 ano |
| Onde cabe cada tipo | retorno de 40 em 15 pontos; primeira consulta de 80 em 14 |
| Duração | reserva de primeira consulta gravou 1:20:00 sem ninguém digitar o fim |
| Ocupação | a consulta de 80 min ocupa 2 células; só a primeira mostra o nome |
| Sobreposição | o mesmo horário e a segunda metade da consulta longa recusados |
| Fora da grade | 19h de segunda e qualquer hora de quarta recusados |
| Feriado | sugere sem bloquear; bloquear fecha o dia com o motivo; desmarcar reabre |
| Feriado local | municipal vale em "SAO PAULO" e "são paulo", não em Campinas; estadual só na UF; recorrente expande para outro ano |
| Bloqueio | tira a manhã de terça e deixa a tarde livre; atendimento extra abre a quarta |
| Pré-cadastro | criado com nome e telefone, motivo escrito, contato gravado, sem telefone é recusado |
| Check-in | leva para a ficha completa quando é pré-cadastro, com a mensagem explicando |
| Troca de paciente | troca sem mexer no horário |
| Encaixe | sem justificativa recusado; com justificativa passa sobre horário ocupado |
| Cobertura | "publicada até 14/09/2027, ~2.039 horários, Seg · Ter · Qui" |
| Telas | grade, dia, mês, configuração e balcão renderizam; célula livre clicável, fechada com motivo, legenda, pré-cadastro sinalizado |
| Regressão | 72 templates, 30 páginas, 187 casos anteriores — 0 falhas |

Percurso real no navegador: grade com a semana semeada, clique no horário
livre abrindo o modal com "07/09/2026 às 10:00" e "O fim é calculado da
duração deste tipo — 80 min", busca de paciente por nome, envio, e a recusa
correta quando os 80 min não caíam.

## Dois bugs encontrados na verificação

1. **Atendimento extra não abria dia sem regra semanal** — que é exatamente
   o caso do mutirão numa quarta em que o médico não atende. A grade voltava
   vazia porque o tamanho de célula vinha só das regras.
2. **A recusa por duração mentia** — dizia "horário já ocupado" para uma
   célula livre.

## Pendências declaradas

- **As rotas da agenda mudaram para português** (`/dia/`, `/mes/`,
  `/balcao/`, `/configurar/`, `/reservar/`). Os nomes de rota (`scheduling:day`
  etc.) foram preservados, então nenhum link interno quebrou; um favorito
  antigo, sim.
- **A grade não tem arrastar-e-soltar** para remarcar. Remarcar é por
  formulário, com os horários livres listados. Arrastar numa grade de
  centenas de células precisa de tratamento de toque e de acessibilidade que
  não cabia nesta rodada.
- **Lembretes de 24 h e 2 h** continuam como estavam (RF-06.04, já
  implementado); a agenda nova reprograma corretamente ao remarcar e ao
  trocar o paciente.
- **A tela de feriados não guarda "decidi atender nesse dia"**: ela mostra o
  estado atual (bloqueado ou não) e conta quantos seguem abertos. Reabrir não
  desfaz sua escolha, mas também não distingue "ainda não decidi" de "decidi
  atender". Se isso incomodar na prática, é uma coluna a mais.
