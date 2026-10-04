# Impressões, "trazer tudo" e ficar na aba — homologação

**Data:** 2026-10-04 · **Roteiro:** `checks/check_estruturado.py` ·
**Código:** `clinical/views.py`, `clinical/urls.py`,
`templates/clinical/detail.html`, `templates/clinical/_carry_forward.html`

Três defeitos da tela do prontuário estruturado com a mesma assinatura: o
servidor fazia a coisa certa e a tela não mostrava, ou mostrava e depois
perdia o lugar. Nenhum dos três quebra nada, nenhum vai para o log.

---

## 1. As impressões não eram desenhadas

`Encounter.impressions` existe no modelo desde o começo e sempre esteve em
`EncounterForm.Meta.fields`. **Nenhuma das sete abas do estruturado o
renderizava.**

A ausência, sozinha, já é um buraco: o estruturado não tinha onde
registrar a leitura do caso, que é coisa diferente da hipótese codificada
(um CID) e da conduta (o que se vai fazer).

Mas o custo real é outro, e é o que o usuário relatou. A conduta e as
impressões de uma consulta são oferecidas na consulta seguinte pelo
mecanismo de cópia (`clinical/carry_forward.py`), **nos dois tipos de
atendimento** — é o que faz as impressões de um texto livre chegarem a um
estruturado. Aceitar "Impressões da consulta anterior" num atendimento
estruturado fazia exatamente o que promete:

```python
setattr(encounter, item.field_path, value.get('text', ''))
encounter.save(update_fields=[item.field_path])
```

O item saía da lista de pendências, o banco guardava o texto, e o médico
**não via nada**. Clicava em "Trazer para esta consulta" e o conteúdo
desaparecia.

O texto só reaparecia no **resumo impresso**, que já imprimia as
impressões do estruturado logo depois das hipóteses
(`templates/clinical/summary.html`). O papel estava certo há tempo; a tela
é que não existia.

**Onde o campo ficou:** na aba **Hipóteses**, abaixo da tabela de
diagnósticos. Não em aba própria, porque é a mesma leitura — a hipótese é
a conclusão codificada e a impressão é o que não cabe num código;
separá-las em duas abas faria escrever uma sem ver a outra. A ordem é a
mesma do resumo impresso, e isso não é coincidência: as duas telas mostram
o mesmo raciocínio.

O formulário é o do `autosave`, como os outros três da tela, então salvar
impressões não toca na história nem na conduta — o autosave grava apenas
os campos que chegam no envio.

## 2. Não havia como trazer tudo

O retorno de um paciente em uso de seis medicamentos chega com dez itens
para revisar — conduta, impressões, cada hipótese, cada medicação —, e
revisar quase sempre quer dizer aceitar: é o ponto de partida da consulta
de hoje. Dez cliques, dez recarregamentos de página e (ver o defeito 3)
dez voltas para a primeira aba não produzem cuidado. Produzem um médico
que para de usar o recurso e redigita tudo.

**`CarryForwardAcceptAllView`**, botão "Trazer tudo" ao lado do contador
"N aguardando revisão", onde quem acabou de ler o número está olhando.

Três decisões:

- **Não é caminho novo.** Cada item passa por
  `cf.review_carry_forward_item`, o mesmo do botão individual, com as
  mesmas recusas — inclusive a de atendimento finalizado, que mora lá
  dentro e não só na view. Isto é o botão individual clicado em todos.
- **Tudo ou nada.** A transação envolve o laço inteiro. Um "trazer tudo"
  que traz metade é pior do que um que falha: ninguém conta o que veio, e
  a diferença só aparece na consulta seguinte, quando faltar a medicação
  que ninguém percebeu que não tinha entrado.
- **Sem confirmação antes.** Cada item já está escrito na tela acima do
  botão, aceitar é exatamente o que o botão diz, e o que ele grava
  continua editável até a finalização. Pedir confirmação aqui seria cobrar
  um clique a mais justamente de quem veio economizar nove.

