# Contagem no mês, remarcação visual e confirmação por SMS/e-mail

Três pedidos, e cada um trouxe uma decisão que vale registrar.

## 1. Contagem de livres e agendados no mês

Cada dia do calendário passa a mostrar **quantos horários estão livres** e
**quantos pacientes estão agendados**, e o cabeçalho traz o total do mês.

Duas escolhas dentro disso:

**"Agendados" conta pacientes, não células.** Uma primeira consulta de 80
minutos ocupa duas células da grade e continua sendo um paciente. Contar
células faria a agenda parecer duas vezes mais cheia do que está.

**Dia sem grade não recebe crachá nenhum.** Um "0 livres" em sábado e
domingo enche o calendário de informação que não é informação. Dia de
atendimento sem vaga mostra "lotado"; dia bloqueado mostra "fechado".

O custo estava em montar 42 grades para desenhar um mês — seriam mais de cem
consultas ao banco. `availability.month_summary` carrega regras, bloqueios e
reservas **uma vez** e monta as grades em memória: medido, **3 consultas
para 42 dias**.

## 2. Remarcar olhando o mês

Antes, remarcar pedia dois `datetime` digitados. Para saber se 14h de quinta
estava livre era preciso sair da tela, olhar a agenda e voltar — que é
exatamente o que não se pode fazer com o paciente na linha.

Agora a tela de remarcação é o calendário do mês:

- cada dia mostra a contagem de livres, e **só dia com vaga é clicável** —
  oferecer um dia lotado ou já passado só gera um clique que não leva a nada;
- clicar num dia lista, ao lado, os horários em que **cabe esta consulta**.
  Uma consulta de 80 minutos aparece só onde há duas células livres seguidas:
  na quinta de 8h às 14h, isso dá 8 horários, não 9;
- clicar num horário remarca. A **duração não é editável**: remarcar é mudar
  o quando, não o quanto — e digitar o fim à mão seria a chance de encurtar
  a consulta sem querer.

O campo de data e hora manual continua existindo, recolhido: serve ao encaixe
fora da grade, que a lista de horários livres não oferece por definição. E
continua valendo a checagem de disponibilidade, o controle de versão
(`row_version`) e a `ExclusionConstraint` do banco.

## 3. Confirmação por SMS e por e-mail

No modal do paciente, na agenda da semana, entrou o bloco **"Confirmar com o
paciente"** com dois botões. O modal diz **para onde a mensagem vai** antes
do clique ("SMS para 11977771234 · e-mail para marta@example.com"), e o botão
some quando falta o contato — um botão que sempre devolve erro é pior que a
ausência dele.

### A decisão que precisa ser explícita

Os lembretes automáticos (24 h e 2 h) exigem **opt-in e verificação prévia**
do contato. A confirmação manual **não exige**, e isso é deliberado:

> A secretária acabou de falar com a pessoa e está confirmando o horário no
> número que ela mesma passou. É mensagem transacional, pedida por quem
> atende, para quem marcou — não é disparo automático nem comunicação de
> marketing.

Exigir verificação prévia inviabilizaria justamente o caso do pré-cadastro
por telefone, que é o motivo de o canal existir. Continua valendo: contato
com validade vencida sai da lista, e **a mensagem não leva conteúdo
clínico** — data, hora, profissional e clínica, com o rodapé dizendo isso.

**Reenvio é permitido**, e cada envio é uma entrega própria, numerada:
mensagem não chega, e a secretária precisa poder mandar de novo. O histórico
mostra quantas vezes se tentou em vez de sobrescrever a tentativa anterior.

**Canal desligado avisa, não finge.** Com `SMS_ENABLED=False` ou o canal
desativado na clínica, a tela diz que nada foi enviado — a entrega fica
marcada, não some.

## 4. A área do gestor

Nova tela em **Administrativo → Mensageria**, para `owner` e `manager`. Quem
não administra a clínica recebe 404, não 403: não precisa saber que a tela
existe. A verificação é por papel no vínculo ativo, consultado no banco a
cada requisição — papel revogado deixa de valer imediatamente.

### SMS (SMSDEV)

A chave da API fica **no banco e cifrada**, não em variável de ambiente:
quem a tem é o gestor da clínica, e cada clínica tem a sua. A chave global do
deploy continua valendo como padrão para quem não configurou a própria.

Três comportamentos que importam:

- **a tela nunca devolve a chave.** Mostra a máscara (`•••••••7654`) para o
  gestor conferir que a gravada é a certa;
- **campo em branco não apaga a chave.** Reabrir a tela para mudar o nome do
  remetente e salvar não pode zerar a credencial;
- **"Testar a chave" consulta o saldo** no provedor — confirma que a chave é
  aceita sem gastar crédito nem mandar mensagem para o telefone de ninguém.

A chave também **não entra no log de auditoria**, nem mascarada: o log
registra que mudou e quem mudou.

### E-mail por médico

