# Ajustes do prontuário — o que você reportou

Onze pontos, cada um com o que era, o que virou e por quê. Três eram bug de
verdade; dois deles com uma causa comum que valia consertar na origem.

## 1. Caixas de texto não são mais redimensionáveis

Toda `<textarea>` tinha alça de arrastar. Sai a alça (`resize: none`) e, em
troca, **a caixa cresce com o texto**: quem escreve uma história longa
continua vendo o que escreveu, sem arrastar nada e sem barra de rolagem
dentro do campo.

O `rows` do formulário passa a ser a altura **mínima** — a proporção pensada
na tela (queixa curta, história longa) continua valendo com o campo vazio, e
a caixa volta a ela quando o texto encurta. Vale em todas as abas.

Medido no navegador: queixa 67 px vazia → 146 px com seis linhas → 67 px de
volta.

## 2. Finalizar atendimento pedia um requisito por vez

**Era isto o bug.** A verificação era em cascata: cada tentativa apontava um
requisito, e o próximo só aparecia depois de resolver aquele. Você preencheu
queixa e história, clicou, e o sistema então falou da conduta — parecendo que
não finalizava.

Agora `finalization.missing_requirements()` devolve **tudo o que falta de uma
vez**, e:

- o **modal mostra a lista antes do clique**, dizendo em que aba está cada
  item, e o botão sai desabilitado enquanto houver pendência;
- a recusa, se acontecer, também vem completa e numerada;
- a lista lembra que "Justificativa da finalização" dispensa queixa e
  conduta quando não se aplicam.

Revisar o carry-forward também entra na lista — e essa é a única pendência
que a justificativa **não** dispensa, porque revisar é o ato de decidir o que
entra no registro.

## 3. CPF válido com aviso de "CPF inválido" ao lado

**Bug real, e a causa é específica.** O campo de aviso nascia com as classes
`invalid-feedback d-block`, e a visibilidade era controlada pelo atributo
`hidden`. Só que `.d-block` do Bootstrap é `display: block !important`, e o
`!important` vence o `hidden` do navegador: `feedback.hidden = true` não
escondia nada. Resultado: CPF certo, campo verde e a frase "CPF inválido: os
dígitos verificadores não conferem" logo abaixo.

Agora a visibilidade é a própria classe `d-block`, adicionada e removida. O
algoritmo de validação estava correto e não mudou.

Medido no navegador: `111.444.777-35` → campo `is-valid`, mensagem vazia,
`display: none`. `111.444.777-34` → `is-invalid` com a mensagem visível.

## 4. Escala continuava aberta depois de salvar

A tela abria sozinha a primeira escala que tivesse valor registrado — e o
efeito era o contrário do pretendido: depois de salvar, a página voltava com
um formulário de trinta campos escancarado no meio da aba, como se ainda
houvesse algo a fazer nele.

Nenhuma escala abre sozinha. O ✓ no seletor diz quais foram aplicadas, e
escolher a escala reabre com os valores marcados. Cada formulário ganhou um
botão **Fechar**.

## 5. "Lançar analito à mão" com layout diferente

As sete colunas somavam 15 de 12, quebrando a linha no meio com larguras que
não batiam com o formulário de cima, e usava `g-2` contra `g-3`. Agora é o
mesmo desenho de "Incluir resultado de exame": caixa cinza, título, `g-3`,
colunas que fecham em 12 e botão primário.

## 6. Autocomplete do CID-10

O `cid10.csv` que você deixou na raiz virou
`catalogs/data/cid10-2024.csv` — **14.233 códigos** (2.045 categorias e
12.188 subcategorias), convertidos para o formato do importador já existente
(`code,description,parent_code`, com o pai derivado do código: `G40.0` → pai
`G40`). Importado como release `CID10 2024` e ativado.

A busca é **por código ou por descrição**, porque é assim que se procura:

| Digitado | Encontra |
| --- | --- |
| `G40` | G40 Epilepsia e os 10 subitens |
| `g43.0`, `G430` | G43.0 Enxaqueca Sem Aura |
| `enxaqueca` | as 6 formas de enxaqueca |
| `esclerose multipla` (sem acento) | G35 Esclerose Múltipla |
| `cefaleia` | R51 Cefaléia, G44.2 Cefaléia Tensional… |

**Busca sem acento precisou de coluna própria.** Este banco não tem a
extensão `unaccent` (o usuário da aplicação não tem privilégio para criá-la),
e ninguém digita acento procurando com pressa. `DiagnosisCode.search_text`
guarda código e descrição sem acento e em maiúsculas; o termo digitado passa
pela **mesma** função de normalização. São 14 mil linhas — a varredura custa
menos que a dependência. Instalação que já tinha catálogo importado é
preenchida por **migração de dados**, não por comando manual.

Na tela: um campo de busca acima de CID e Hipótese, com lista rolável,
navegação por seta e Enter, e um aviso "Selecionado: G43.0 — …". Escolher
preenche código, descrição e o vínculo com o catálogo.

Três decisões de comportamento:

- **hipótese sem CID continua possível** — é o caso mais comum na primeira
  consulta. O que passou a ser recusado é hipótese **vazia**, que antes
  gravava uma linha em branco com um grau de certeza ao lado;
- **editar a descrição à mão desfaz o vínculo** com o código, e a tela diz
  isso: o texto deixou de ser o do CID escolhido;
- **falha de rede na busca não trava o registro** — a tela avisa e a hipótese
  continua podendo ser escrita à mão.

## 7. Resumo do caso, imprimível

