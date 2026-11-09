# Primeira consulta, seguimento e texto livre (1.41)

Pedido do Dr. Fernando em 2026-11-09. O atendimento estruturado tinha uma
tela só, com **queixa principal** e **história da doença atual** na primeira
aba. Num retorno, os dois campos não têm o que receber: a queixa e a história
se escrevem uma vez, na primeira consulta, e o que se escreve depois é a
**evolução**. Com a tela única, o médico escrevia a evolução dentro da
história, ou repetia a queixa de meses atrás para passar pela finalização.

## O que existe agora

| Tipo | Botão (`kind`) | Tela | Primeira aba |
| --- | --- | --- | --- |
| Primeira consulta | `structured` | estruturada | **História**: queixa, história, antecedentes, hábitos, consanguinidade |
| Seguimento e retorno | `seguimento` | estruturada | **Evolução**: evolução, antecedentes, hábitos, consanguinidade; ao lado, a queixa e a história da primeira consulta, só para leitura |
| Texto livre | `free_text` | uma página | texto, **escalas**, medicação, impressões e conduta, hipóteses |

As outras cinco abas do estruturado (medicação, exame, resultados,
hipóteses, conduta) são as mesmas nos dois tipos estruturados.

## Decisões, e a alternativa recusada de cada uma

**`estrutura` ao lado de `kind`, e não um terceiro `kind`.** `kind` decide
qual tela se desenha, e é lido em vinte e tantos lugares: o roteiro de exame,
a cópia da consulta anterior, o resumo, a IA, a exportação, a âncora dos
adendos. Um `kind` novo faria cada um desses lugares cair no ramo errado sem
aviso (o seguimento seria tratado como "não estruturado"). O seguimento é
estruturado em tudo, e só a primeira aba muda. `EstruturaDoAtendimento` está
em `clinical/models.py`.

**O hash dos finalizados não pode mudar.** `compute_content_hash` acrescenta
a evolução **só quando há texto**. Todo atendimento anterior tem a evolução
vazia e recalcula exatamente o valor gravado no fechamento. A alternativa,
acrescentar sempre, mudaria o recálculo de todos os finalizados (o
separador `|` a mais) e faria a conferência de integridade acusar adulteração
em todo o acervo. `check_primeira_e_seguimento` §1 confere contra os
finalizados do banco.

**O botão continua mandando `kind`.** `structured` e `free_text` são os
valores da 1.40, e o formulário aberto antes da publicação continua abrindo o
que pedia. O seguimento é o valor novo, `seguimento`, traduzido em
`clinical/estrutura.py::abertura`. Valor desconhecido abre primeira consulta:
errar para o lado de pedir mais registro é o erro aceitável.

**Um botão dividido, e não três botões nem um seletor.** Com três botões, a
barra da ficha passava de seis e o nome do paciente quebrava em três linhas.
Com um seletor puro, o caso comum (o retorno de quem já foi atendido) custaria
um clique a mais, que foi o motivo de o texto livre nascer como botão. O
botão dividido abre o tipo sugerido num clique, e a seta mostra os três com
uma linha de explicação cada.

**A sugestão olha a agenda antes do histórico.** O horário de hoje com
check-in, se houver um só: a secretária já marcou ali primeira consulta,
seguimento ou retorno. Sem ele, paciente com atendimento finalizado nesta
clínica está em seguimento, e sem nenhum é primeira consulta. Procedimento e
"outro" não dizem nada e caem no histórico. A sugestão nunca é gravada, quem
decide é o clique.

**No celular, os três empilhados, sem menu suspenso.** Abaixo de 768px as
ações da página ficam num painel lateral que rola. Um menu suspenso dentro
dele sai cortado, e por isso ali os três aparecem como botões largos, com a
explicação e o sugerido em destaque.

