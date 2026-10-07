# Intervalos, naturalidade, a ficha na gaveta e o aviso de horário

Sete melhorias pedidas juntas, em 2026-10-07, depois de usar o sistema
com duas clínicas reais. Não são um tema só, mas três perguntas que se
repetem: **o que o médico precisa saber sem parar de atender**, **o que o
paciente precisa saber sem ligar para a clínica**, e **o que o inquilino
precisa poder mudar sozinho**.

---

## 1. Intervalos pontuais na agenda

### O que faltava

Existia `AvailabilityRule.buffer_minutes` — "Intervalo entre
atendimentos" —, que reserva minutos **depois de cada** consulta para a
que estourou o horário não empurrar a seguinte. Não serve para o almoço:
a pausa de relógio cai num horário fixo, e **em horário diferente a cada
dia da semana** — 11h40 na segunda, 12h20 na terça.

`ScheduleBlock` também não servia. Ele é bloqueio de **data** (férias,
congresso, feriado), com `start_at`/`end_at`. Um almoço declarado assim
exigiria 52 linhas por ano, por dia da semana.

### O que entrou

`scheduling.models.RecurringBreak`: dia da semana, hora de início e fim,
vigência e motivo. Modelo próprio por três razões, e a terceira decide:

1. pode haver mais de uma pausa no mesmo dia, e campo não se repete;
2. a pausa não tem célula nem tipo de atendimento — metade de
   `AvailabilityRule` não se aplicaria;
3. **uma pausa pode atravessar duas regras do mesmo dia** (manhã e tarde
   declaradas em envios separados), e pendurada numa delas valeria só
   para metade da grade.

### O ponto único

A subtração mora em **`open_intervals`**, e só nele. Os três caminhos que
respondem sobre disponibilidade passam por ali:

| Pergunta | Função | O que aconteceria se a pausa valesse só na grade |
| --- | --- | --- |
| O que a tela desenha? | `day_grid` | — |
| Onde cabe uma consulta? | `available_slots` | o horário apareceria na lista de livres |
| Dá para marcar aqui? | `fits` | a secretária veria fechado e marcaria assim mesmo |

A célula fechada mostra **o motivo** ("Almoço"): buraco sem explicação na
agenda faz a secretária ligar para o médico perguntando se dá para
encaixar.

A pausa é descontada **antes** de o atendimento extra ser acrescentado.
Abrir um extra das 11h às 13h num dia em que se almoça das 12h às 13h
quer dizer "hoje eu atendo até as 13h" — e a ordem garante isso.

### A tela

Bloco recolhido em "Dias e horário", com três pares de campos. O texto
diz que vale para os dias marcados, e que **horário de pausa diferente
por dia se publica um dia de cada vez** — exatamente como já se faz com
janelas de horário diferentes.

O formulário recusa quatro coisas, cada uma com mensagem própria porque
cada uma se corrige de um jeito diferente: fim antes do início, meio
intervalo preenchido, intervalo fora da janela de atendimento (gravá-lo
seria gravar algo sem efeito, e a pessoa sairia achando que configurou) e
dois intervalos sobrepostos.

Substituir a grade **encerra** as pausas daqueles dias em vez de
apagá-las, pela mesma razão das regras: a agenda de ontem continua
reconstruível como foi — inclusive o almoço de ontem.

---

## 2. Naturalidade do paciente

Não existia. Entra como três campos na Identificação: país, cidade e UF
de nascimento. Em neurologia a procedência importa clinicamente — Chagas,
neurocisticercose, endemias regionais mudam a lista de hipóteses — e é
dado de identificação em relatório e perícia.

**Texto livre, com catálogo sugerindo.** `birth_city` é `CharField` e não
chave estrangeira, de propósito: quem nasceu fora do Brasil não está em
lista de município brasileiro, e município que muda de nome reescreveria
a ficha antiga. O catálogo sugere; não impede.

O catálogo é `catalogs.Municipality`, 5.571 municípios do IBGE, carregado
por `import_municipios` **no worker** (trabalho externo é do worker, §2).
A busca ignora acento reaproveitando `normalize_for_search` — a mesma
normalização da importação, porque duas que divergem fazem a busca mentir
em silêncio.

**A instalação que nunca rodar o comando continua funcionando**: a busca
devolve lista vazia, o `<datalist>` fica sem opções, e o campo segue
aceitando o que se digita.

### A migration que não retroescreve

`birth_country` tem `default='BR'` no modelo, mas a coluna nasce com
`''` nas linhas existentes (`preserve_default=False`). Preencher 'BR' em
2.231 fichas afirmaria, em nome de pacientes reais, uma naturalidade que
ninguém declarou. O padrão vale para a ficha **nova**, onde é o palpite
certo; para a antiga, vazio é a verdade: não se perguntou.

---

## 3. A ficha do paciente numa gaveta, durante o atendimento

No meio da evolução aparece a pergunta que não é clínica: qual o
endereço, qual o convênio, de onde ele é, qual o telefone do filho. O
caminho era abrir outra aba — ou, pior, sair do atendimento **não
salvo**.

`_gaveta_ficha.html` usa a mecânica que já existia para a consulta
anterior: vem renderizada com a página e escondida por CSS, em vez de
buscada ao abrir. São campos que já estão no banco, e quem abre está no
meio de uma frase.

**É leitura, e não tem formulário** — um formulário ali seria um
formulário dentro da página do atendimento, e enviar um levaria o outro
junto. A ficha completa abre em outra aba.

O JavaScript da gaveta foi **generalizado** para duas: eram uma só,
endereçada por id fixo, e acrescentar a segunda duplicando
abrir/fechar/foco/Esc deixaria a segunda cópia sendo a que esquece de
devolver o foco. `Alt+P` segue na consulta anterior; `Alt+D` abre os
dados.

