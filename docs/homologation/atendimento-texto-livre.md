# Atendimento em texto livre, ao lado do estruturado

> **Homologado na pilha local (2026-09-17).** Evidência de
> `checks/check_texto_livre.py` (13 seções, `EXIT=0`) e da suíte inteira.

> **Correção de 27/09/2026.** Incluir uma medicação ou hipótese agora salva
> primeiro o texto livre, as impressões e a conduta que ainda estiverem na
> tela. O POST auxiliar só prossegue depois dessa gravação; se ela falhar, o
> item não é incluído e o texto permanece no navegador com uma mensagem
> explícita. Assim, o recarregamento não apaga o que estava sendo digitado.

## Por que existe

O prontuário estruturado é bom e continua sendo o padrão: queixa, história,
antecedentes, o roteiro de exame com quase 400 itens, escalas. É o que se
quer numa primeira consulta e numa investigação.

Só que nem toda consulta é essa. Retorno de rotina, ajuste de dose,
renovação — o médico com a sala cheia escreve um parágrafo. Obrigá-lo a
percorrer seis abas para isso não faz o registro ficar mais completo; faz o
parágrafo ser escrito em outro lugar, fora do prontuário. **Um prontuário
que só aceita o registro completo acaba recebendo menos registro, não
mais.**

## O que muda, e o que deliberadamente não muda

| | Estruturado | Texto livre |
| --- | --- | --- |
| Corpo da consulta | queixa, HDA, antecedentes, hábitos | uma caixa só |
| Exame neurológico | roteiro de 387 nós + escalas | não tem |
| Tela | seis abas | **uma página** |
| Medicação em uso | estruturada | **a mesma, estruturada** |
| Vem da consulta anterior | conduta, impressões, CID, medicação | **as mesmas quatro** |
| Hipóteses (CID-10) | estruturadas | **as mesmas, estruturadas** |
| Impressões | campo próprio | campo próprio |
| Conduta | campo próprio | **o mesmo campo** |
| Receita, pedido, encaminhamento | sim | **sim, o mesmo botão** |
| Imprimir | resumo do caso | **o mesmo resumo** |
| Abrir hoje, fechar depois | sim | sim |

Medicação e CID continuam **campos**, e não texto, nos dois tipos. É deles
que saem a receita, o alerta e o indicador — texto livre é sobre como se
escreve a consulta, não sobre abrir mão do que o sistema precisa entender.

## O que viaja entre os dois

Conduta, impressões, hipóteses (CID) **e a medicação em uso** são oferecidas
na consulta seguinte do mesmo paciente, para aceitar ou rejeitar uma a uma —
o mecanismo de `carry_forward` que já existia para conduta e CID, agora com
as impressões e com a medicação.

A medicação era uma promessa que o código não cumpria: o próprio
`Medication` dizia, na sua docstring, que "a lista da consulta seguinte é
trazida pela cópia revisada do atendimento anterior (RF-03.04)" — e
`carry_forward` nunca a copiou. A lista pertence ao atendimento, e não ao
paciente, justamente para que o registro de ontem não mude quando o
tratamento de hoje muda; sem a cópia, o preço disso era redigitar tudo a
cada retorno, que é como uma lista de medicação deixa de ser confiável.

Vem só o que está **em uso**. Suspenso e concluído são decisões já tomadas
na consulta anterior, e trazê-los faria o médico recusar as mesmas linhas
todo retorno — uma revisão que se rejeita sempre deixa de ser lida. O item
mostra nome, dose, frequência e indicação numa linha, como se lê numa
receita: o que se decide ali é se aquele remédio continua, e para isso é
preciso ver a posologia junto do nome.

**A cópia funciona nos dois sentidos** porque ela é por campo, e o campo é
o mesmo: a conduta de um atendimento de texto livre chega num estruturado e
vice-versa. Isso não é coincidência de implementação — é a razão de as
impressões serem um campo próprio, e não o último parágrafo do texto livre.
Diluídas no corpo, não haveria o que copiar.

Aceitar um item passou a aplicar o valor **pelo nome do campo**, em vez de
um `if` por campo. O `elif` esquecido era um defeito real que a hipótese já
teve: o item ficava marcado como aceito e nada era copiado.

