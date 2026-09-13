# Central de ajuda: manual e perguntas de uso

`/ajuda/` — doze processos explicados passo a passo, com 25 capturas das
telas reais, mais dez perguntas de quem já usa. Pública, sem login, e
ligada à página inicial.

Evidências: `checks/check_ajuda.py`.

## Pública, e por quê

Duas razões práticas. Quem está avaliando o sistema quer ver como ele
funciona **antes** de ter conta — e um manual com as telas reais responde
isso melhor do que qualquer parágrafo de venda. E quem já usa costuma
procurar ajuda no celular, fora da sessão aberta no consultório.

Não há dado de pessoa real em imagem nenhuma: todas as capturas saem do
banco de demonstração, com pacientes sintéticos. Isso é condição, não
detalhe — o manual é público.

## O conteúdo vive em Python

`base/help_content.py`, e não em Markdown solto nem no banco:

**É conferível.** `check_ajuda` percorre a estrutura e afirma que toda
captura referenciada existe em `static/help/` — e, na direção contrária,
que nenhuma captura no disco ficou órfã. O modo como um manual apodrece é
exatamente esse: o texto muda, a imagem some, e ninguém percebe até um
usuário abrir a página e ver o ícone quebrado.

**Versiona junto com a tela que descreve.** Um manual no banco descreve a
versão de quando foi escrito, e o commit que muda a tela não o toca. Aqui,
quem muda a tela vê o texto no mesmo diff.

## Os doze processos

| # | Artigo | Público |
| --- | --- | --- |
| 1 | Entrar e escolher a clínica | Todos |
| 2 | Cadastrar um paciente | Secretaria, médico, gestor |
| 3 | Marcar e remarcar na agenda | Secretaria, médico, gestor |
| 4 | Atender: escrever o prontuário | Médico |
| 5 | O exame neurológico estruturado | Médico |
| 6 | Emitir e assinar um documento | Médico |
| 7 | Entregar o documento ao paciente | Médico, secretaria |
| 8 | Portal de solicitações do paciente | Médico, gestor |
| 9 | Buscar códigos CID-10 e TUSS | Todos |
| 10 | Chat de apoio | Médico |
| 11 | Convênios, planos e valores | Dono, gestor, médico |
| 12 | Equipe, papéis e registro profissional | Dono |

Cada artigo tem público declarado, resumo e passos numerados. Nem todo
passo tem captura: uma imagem por parágrafo transforma o manual numa
apresentação de slides.

## O manual descreve o que existe

`check_ajuda`, seção 8, lê o texto inteiro — artigos e perguntas — e falha
se ele mencionar teleconsulta, TISS, DICOM, PACS, cartão de crédito ou
boleto. São as coisas que a versão 1 **não** entrega (seção 2.2 do PRD), e
prometê-las num manual é pior do que prometê-las numa página de vendas:
aqui a pessoa já é cliente, e vai procurar o botão.

O artigo do chat de apoio diz, com todas as letras, que a remoção de dados
identificadores é melhor esforço e não anonimização completa — a mesma
ressalva que está em `chatbot.md`. Um manual que omitisse isso ensinaria o
médico a digitar o que não deve.

## As capturas

Tiradas com Chrome real dirigido por `agent-browser`, contra a pilha local
e o banco de demonstração recém-limpo. **Em lotes pequenos, fechando o
navegador entre eles**: o Chrome foi morto três vezes nesta máquina por
falta de memória, e uma sequência de vinte e cinco capturas numa sessão só
é exatamente o caso que estoura.

Três exigiram preparar o estado antes, e vale registrar porque a próxima
atualização vai precisar do mesmo:

- **`agenda-marcar`**: a semana corrente não tinha horário livre (a grade
  do médico é segunda-feira, e a captura foi feita num domingo). Resolvido
  navegando para `?date=` da segunda seguinte.
- **`chat-conversa`**: não havia conversa no banco — os roteiros limpam as
  suas. Criada uma conversa de exemplo, com a resposta da IA mostrando a
  frase "Não encontrei isso no prontuário deste paciente", que é
  justamente o comportamento que o artigo descreve.
- **`solicitacoes-portal`**: o portal vem desligado por padrão, e o
  endereço responde 404 nesse estado. Ligado na clínica de demonstração.

## Um defeito encontrado na primeira renderização

O texto dos passos usa Markdown — `**negrito**` para nome de menu, crase
para valor digitado. O template os passava com `|safe`, que não converte
nada: a tela mostrava os asteriscos e as crases literais.

A conversão passou para a view, com `ai.rendering.render_markdown` — o
mesmo renderizador da saída da IA, que **escapa antes de converter**. Isso
importa porque a página é pública: HTML literal escrito no manual vira
texto inerte, não markup.

## O que foi verificado

`checks/check_ajuda.py`, nove seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | Toda captura referenciada existe? | 25 de 25 |
| 2 | Alguma captura órfã? | Nenhuma |
| 3 | As páginas abrem sem login? | Índice, perguntas e landing em 200 |
| 4 | Cada artigo abre e está no índice? | 12 de 12 |
| 5 | Slug inexistente? | 404, não 500 |
| 6 | A landing leva ao manual? | Manual e perguntas |
| 7 | As capturas são servidas? | `<img>` renderizado |
| 8 | Promete o que está fora do escopo? | Nada |
| 9 | Todo artigo tem público, resumo e passos? | 12 de 12 |

A seção 2 é a que costuma faltar em verificação de manual: ela pega a
captura que ficou no repositório depois de o texto que a usava ser
reescrito. Peso morto não quebra nada — e é por isso que fica.