**A troca de tipo só quando nada some.** O tipo errado pode ser trocado
enquanto o atendimento está aberto (`clinical:estrutura`, só por POST). A
troca é recusada se o campo que deixa de aparecer tem texto, com a recusa
dizendo o que fazer: seguimento com evolução não vira primeira consulta, e
primeira consulta com queixa ou história não vira seguimento. Texto gravado e
não desenhado é o defeito que as impressões tiveram antes da 1.20. A troca
vai para a trilha (`clinical.encounter_estrutura_trocada`).

**A queixa e a história da primeira consulta, ao lado da evolução.** Aparece
a mais recente estruturada com uma das duas escritas, de qualquer médico da
clínica. É leitura, como a gaveta da consulta anterior, e não cópia: nada vai
para o atendimento de hoje.

**A cópia da consulta anterior não muda.** Ela já não copiava queixa nem
história ("aquilo é do dia") e também não copia a evolução, pelo mesmo
motivo. Conduta, impressões, hipóteses e medicação continuam vindo para
revisão, entre os três tipos.

## Escalas no texto livre

O texto livre recebe o mesmo bloco de escalas do estruturado
(`templates/exams/scales.html`, como cartão numerado). A razão é a série
temporal: `clinical/series.py` lê o achado `escala.<código>` de **todo**
atendimento do paciente, sem olhar o tipo. Com a escala disponível no texto
livre, o retorno rápido entra na mesma linha do gráfico de evolução que a
consulta estruturada, e a progressão do paciente não tem buraco porque um
retorno foi escrito corrido.

Duas consequências:

- gravar a escala volta para `#escalas` no texto livre e para `#tab-exame` no
  estruturado. Voltar para a âncora do outro tipo deixaria a página no topo,
  longe do escore recém-gravado;
- o formulário da escala no texto livre salva antes o texto do atendimento
  (`data-nd-save-encounter-before-submit`, o mesmo contrato da medicação e da
  hipótese). Aplicar uma escala no meio da consulta não pode custar o
  parágrafo que ainda não tinha sido salvo.

## O código do segundo fator em casas

`static/duralux/nd-otp.js` desenha seis casas sobre o campo `data-nd-otp="6"`.
**O campo continua sendo um só**: ele fica por cima das casas, transparente,
com o mesmo nome, e as casas só mostram o que está nele. A alternativa comum,
seis campos de um dígito, quebra três coisas:

- o gerenciador de senhas e o preenchimento automático do celular preenchem
  **um** campo `one-time-code` e param no primeiro;
- colar "123 456" exige código para redistribuir os dígitos, e o espaço vira
  dígito errado;
- o leitor de tela anuncia seis campos, cinco deles sem rótulo.

Onde o código de recuperação também vale (entrar, reconfirmar, resetar o MFA
de um colega), `data-nd-otp-recuperacao` acrescenta **Usar um código de
recuperação**, que devolve o campo comum sem filtro de dígitos. Sem
JavaScript, o campo aparece como sempre e o servidor recebe o mesmo `code`.
O campo transparente fica em 16px, pelo mesmo motivo do bloco de toque: com
menos que isso, o Safari do iPhone dá zoom ao focar.

## Verificação

`checks/check_primeira_e_seguimento.py`, dentro de uma transação desfeita.
O roteiro cobre:

- o hash: igual ao da 1.40 sem evolução, diferente com ela, e os finalizados
  do banco recalculando igual;
- os três botões e o valor desconhecido;
- a tela do seguimento: a aba, os campos, a primeira consulta ao lado e o
  autosave;
- a finalização pedindo a evolução;
- a troca de tipo, com as recusas, só por POST e na fronteira entre
  clínicas;
- a sugestão: agenda, histórico e procedimento;
- as duas portas, o sugerido e a secretária sem o botão;
- as escalas no texto livre: o cartão, a âncora, o achado e a série do
  gráfico com os dois tipos;
- a evolução lida pela IA, pela exportação, pelo resumo, pela gaveta e pelo
  descarte;
- o código em casas nas telas que o pedem.

`check_texto_livre` passou a contar um formulário que salva o texto antes por
escala na tela, e `check_idioma` registra a recusa nova (`TrocaRecusada`).