## Abrir agora, finalizar depois

Já funcionava no modelo (`status` com três estados e `finalized_at`), mas
**a finalização bloqueava o texto livre**: ela exigia queixa principal ou
história da doença atual, campos que essa tela não tem. O resultado seria
pedir uma "justificativa da finalização" em *toda* consulta de texto livre
— e uma trava que se dispara sempre deixa de ser lida e passa a ser
contornada por reflexo.

Agora o requisito é o mesmo — "há registro do que houve?" —, lido no campo
certo de cada tipo. As âncoras da mensagem também: mandar alguém para "a
aba História" numa tela sem abas é mandá-lo procurar o que não existe.

## Uma coluna, na ordem da consulta

A primeira versão punha texto e conduta à esquerda e medicação e CID numa
coluna estreita à direita. Lida como prontuário, ela obrigava o olho a
saltar de um lado para o outro no meio do raciocínio. Agora é **uma coluna
só**, numerada, na ordem em que a consulta acontece:

1. **Texto livre** — o corpo da consulta
2. **Medicações em uso** — estruturadas
3. **Impressões e conduta**
4. **Hipóteses (CID-10)** — estruturadas

O obstáculo era HTML, não estética: medicação e hipóteses trazem `<form>`
próprio, e **formulário não se aninha** — o navegador ignora o interno, e o
botão de incluir medicação passaria a salvar o texto livre. Foi por isso
que a primeira versão empurrou os dois para uma coluna lateral, fora do
formulário do atendimento.

A saída é o atributo `form=` do HTML5: o `<form>` do atendimento é
declarado vazio no alto da página, e cada campo diz a que formulário
pertence. Os campos podem então ficar em qualquer lugar, intercalados com
os outros formulários, e continuam sendo enviados juntos.

A alternativa era quebrar o atendimento em três formulários com um botão de
salvar cada — e salvar o texto perdendo a conduta digitada logo abaixo é
pior do que qualquer arranjo de colunas.

## A ficha do paciente

Mostrava os **cinco últimos** atendimentos e só a data de abertura. Ver o
sexto obrigava a ir ao prontuário, e nada dizia se aquela linha era uma
evolução estruturada ou um texto livre.

Agora traz **todos**, com o tipo em pastilha, abertura e fechamento, e as
duas colunas ordenam — a mesma ordenação do prontuário, pelo mesmo seletor
e pela mesma tabela fechada de campos. Duas consultas paralelas
divergiriam, e a ficha acabaria mostrando uma ordem que o prontuário não
conhece.

A lista rola dentro do cartão: vertical para que a tela não cresça com o
paciente de dez anos de acompanhamento, horizontal porque são seis colunas
e o celular não as comporta lado a lado. O cabeçalho fica preso no topo —
tabela que rola com o cabeçalho junto perde o nome da coluna na terceira
linha. E o link de ordenação volta para a tabela por âncora; sem ela,
ordenar jogava o leitor de volta ao topo da ficha.

## Contato no cadastro do paciente

O cadastro pedia CPF, endereço e carteirinha e **não** pedia o telefone.
Quem cadastrava salvava o paciente e só depois descobria a área de
Contatos, na ficha: o caminho até o dado mais usado da clínica passava por
duas telas.

Celular e e-mail entraram como seção 2 do cadastro e viram um
`PatientContact` de verdade, na mesma transação — o mesmo registro que a
área de Contatos lista e que a agenda lê para confirmar horário. Guardá-los
como campos do paciente criaria um segundo endereço que metade do sistema
não enxergaria.

O que se registra ali é o contato do **próprio paciente**, e a relação diz
isso. Parente, cuidador e representante legal continuam na área de
Contatos, que tem os campos que eles exigem — comprovação da representação,
autorização para receber documentos.

Na edição o bloco não some: some a numeração, e a tela passaria de 1 para
3. Em vez disso ele aponta para a área de Contatos, que é onde a pergunta
"este telefone substitui qual dos contatos?" se responde com a lista na
frente de quem decide.