Botão **Resumo do caso** no topo do atendimento, abrindo em janela própria
com proporção de folha. Sai sem menu, sem botões e sem formulário; o que
está na tela é o que sai no papel, com botão Imprimir (que serve também para
"salvar como PDF" pelo diálogo do navegador).

Traz identificação do paciente, história, medicações em uso, exame
neurológico por domínio, resultados de exames (com os analitos **fora** da
referência e a contagem dos que estão dentro), hipóteses, conduta e adendos.

Duas coisas que o rodapé diz e que importam: se o atendimento **ainda não
está finalizado** (o conteúdo pode mudar) e que **não é documento assinado** —
receita, relatório e encaminhamento continuam saindo pelo fluxo de documentos
médicos, com assinatura digital. Uma folha impressa não deve circular
parecendo laudo.

Atendimento finalizado mostra o hash de integridade.

## 8. Carry-forward mostrando estrutura interna

Era isto na tela:

```
plan_text                                    {'text': 'TPM 100mg'}
diagnosis:a192554a-a3d1-402c-89f5-7558ce340c43   {'rank': 1, 'certainty': 'suspected', …}
```

Agora:

> **CONDUTA DA CONSULTA ANTERIOR**
> TPM 100mg
>
> **HIPÓTESE DA CONSULTA ANTERIOR**
> R51 — Cefaleia
> Suspeita · ordem 1

Com **Trazer para esta consulta** / **Descartar** em vez de Aceitar/Rejeitar,
e o cabeçalho dizendo "nada é copiado sem sua decisão". Quem decide precisa
ler o conteúdo, não o formato de armazenamento.

**E havia um bug embaixo disso:** aceitar uma hipótese trazida **não fazia
nada**. O item era marcado como aceito e a hipótese não entrava no
atendimento — o aceite existe justamente para trazê-la. Agora cria a
`EncounterDiagnosis` com a nota "Trazida da consulta anterior e revisada".
Aceitar a conduta já funcionava.

## 9. A causa comum de vários "crachás" que pareciam texto solto

Investigando o "IA: Desligada" sem fundo, medi no navegador:

```
bg-soft-secondary -> rgba(0, 0, 0, 0)   ← sem fundo nenhum
bg-soft-dark      -> rgb(233, 239, 244) ← o cinza claro de verdade
```

A classe `bg-soft-secondary` existe no CSS do tema mas **não define fundo**.
E `secondary` era justamente o tom de reserva do `nd_tone` — então todo
estado neutro do sistema (rascunho, arquivado, não avaliado, sem referência,
IA desligada, desatualizado, expirado, encerrado) e todo valor fora do mapa
apareciam como texto solto, perdendo a informação de que aquilo era um
estado.

Corrigido na origem: o tom neutro do `nd_tone` passou de `secondary` para
`dark`. Conserta todas essas telas de uma vez, e o crachá de prioridade das
hipóteses voltou a usar o mesmo mecanismo em vez de classes próprias.

Também no cartão de exame: `extraction_detail` só é vermelho em falha de
verdade — "IA desligada" não é erro deste exame, e o vermelho fazia o cartão
parecer com problema. E o corpo do cartão não é renderizado quando não há
laudo, analito nem formulário: uma faixa cinza vazia parecia conteúdo que não
carregou.

## 10. Aba não abria pelo endereço

Fora da sua lista, mas apareceu ao testar: os redirecionamentos apontavam
para `#tab-exame` e o JS não lia o endereço. Depois de salvar um eixo do
exame, a pessoa voltava para a primeira aba. Agora a aba abre pelo endereço e
trocar de aba atualiza o endereço (com `replaceState`, para o navegador não
rolar até o painel).

## 11. Hipótese sem descrição no grid

Registro antigo com descrição vazia deixava a célula em branco. O formulário
agora recusa hipótese vazia, e o grid e o resumo mostram "—" para o que já
existe.

## Verificação executada

| Verificação | Resultado |
| --- | --- |
| Varredura dos ajustes | **43 de 43** — finalização, justificativa, CID, resumo, carry-forward legível e com efeito, rejeitar sem copiar |
| Regressão | 68 templates, 30 páginas, 25 + 45 + 42 casos anteriores — 0 falhas |
| CPF no navegador | válido → sem mensagem, `display:none`; inválido → mensagem visível |
| Caixas de texto | `resize: none` em todas; cresce de 67 → 146 px e volta |
| Escalas | 14 no DOM, **0 abertas na carga**; aplicar Epworth deu 16/24 com a faixa, salvou, fechou e marcou ✓ |
| CID no navegador | "esclerose multipla" → G35; "enxaqueca" → 6 opções; escolher preencheu G43.0 + descrição + vínculo `930efbd6`; gravou |
| Resumo | abre em janela própria, 6 seções, sem menu, com Imprimir e o aviso de que não é documento assinado |
| Carry-forward | "Conduta da consulta anterior / TPM 100mg" e "Hipótese da consulta anterior / R51 — Cefaleia"; aceitar a hipótese criou a hipótese (0 → 1) |
| Crachás | todos com fundo: `Laboratorial`, `IA: Desligada`, `laudo liberado`, `Dentro da referência` |
| Busca do CID | teto de 20 resultados, termo com menos de 2 caracteres não varre o catálogo |

## O que não mudou, e por quê

**A data em `<input type="date">` continua exigindo o formato do campo.** Na
conferência pelo navegador automatizado a data não gravou; investigado, é
limitação da ferramenta de automação ao preencher campo de data nativo — o
formulário parseia ISO e locale corretamente, e o preenchimento pela tela
gravou `2026-08-25` sem problema.
