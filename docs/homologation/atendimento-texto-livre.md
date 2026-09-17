# Atendimento em texto livre, ao lado do estruturado

> **Homologado na pilha local (2026-09-17).** Evidência de
> `checks/check_texto_livre.py` (11 seções, `EXIT=0`) e da suíte inteira.

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

Conduta, impressões e hipóteses (CID) são oferecidas na consulta seguinte
do mesmo paciente, para aceitar ou rejeitar uma a uma — o mecanismo de
`carry_forward` que já existia para conduta e CID, agora com as impressões.

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

## Três defeitos que a construção produziu, e como apareceram

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

`checks/check_texto_livre.py`, 11 seções, `EXIT=0`:

- [x] os dois tipos abrem, e cada um na **sua** tela (o estruturado sem
      `id_free_text`, o livre sem `tab-exame`)
- [x] `kind` desconhecido vira estruturado, e não um estado inválido
- [x] a página tem texto, impressões, conduta, medicação, CID e emitir
      documento — e **zero** formulários aninhados
- [x] o que se digita é gravado, e o atendimento passa a "em andamento"
- [x] a finalização do texto livre não pede queixa nem história; vazio, ela
      pede o texto do atendimento e a conduta
- [x] abrir e finalizar depois: `finalized_at` gravado, registro imutável
- [x] conduta e impressões viajam do texto livre para o estruturado **e**
      do estruturado para o texto livre
- [x] aceitar um item copiado grava mesmo o valor
- [x] a grade traz abertura, fechamento, "em aberto" e ordena pelas duas
- [x] ordenação forjada pela URL não quebra nem vaza ordenação por coluna
      que a tela não mostra
- [x] texto livre e impressões entram no hash de conteúdo
- [x] o resumo imprimível sai certo nos dois tipos
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

## O que ficou de fora

- **Não há conversão entre os tipos.** Um atendimento nasce estruturado ou
  livre e assim fica. Converter significaria decidir o que fazer com o
  roteiro de exame já preenchido, e a resposta certa depende do caso —
  copiar conduta e impressões para um atendimento novo já cobre o uso real.
- **O texto livre não é analisado.** Nada lê aquele texto para extrair CID
  ou medicação: o que o sistema entende continua vindo dos campos
  estruturados, de propósito.