**Consentimento.** A caixa "pode receber mensagens do atendimento" nasce
marcada, e vale só para o transacional — confirmar o horário que a pessoa
marcou, mandar a receita que ela pediu. Quem deu o telefone no balcão deu
para ser chamado. Divulgação é outra coisa: exige consentimento específico
e destacado (LGPD art. 11, I), não se deduz daquela caixa, e continua
sendo decidida na área de Contatos. O roteiro confere que o cadastro **não**
marca `marketing_opt_in_at` sozinho.

## A grade

Abertura e fechamento são colunas separadas, e **as duas ordenam**. Com
atendimento que se abre num dia e se finaliza em outro, elas deixam de
coincidir: quem procura o que ficou pendente ordena por fechamento, onde o
"em aberto" vem primeiro. A coluna também mostra o tipo do atendimento.

A ordem vem da URL e é validada contra uma tabela fechada, nunca
interpolada na consulta — `order_by` montado com o que chega na URL aceita
`patient__cpf` e vira um oráculo de ordenação sobre colunas que a tela não
mostra. Conferido: `patient__cpf`, `id`, `; DROP TABLE --` e vazio todos
devolvem 200 com a ordem padrão.

Há desempate por abertura: dois atendimentos ainda não finalizados têm o
mesmo `finalized_at` (nulo), e sem o segundo critério a mesma página
recarregada troca duas linhas de lugar.

## Sete defeitos que a construção produziu, e como apareceram

**Formulário aninhado.** A primeira versão da tela punha o parcial de
medicações — que traz um `<form>` próprio — dentro do formulário do
atendimento. HTML não aninha formulário: o navegador ignora o interno, e o
botão de incluir medicação passaria a salvar o texto livre. A tela foi
reestruturada para o `<form>` cobrir só a coluna da esquerda, e o roteiro
passou a conferir aninhamento em vez de confiar na leitura.

**A data do resumo.** O resumo imprimível do texto livre saía com as seis
seções do estruturado vazias, cada uma com "Não registrada" embaixo —
folha cheia de ausência. Agora o corpo escrito substitui a seção História,
e o resto (medicação, hipóteses, conduta, adendos) é o mesmo nos dois.

## O que o roteiro conferiu

`checks/check_texto_livre.py`, 13 seções, `EXIT=0`:

- [x] os dois tipos abrem, e cada um na **sua** tela (o estruturado sem
      `id_free_text`, o livre sem `tab-exame`)
- [x] `kind` desconhecido vira estruturado, e não um estado inválido
- [x] **as duas portas** que abrem atendimento — ficha do paciente e
      prontuário — oferecem os dois tipos, e nenhum template que aponta para
      `clinical:new` escapa da varredura
- [x] a página tem texto, impressões, conduta, medicação, CID e emitir
      documento — e **zero** formulários aninhados
- [x] o que se digita é gravado, e o atendimento passa a "em andamento"
- [x] a finalização do texto livre não pede queixa nem história; vazio, ela
      pede o texto do atendimento e a conduta
- [x] abrir e finalizar depois: `finalized_at` gravado, registro imutável
- [x] conduta e impressões viajam do texto livre para o estruturado **e**
      do estruturado para o texto livre
- [x] aceitar um item copiado grava mesmo o valor
- [x] a medicação **em uso** vem da consulta anterior com posologia, a
      suspensa não vem, aceitar grava a linha com a data de início, e
      aceitar duas vezes não duplica
- [x] a grade traz abertura, fechamento, "em aberto" e ordena pelas duas
- [x] ordenação forjada pela URL não quebra nem vaza ordenação por coluna
      que a tela não mostra
- [x] texto livre e impressões entram no hash de conteúdo
- [x] nenhum card carrega `stretch-full`, e o autocomplete do CID-10 tem os
      três ganchos e devolve resultado de verdade
- [x] o resumo imprimível sai certo nos dois tipos
- [x] a página de texto livre está na ordem texto → medicação → impressões e
      conduta → CID, e os campos estão amarrados ao formulário por `form=`
- [x] a ficha do paciente lista **todos** os atendimentos, com tipo, abertura,
      fechamento, rolagem e ordenação pelas duas datas
- [x] contato informado no cadastro vira `PatientContact`, com o telefone
      sem máscara, aparece na ficha, e **não** marca consentimento de
      divulgação sozinho; telefone de 4 dígitos é recusado