O e-mail que o paciente recebe deve vir do consultório de quem o atende, e
numa clínica com vários médicos isso são vários remetentes. Cada médico tem
nome, endereço, responder-para e, **opcionalmente**, servidor SMTP próprio.

Servidor próprio é opcional de propósito: um médico pode querer apenas que o
e-mail saia no nome dele, pelo servidor da instalação. Só quando há host
informado é que se abre uma conexão SMTP separada.

A senha do SMTP segue a mesma regra da chave de SMS: cifrada, mascarada na
tela, e em branco mantém. "Testar a conexão SMTP" abre e fecha a conexão sem
enviar e-mail.

Validação: TLS e SSL são alternativos (587 costuma usar TLS; 465, SSL), e a
tela recusa os dois juntos em vez de deixar o envio falhar depois.

### Cifragem

`base/crypto.py` usa o mesmo desenho de envelope do PFX: uma chave de dados
aleatória por segredo cifra o valor, e só ela — nunca o valor — é embrulhada
pela chave-mestra. Isso permite rotacionar a mestra reembrulhando as chaves
de dados.

**A chave-mestra é `SECRETS_MASTER_KEY`, separada da do PFX de propósito**:
comprometer a chave de SMS não deveria dar acesso ao certificado de
assinatura. Enquanto ela não for definida, cai na `PFX_MASTER_KEY` para a
instalação existente continuar funcionando — **e a tela avisa que estão
compartilhadas**. Sem chave-mestra nenhuma, a tela recusa guardar o segredo
em vez de gravá-lo em claro.

Segredo que não abre com a chave atual levanta erro em vez de virar string
vazia: tratá-lo como vazio faria o sistema chamar o SMSDEV com chave em
branco e reportar erro do provedor em vez do erro real.

### Log de entregas

Tela com as últimas 100 entregas: canal, destino, origem, estado e tentativas
— **sem o texto da mensagem**. É o suficiente para diagnosticar "o SMS não
chegou" sem transformar a tela num arquivo de mensagens do paciente.

## Verificação executada

**69 casos, 0 falhas.**

| Verificação | Resultado |
| --- | --- |
| Contagem no mês | segunda 15 livres; quinta 9; quarta sem grade; após uma consulta de 80 min, **1 agendado** e 13 livres |
| Custo da contagem | **3 consultas ao banco para 42 dias** |
| Tela do mês | mostra livres e agendados por dia, total do mês e a legenda explicando que "agendados" conta pacientes |
| Remarcação | abre o calendário; escolher a quinta lista **8 horários** (9 células, 8 comportam 80 min); clicar remarcou para 17/09 10:00 preservando 1:20:00 |
| Remarcação — recusas | versão desatualizada e horário fora do expediente recusados com a explicação |
| Cifragem | cifra e decifra; o texto cifrado não contém o segredo; máscara mostra só o fim; segredo sem chave embrulhada levanta erro |
| Permissão | secretaria recebe **404** na mensageria; gestor entra |
| Chave do SMS | salva cifrada; decifra correta; a tela não devolve a chave, só a máscara; em branco mantém; ativar sem chave é recusado |
| Provedor | usa a chave da clínica; canal desativado na clínica bloqueia com a explicação |
| E-mail por médico | remetente salvo e cabeçalho montado; servidor próprio com senha cifrada; TLS+SSL recusado; senha em branco mantém |
| Confirmação por e-mail | enviada com o remetente do médico, data, profissional e clínica, e o aviso de que não contém informação clínica |
| Reenvio | segunda entrega numerada, não sobrescreve |
| SMS desligado | avisa sem fingir que enviou; a entrega fica marcada |
| Sem contato | explica o que falta cadastrar |
| Telas | modal com os botões e o destino; log de entregas sem o texto da mensagem |
| Regressão | 75 templates, 30 páginas, 270 casos anteriores — 0 falhas |

Percurso real no navegador: mês com "6 livres / 1 agendado" por dia,
remarcação clicando no dia 17 e vendo os 8 horários, tela de mensageria com
o aviso da chave-mestra compartilhada, e o modal do paciente mostrando
"SMS para 11977771234 · e-mail para marta@example.com".

## Pendências declaradas

- **A chave da SMSDEV é sua para colocar** — na tela de Mensageria, não pelo
  chat. E defina `SECRETS_MASTER_KEY` no deploy: hoje a instalação está
  usando a chave do PFX, e a tela avisa isso.
- **`SMS_ENABLED` e `EMAIL_ENABLED` seguem `False`** nesta instalação. A
  configuração pode ser feita e testada desde já, mas nada sai até isso mudar
  no deploy (P-03).
- **A resposta do paciente ao SMS não é lida.** A mensagem pede "confirme
  respondendo", mas o retorno não é processado — quem marca como confirmado é
  a secretária, pelo botão. Ler a resposta exige webhook do provedor e é
  trabalho próprio.
- **O e-mail é texto puro**, sem HTML. Suficiente para confirmação de
  horário, e evita a discussão de rastreamento por imagem.