---

## 4. Aviso automático de horário marcado, remarcado e cancelado

### O que faltava

Havia o lembrete automático (24h e 2h antes) e a confirmação que a
secretária manda à mão. **Marcar e cancelar não avisavam ninguém** — quem
tivesse a consulta cancelada descobria ao chegar na clínica.

### O que entrou

Três eventos, consumidos por `communications`. `appointment_reserved` já
existia e era consumido pelo CRM: o aviso ao paciente entrou como
**segundo consumidor do mesmo tópico**, porque "reservado" e "marcado"
são o mesmo fato e dois eventos para o mesmo fato divergem. Cancelar e
remarcar ganharam tópico próprio.

**Só e-mail.** SMS custa crédito, é recurso de plano, e o aviso
automático dispararia em todo agendamento de toda clínica. O canal
continua disponível pela confirmação manual, que é quando alguém decidiu
gastar.

Os contatos são os de `confirmation_contacts`, que não exigem opt-in: é
mensagem transacional sobre um horário que a própria pessoa marcou, no
endereço que ela deu — inclusive o do pré-cadastro por telefone, que é
quem mais precisa do aviso.

Idempotente pela chave da entrega: o dispatcher pode reentregar o evento,
e o paciente não recebe dois e-mails do mesmo cancelamento. Versão nova
do agendamento é aviso novo — cancelar depois de remarcar são dois fatos.

### O corpo da mensagem

**`Local` passou a ser o endereço.** Era o nome da clínica, que o
paciente já sabe e que não o leva a lugar nenhum:

```
  Data e hora .... 12/10/2026 às 11:00
  Profissional ... Dr. Fulano
  Local .......... Consultório Dr Fulano
                   Rua Cubatão, 86 - Cj 409 — Vila Mariana — São Paulo/SP — 04013-000
  Como chegar .... https://maps.google.com/...
  Telefone ....... (11) 3287-3247
```

O nome fica na primeira linha porque é o que está escrito na porta. Sem
endereço cadastrado, o texto **diz isso** em vez de deixar o paciente
supor que o nome basta. O CEP saiu da máscara — era `04013000`.

Os três casos repetem data, profissional e local, inclusive o
cancelamento: sem eles, quem tem duas consultas marcadas não sabe qual
caiu.

---

## 5. Nome fantasia editável pelo inquilino

`Tenant.trade_name` existia e não estava em tela nenhuma. A clínica que
quisesse corrigir o nome que o paciente lê na receita precisava pedir a
quem administra a instalação.

Entrou em Identidade da clínica. A distinção que a tela agora faz:
**razão social e CNPJ são o que a clínica é perante a Receita**, chegam
pelo convite e não se editam ali — editá-los faria o contrato de adesão
apontar para um nome que ninguém assinou. **O nome fantasia é como ela se
apresenta ao paciente**, e é dela.

A troca entra na trilha com valor anterior e novo: o nome que sai na
receita é coisa que alguém vai querer datar depois.

---

## 6. SMTP, SMS e IA por inquilino — verificado

Pedido como verificação, e a cadeia estava correta. Agora está **provada**
em `check_servicos_do_inquilino.py`, nos três serviços e nos dois
sentidos:

| Serviço | Sem configuração | Com a sua | Desligando |
| --- | --- | --- | --- |
| E-mail | instalação | a dela (remetente e, se houver, servidor) | **volta à instalação** |
| SMS | instalação | a chave dela | recusa explícita, se tem chave; volta à instalação, se não tem |
| IA | instalação | o provedor dela | **volta à instalação** |

Duas assimetrias deliberadas, que o roteiro fixa:

- **desligar o canal de SMS com chave gravada é recusa, não retorno ao
  padrão.** A clínica que desliga o SMS está dizendo "não mande SMS", não
  "mande pela conta de vocês";
- **configuração pela metade cai no padrão** em vez de quebrar: a IA
  exige ligada, com chave e com modelo (`is_usable`), porque faltando
  qualquer uma o pedido falharia no provedor — e a falha lá chega ao
  médico como erro genérico no meio do atendimento.

E o corte por plano continua vindo **antes** da chave da clínica: o
Gratuito não manda SMS nem com chave própria.

### O que não mudou, e por quê

**E-mail não é recurso de plano**, e não virou um. `sms` e `clinical_ai`
são chaves em `plans.py`; e-mail não. Gatear o SMTP por plano tiraria do
Gratuito a verificação de conta, a recuperação de senha e a entrega de
documento — o sistema pararia de funcionar para ele. Se for para cortar
e-mail por plano, é decisão comercial a tomar à parte, não efeito
colateral desta entrega.

---

## Verificação

Três roteiros novos:

- `check_aviso_de_horario.py` (7 seções) — o Local como endereço, os três
  casos, a falta de endereço declarada, os eventos emitidos e consumidos,
  a idempotência **com volume criado antes** (sem um contato com e-mail,
  as asserções passariam sobre lista vazia), e o aviso não saindo da
  requisição;
- `check_servicos_do_inquilino.py` (6 seções) — a tabela acima, mais o
  nome fantasia e os campos que **continuam fora** do formulário
  (`legal_name`, `cnpj`, `slug`, `plan`);
- `check_intervalos_e_ficha.py` (8 seções) — a pausa recortando os três
  caminhos, as quatro recusas do formulário, a vigência, a naturalidade
  nos três estados, e a gaveta sem formulário.

**96 roteiros, nenhuma falha.** Um defeito real foi pego pela bateria ao
escrever isto: a tabela da gaveta sem `.table-responsive`, que no celular
empurraria a página para o lado — `check_mobile` reprovou.