- [x] atendimento de outra clínica responde 404

**O corpo da consulta fora do hash.** `compute_content_hash()` cobre o que o
médico escreveu, é gravado na finalização e aparece na tela e na trilha de
auditoria. Os dois campos novos não estavam nele — e no texto livre o campo
de fora seria o **atendimento inteiro**: ele mudaria sem que a versão gravada
mudasse junto, que é o contrário do que o hash existe para fazer. Entrou no
cálculo, e no roteiro. Atendimento já finalizado não muda: aquele valor está
gravado e nada o recalcula.

**O resíduo que derrubou roteiro alheio.** A primeira versão de
`check_texto_livre.py` deixava atendimentos de texto livre na demonstração, e
`check_resto` — que procura o campo de hábitos no primeiro atendimento aberto
que encontrar — passou a acusar ausência de um campo que o texto livre não
tem, de propósito. Duas correções: `check_resto` agora pede um atendimento
**estruturado**, com ordem explícita (`first()` sem `order_by` deixa a escolha
com o Postgres), e a limpeza do roteiro novo apaga também tudo o que nasceu
para aquele paciente depois que ele começou — não só o que ele lembrou de
registrar numa lista.

**A porta esquecida — e a única encontrada usando o sistema.** Os dois
botões foram postos na ficha do paciente e esquecidos na tela de
**Prontuário**, que tem o seu próprio "Novo atendimento". Quem entra pelo
prontuário não passa pela ficha, e o médico que testou criou um atendimento
sem nunca ver a escolha.

O roteiro não pegou porque exercitava o `POST` com `kind` na mão — provava
que o servidor entende os dois tipos, e nada sobre haver por onde escolher.
Agora ele confere as duas telas renderizadas **e** varre os templates: todo
arquivo que aponta para `clinical:new` precisa trazer os dois valores, de
modo que uma terceira porta nasça coberta. Uma porta sem a escolha não
parece uma porta faltando — parece que o texto livre não existe.

**`instance.pk` não diz se é um cadastro novo.** A chave primária é um UUID
com `default=uuid.uuid4` (`base/models.py`): ela **já vem preenchida** no
objeto que ainda não foi gravado. O guarda "só na criação" foi escrito como
`if self.instance.pk: return None` e desligou o contato exatamente no caso
para o qual ele existe — e em silêncio, porque o paciente era criado
normalmente, só sem contato. A pergunta certa é `_state.adding`. O mesmo
engano estava em dois pontos antigos do `PatientForm`, onde só custava
consultas inúteis a cada abertura do cadastro; foram corrigidos junto.

**`stretch-full` numa coluna única.** Os quatro cards nasceram com
`card stretch stretch-full`, copiado do layout de duas colunas. Aquela
classe é `height: calc(100% - 24px)` e serve para cards **lado a lado**
ficarem da mesma altura; empilhados numa coluna, `100%` é a altura da
coluna inteira, e cada card passa a querer a altura dos quatro somados. A
página ficou com telas de espaço vazio entre uma seção e a seguinte — e o
sintoma relatado foi exatamente esse: "precisa rolar muito até encontrar".

**O CID sem autocomplete.** `cid.js` acha o campo de busca, sobe até o
`<form>` e desiste se não houver `data-cid-url` ali. A tela de texto livre
nasceu sem o atributo e com o campo de busca renderizado pelo parcial
genérico — sem o campo oculto `diagnosis_code_id`, que é onde o script
grava qual código do catálogo foi escolhido. A busca virava um campo de
texto mudo, e nada na tela reclamava. O roteiro agora confere os três
ganchos **e** que o endereço devolve resultado de verdade: o atributo estar
na página não prova que a busca responde.

## O que ficou de fora

- **Não há conversão entre os tipos.** Um atendimento nasce estruturado ou
  livre e assim fica. Converter significaria decidir o que fazer com o
  roteiro de exame já preenchido, e a resposta certa depende do caso —
  copiar conduta e impressões para um atendimento novo já cobre o uso real.
- **O texto livre não é analisado.** Nada lê aquele texto para extrair CID
  ou medicação: o que o sistema entende continua vindo dos campos
  estruturados, de propósito.
