# Aderência ao celular

> **Auditado num navegador de verdade (2026-09-18).** 30 telas do produto em
> quatro tamanhos — 390×844 (iPhone), 360×740 (Android comum), 844×390
> (celular deitado) e 768×1024 (tablet em retrato) —, medindo transbordo
> horizontal, tamanho de fonte efetivo dos campos e altura real dos alvos de
> toque. `checks/check_mobile.py` trava o resultado.

## O que já estava certo

Vale dizer primeiro, porque mudou o tamanho do trabalho: **nenhuma tela
transbordava na horizontal**. O tema é Bootstrap, as 48 tabelas do produto
estão embrulhadas em `.table-responsive`, o `viewport` está declarado, o
menu lateral entra e sai pelo botão de sanduíche, a barra de ações da página
já virava painel deslizante abaixo de 768px, e a janela do chat já ocupava a
tela inteira e desistia de arrastar e redimensionar no celular.

Não havia, portanto, um problema de layout. Havia um problema de **tamanho
do que se toca e do que se lê**.

## O achado principal: o Safari dava zoom a cada campo

Os campos do tema renderizam a **13,5px**. O Safari do iPhone amplia a
página inteira quando o campo que recebe o foco tem fonte menor que 16px —
e não volta ao sair. Quem preenchia o cadastro de paciente atravessava 28
campos; o prontuário estruturado tem **mais de mil**. A cada toque a página
saltava de escala, e o caminho de volta era a pinça.

16px é o limiar do próprio Safari, não uma preferência de leitura. A regra
vale também para os campos `-sm`: o campo pequeno é justamente o da tabela,
o mais apertado de acertar com o dedo.

| | Antes | Depois |
| --- | --- | --- |
| Cadastro de paciente | 28 campos que davam zoom | 0 |
| Prontuário estruturado | 1.037 | 0 |
| Atendimento em texto livre | 18 | 0 |
| Ficha do paciente | 18 | 0 |
| Chat da equipe | o campo de escrever | 0 |

## A condição é o dedo, e não a largura

A primeira versão do remendo usou `max-width: 767.98px`, e a medição mostrou
o erro na hora: **um celular deitado tem 844px de largura**. O mesmo
aparelho, o mesmo dedo, e o Safari voltando a dar zoom. No tablet em
retrato, 768px, idem.

A pergunta certa é `pointer: coarse` — "o apontador é impreciso?". O teto de
1199px exclui o computador com tela sensível ao toque, onde o mouse costuma
ser o apontador de fato e a densidade do tema deve continuar. A largura fica
na lista como primeira alternativa, para o navegador que não responda
`pointer`.

Esta parte **não** pôde ser provada no navegador da auditoria: a emulação de
aparelho do Chrome muda o tamanho da tela, mas não passa a reportar
`pointer: coarse`. O que se verificou foi que a consulta é válida e que o
bloco com as sete regras está na folha carregada — se a lista estivesse
malformada, o navegador teria descartado o bloco inteiro em silêncio, que é
o risco real de escrever uma consulta com duas alternativas.

## Alvo de toque de 40px

A auditoria achou botões de 27px de altura — "Trocar organização", "Usar a
câmera", "Não sei a data de nascimento" —, o avatar do cabeçalho com 30px, e
os controles da janela do chat com 26px. O dedo tem cerca de 9mm; 27px é
metade disso.

Num prontuário isso não é cosmético: o botão vizinho pode ser **Descartar**.
E o avatar do cabeçalho é o único caminho para sair da conta e trocar de
organização — errar o toque ali não tem alternativa na tela.

`min-height` em vez de `padding`, para não mexer no alinhamento do texto
dentro do botão, e `inline-flex` para o rótulo continuar centrado quando a
altura cresce. O botão que é só ícone ganhou `min-width` para continuar
quadrado — sem isso viraria um retângulo e sairia do lugar no cabeçalho.

## Dois transbordos reais, e o que os causava

**A barra de ações, entre 768px e ~900px.** A partir de 768px o tema deixa
de esconder as ações atrás do botão de sanduíche e as mostra em linha, num
`d-flex` sem `flex-wrap`. Uma tela de atendimento com cinco ações pede 593px
de uma barra que tem menos: medido em 768×1024, 52px para fora. A correção
fica **fora** de media query de propósito — a condição já é a largura
disponível, e quebrar a linha quando não cabe é o comportamento certo em
qualquer tamanho; em tela larga a linha nunca quebra, porque cabe.

**`g-5` numa `row` dentro de `container`.** A calha de 3rem vira margem
negativa de 24px de cada lado, e a folga do `container` é de 12px: sobram
12px para fora da tela. Acontecia na página de vendas e no artigo da central
de ajuda. Virou `g-4 g-lg-5` — abaixo de `lg` as colunas empilham, e calha
horizontal ali não separa nada. O segundo caso, o da ajuda, foi encontrado
**pelo roteiro**, não pela medição: eu não tinha auditado aquela tela.

## Rolagem dentro de rolagem

A lista de atendimentos da ficha do paciente tem altura fixa no computador,
para que o paciente de dez anos de acompanhamento não empurre o resto da
ficha para fora da tela. No celular, área rolável dentro de página rolável é
briga de dedo: o toque que queria rolar a página rola a lista, ou o
contrário. Passou a ser `60vh` no aparelho de toque — continua limitada, e o
limite acompanha a tela.

## O que o computador não sentiu

Todas as regras estão atrás da media query, e a medição em 1440×900 confirma
o desktop idêntico ao de antes: campo a 13,52px, botão a 27px, zero
transbordo. A densidade do Duralux é boa no computador, e aumentar campo e
botão lá só roubaria espaço num sistema que mostra muita informação junta.

## Por que existe `checks/check_mobile.py`

Layout não se mede em Python, e o roteiro não tenta. Ele existe para
**impedir que o remendo desapareça**: as regras de toque não produzem efeito
nenhum no computador — nenhuma tela muda, nenhum outro roteiro reclama —, e
CSS que não faz nada visível é o primeiro candidato a ser apagado numa
limpeza.

O roteiro afirma o contrato: o bloco existe, a condição inclui
`pointer: coarse` **e** um teto de largura, os campos vão a 16px, o alvo
chega a 40px, a barra de ações quebra linha, o campo do chat também vai a
16px, nenhuma das 48 tabelas escapa do `.table-responsive`, e nenhuma `row`
usa calha grande sem variante responsiva. As três isenções de tabela são
declaradas com nome: as duas folhas de impressão e a página pública de
verificação, que não carregam o tema.

## O que ficou de fora

- **Não há aplicativo nem *service worker*.** O produto é servidor
  renderizando HTML, e continua sendo; o que se fez aqui foi caber no
  aparelho, não virar outra coisa.
- **O roteiro de exame com 387 itens continua longo no celular.** Ele agora
  se toca sem erro e se lê sem zoom, mas um exame neurológico completo não
  cabe numa tela de 6 polegadas, e fingir que cabe seria pior. O atendimento
  em texto livre existe justamente para a consulta que não pede aquilo.
- **A grade da agenda por semana rola na horizontal** no celular, de
  propósito: sete dias lado a lado é o que a grade significa, e empilhá-los
  deixaria de ser uma grade.
