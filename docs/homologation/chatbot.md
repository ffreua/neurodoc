# Chat de apoio — prompt, prontuário e layout

O chat de apoio passa a mandar ao provedor uma instrução de sistema, o
prontuário do paciente da sessão e o histórico da conversa — tudo
desidentificado — num layout de duas colunas.

Evidências: `checks/check_chatbot.py`.

## O que ele fazia antes

```python
run_chat_turn.delay(str(assistant_message.id), content)
```

`content` era a mensagem digitada, e nada mais. Disso decorriam quatro
lacunas, e nenhuma delas era visível na tela:

| Lacuna | Consequência |
| --- | --- |
| Sem instrução de sistema | Nenhuma regra contra alucinar, nenhum enquadramento de papel |
| Sem histórico | Cada mensagem ia sozinha. "E no segundo caso?" não tinha primeiro caso |
| Sem dado da clínica | As seis funções de `ai/tools/` existiam e o chat não usava nenhuma |
| Sem desidentificação | O caminho de análise desidentificava; o chat mandava cru |

A última era a mais séria: um nome de paciente digitado no chat saía da
instalação sem passar pela política que o resto do sistema aplica.

## Fatos entregues, não ferramentas oferecidas

A saída natural seria vincular as funções de `ai/tools/` como *tools* do
provedor e deixar o modelo escolher. `ai/chat_prompt.py` faz o contrário:
lê o prontuário **antes**, monta um bloco de fatos e o entrega junto da
pergunta.

Três razões, em ordem de peso:

1. **Não depende do provedor.** O próprio produto já registra que chamada
   de ferramenta e saída estruturada variam conforme o modelo por baixo do
   agregador — é por isso que `ai/graphs.py` valida a resposta por conta
   própria. Um chat que só funciona com metade dos dez provedores do
   catálogo não serve.
2. **"Não alucinar" se resolve dando o dado.** Modelo que *pode* chamar
   uma ferramenta às vezes não chama e responde de memória. Com os fatos
   no contexto, a instrução "só existe o que está aqui" tem a que se
   referir.
3. **Auditabilidade.** Sabemos o que saiu porque fomos nós que montamos.
   Com chamada de ferramenta, isso depende de uma decisão tomada fora
   daqui.

O custo é enviar contexto que às vezes não será usado, limitado por tetos
(12.000 caracteres de prontuário, 8.000 de histórico).

## As quatro regras

A instrução de sistema é curta de propósito — regra longa se dilui:

1. **Fontes.** Sobre este paciente existem duas: o bloco de prontuário e o
   que o médico escreveu. Conhecimento geral serve para redigir, nunca
   para afirmar fato.
2. **Dado ausente se diz**, com frase literal: *"Não encontrei isso no
   prontuário deste paciente."* Sem a frase exata, o modelo preenche a
   lacuna — é o que ele faz.
3. **Número nenhum é inventado.** Dose, data, valor: veio da fonte ou não
   existe.
4. **A decisão é do médico.** Sem diagnóstico, sem conduta como ordem.

## Escopo e privacidade

**Apenas o paciente da sessão** (decisão do produto, setembro/2026).
Sessão sem paciente não recebe prontuário nenhum, e o prompt diz isso ao
modelo em vez de deixá-lo supor.

A autorização é **reconstruída do banco dentro da tarefa**, não recebida
pronta: entre enfileirar e executar cabe uma revogação de vínculo, e é a
última chance de recusar antes de o prontuário sair. Verificado na seção 9
com o vínculo suspenso.

**Desidentificação com ressalva escrita.** `deidentify_text` é por regra —
nome cadastrado, CPF, telefone, e-mail. Ela **não** alcança um nome que o
médico digite de cabeça sem estar no cadastro, nem apelido. É melhor
esforço, como o próprio módulo diz, e prometer anonimização forte seria
mentir. **P-06** continua bloqueando uso sobre paciente real.

## O layout

Duas colunas numa tela: conversas à esquerda, conversa à direita. Eram
duas páginas — abrir uma conversa fazia a lista sumir, e trocar de assunto
exigia voltar.

Decisões que valem registro:

- **O título sai da primeira pergunta.** O campo era opcional e ficava
  vazio; a lista virava uma coluna de "Sem título", pela qual não se
  navega.
- **O paciente é escolhido por busca, não por UUID.** O campo pedia o id
  digitado à mão. Ninguém sabe o UUID de um paciente: na prática ficava
  vazio, e toda conversa nascia sem prontuário — justamente o caso em que
  a IA não tem o que consultar.
- **Enter envia, Shift+Enter quebra linha** — e `isComposing` é
  respeitado, senão o Enter que confirma um acento cortaria a palavra no
  meio. Em português isso aconteceria o tempo todo.
- **A rolagem acompanha o streaming só se quem lê está no fim.** Rolar
  para trás para reler e ser arrastado de volta a cada token é o
  comportamento que se odeia em chat.
- **Arquivar, não apagar.** A conversa carrega o que foi perguntado e
  respondido, e isso é material de revisão.
- **O aviso de revisão fica junto do campo**, não num rodapé: é ali que a
  pessoa está prestes a aceitar o que foi respondido.

## O que não mudou

Streaming SSE, revalidação de capacidade a cada volta do laço,
cancelamento e isolamento entre sessões. Funcionam, estão homologados em
[`chat.md`](chat.md), e mexer neles sem necessidade é como se perde o que
já estava certo. `chat-shell.js` é separado de `chat.js` pela mesma razão:
uma mudança de layout não deve arriscar o streaming.

## O que foi verificado

`checks/check_chatbot.py`, dez seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | As quatro regras vão junto? | Todas presentes |
| 2 | O prontuário do paciente vai junto? | 396 caracteres, 4 atendimentos |
| 3 | Nome e CPF saem? | Nenhum termo identificável; 1 marcador |
| 4 | O histórico chega? | Pergunta e resposta anteriores presentes |
| 5 | Resposta pela metade entra no histórico? | Não |
| 6 | Sessão sem paciente alcança prontuário? | Não, e o prompt avisa |
| 7 | Ferramenta sem paciente em escopo? | Recusa |
| 8 | Paciente de outra clínica? | Recusa |
| 9 | Vínculo suspenso entre enfileirar e executar? | Recusa |
| 10 | A tela tem layout, aviso e composer? | Sim |

Fora do roteiro: a volta completa com provedor substituído por um falso —
streaming, gravação e `SystemMessage` em primeiro lugar —, e navegação
real em Chrome (lista, modal, busca de paciente por nome, conversa criada
com o paciente certo).

## Um achado do caminho

A busca de paciente devolvia "nenhum paciente encontrado" para um nome que
existe. Não era defeito: o paciente estava **arquivado**, e o autocomplete
não lista arquivados — o que está certo. O que o episódio mostra é que o
banco de demonstração acumulou estado de teste; o paciente principal da
demonstração foi devolvido a ativo.