Clicar de novo sem nada pendente não é erro — quem recarregou a aba velha
não fez nada de errado —, e a trilha registra
`clinical.carry_forward_accepted_all` com a contagem.

## 3. Salvar devolvia para a primeira aba

`static/duralux/app.js::tabFromHash` reabre a aba cujo id está no endereço,
e o comentário dela já dizia por quê: *"o servidor redireciona para
`.../#tab-exame` depois de salvar, e sem isto a pessoa voltava sempre para
a primeira aba"*.

O mecanismo estava certo. **Vários redirecionamentos de sucesso saíam sem
âncora:**

| Ação | Antes | Agora |
| --- | --- | --- |
| Salvar história | topo da página | `#tab-historia` |
| Salvar texto do exame | topo da página | `#tab-exame` |
| Salvar conduta | topo da página | `#tab-conduta` |
| Salvar impressões | (não existia) | `#tab-hipoteses` |
| Adicionar hipótese | topo da página | `#tab-hipoteses` |
| Revisar item da consulta anterior | topo da página | `#carry-forward` |

Em quatro das sete abas (exame, exames, medicações, adendos) o trabalho
aparecia salvo, porque aquelas ações já carregavam a âncora. Nas outras,
parecia ter sumido — e é por isso que o relato foi "não está acontecendo
em **todas**".

O `#carry-forward` era pior: **três recusas já mandavam para essa âncora e
ela não existia em template nenhum.** O cartão não tinha `id`, então o
navegador deixava a página onde estava e a mensagem de erro aparecia no
topo falando de um cartão que podia estar quatro telas abaixo.

**De onde o servidor sabe a aba.** De um campo oculto no próprio
formulário (`<input type="hidden" name="aba" value="tab-conduta">`), e não
de um mapa campo→aba no servidor: quem sabe em que aba um formulário está
é o template que o desenha, e um mapa no Python seria a segunda lista a
envelhecer.

**O valor é conferido pela forma, não pela lista.** `_aba_pedida` aceita
`tab-[a-z-]{3,24}` e descarta o resto em silêncio — a pessoa cai no topo,
que é o comportamento de antes, não um erro novo. Guardar a lista das sete
abas no Python seria a mesma lista a envelhecer, e o valor vai para o
fragmento de uma URL de redirecionamento.

## O que o roteiro conferiu

`checks/check_estruturado.py`, 6 seções, `EXIT=0`:

- [x] o campo de impressões está na página e **entre** a aba de hipóteses e
      a de conduta — a posição é a do resumo impresso
- [x] o rótulo não aparece duas vezes na mesma caixa
- [x] o que se grava volta na tela e sai no resumo impresso
- [x] salvar impressões não apaga a história (o autosave grava só o que vem)
- [x] **o item "Impressões da consulta anterior" aceito num estruturado
      aparece na tela** — a asserção que teria pego o defeito 1
- [x] "Trazer tudo" não deixa nada pendente e aplica o efeito de cada tipo:
      texto (conduta), medicação e hipótese
- [x] a trilha registra `clinical.carry_forward_accepted_all`
- [x] o cartão some da tela quando nada está pendente, e clicar de novo
      não quebra
- [x] atendimento finalizado recusa com a mensagem do adendo, **nenhum item
      é consumido** e o registro fechado não é alterado
- [x] salvar em cada uma das quatro abas com formulário volta para ela
- [x] `aba` forjada (`tab-<script>`, `../../evil`, `https://exemplo.ru`,
      longa demais, vazia) **não vira âncora** — nenhuma injeção no destino
- [x] acrescentar hipótese volta para a aba de hipóteses
- [x] a âncora `#carry-forward` existe no template, e `tabFromHash`
      continua existindo em `app.js` — sem ele as âncoras são decoração
- [x] **varredura do template:** todo formulário de `autosave` dentro de um
      `tab-pane` carrega o `aba` com o id **daquele** painel, e as sete abas
      são encontradas. Escrito como lista de três nomes, a quarta aba
      nasceria sem — que foi exatamente como as três de hoje nasceram

Bateria completa: **90 roteiros**, nenhuma falha.
