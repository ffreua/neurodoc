# Central de ajuda: manual e perguntas de uso

`/ajuda/` — vinte e dois processos explicados passo a passo, com capturas
das telas reais, mais onze perguntas de quem já usa. Pública, sem
login, e ligada à página inicial.

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

## Os vinte e dois processos

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
| 13 | Os indicadores da clínica | Dono, gestor, médico |
| 14 | Financeiro: recebíveis, pagamentos e ajustes | Dono, gestor, secretaria, médico |
| 15 | A grade de horários do médico | Médico, dono, gestor |
| 16 | Identidade da clínica e o encarregado de dados | Dono |
| 17 | E-mail e SMS da clínica | Dono, gestor |
| 18 | Comunicação em massa | Dono, gestor |
| 19 | Notificações | Todos |
| 20 | Mensagens internas da equipe | Todos |
| 21 | Exportar os dados da clínica | Dono |
| 22 | Falar com a NeuroDoc | Todos |

Os artigos administrativos entraram em 2026-09-23, quando o manual foi confrontado
com o menu: doze artigos cobriam o trabalho assistencial e **nenhum**
cobria o administrativo. Financeiro, indicadores, mensageria, campanhas,
exportação e captura estavam no produto e fora do manual. O artigo de captura
foi retirado junto com a funcionalidade em 29/09/2026 (DEC-53).

Na mesma mudança, o artigo de documentos e o FAQ passaram a dizer o percurso
vigente sem ambiguidade: digitalizar fora do NeuroDoc e enviar o arquivo
pronto em **Anexos**. O manual não orienta pareamento, descoberta de hardware
ou instalação de agente local.

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

Tiradas por `ops/capturar_ajuda.py`, com o navegador **dentro do Docker**,
na rede da própria pilha. A primeira leva saiu de um Chrome dirigido à mão
nesta máquina, e o navegador foi morto três vezes por falta de memória no
meio do trabalho — uma sequência longa de capturas competindo por RAM com
o navegador de quem está trabalhando é exatamente o caso que estoura.
Mudar de lugar resolveu: `scripts/capturar_ajuda.sh` refaz o manual
inteiro num comando.

Cinco defeitos que só apareceram porque o roteiro passou a conferir a si
mesmo, e que valem registro porque nenhum deles levantava erro:

- **A captura saía da clínica errada.** O dono da demonstração tem vínculo
  em duas clínicas, e o roteiro escolhia "a primeira do seletor" — a
  Clínica Demo B, que existe justamente para exercitar a troca de
  organização e quase não tem dado. Vinte e duas telas saíram dela, todas
  respondendo 200. Agora a clínica é escolhida **pelo nome**, e o roteiro
  confere o cabeçalho depois de entrar.
- **Seis capturas saíram idênticas duas a duas.** O preparo mandava rolar
  até uma seção com `scroll_into_view_if_needed`, que não faz nada quando o
  elemento já está visível. O manual publicaria a mesma imagem com duas
  legendas diferentes. O roteiro agora compara o SHA-256 de tudo que
  gravou e falha se dois arquivos baterem; o que não se resolve rolando
  virou captura **do elemento**.
- **A janela de mensagens da equipe atravessa a navegação** — ela vive no
  shell, não na página. Depois das duas capturas do chat, apareceu colada
  por cima da captura seguinte. Fechada agora antes de cada tela.
- **`networkidle` nunca dispara em `/app/`**: chat e notificações mantêm
  conexões SSE abertas, e a rede não fica ociosa. A espera é
  `domcontentloaded` mais um tempo fixo.
- **Duas capturas publicavam erros como se fossem telas.** Valores apontava
  para a rota antiga `/app/finance/valores/` (404), e registro profissional
  navegava até uma ação que aceita somente POST (405). O capturador agora
  visita `/app/org/valores/`, abre o modal de registro dentro da equipe e
  recusa qualquer resposta HTTP malsucedida antes de gravar o PNG.

## O banco de demonstração tinha zero recebíveis

Descoberto ao ilustrar o artigo do financeiro: a tela abria dizendo
"nenhum recebível no período", e nenhum manual se escreve a partir disso.

Eram dois defeitos de `seed_demo` empilhados, e os dois em silêncio:

1. A tabela de honorários e a criação dos recebíveis estavam **dentro** da
   guarda "já existe atendimento finalizado?". Num banco semeado antes de
   esse bloco existir, os atendimentos estavam lá, a guarda pulava tudo, e
   a clínica ficava sem cobrança nenhuma para sempre.
2. Só havia tabela **particular**, e a única paciente com atendimento
   finalizado tem convênio ativo. `create_receivable_for_encounter`
   resolvia o preço como `insurance`, não achava regra, gravava
   `finance.receivable_pricing_missing` na trilha e devolvia `None` — sem
   nada na tela dizendo por quê.

Os dois fatos agora se verificam sozinhos, e a semeadura cria as duas
tabelas. O primeiro recebível sai quitado e os demais ficam em aberto: uma
lista inteiramente verde não mostra para que serve a tela.

## Um defeito encontrado na primeira renderização

O texto dos passos usa Markdown — `**negrito**` para nome de menu, crase
para valor digitado. O template os passava com `|safe`, que não converte
nada: a tela mostrava os asteriscos e as crases literais.

A conversão passou para a view, com `ai.rendering.render_markdown` — o
mesmo renderizador da saída da IA, que **escapa antes de converter**. Isso
importa porque a página é pública: HTML literal escrito no manual vira
texto inerte, não markup.

## O que foi verificado

`checks/check_ajuda.py`, dez seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | Toda captura referenciada existe? | 47 de 47 |
| 2 | Alguma captura órfã? | Nenhuma |
| 3 | As páginas abrem sem login? | Índice, perguntas e landing em 200 |
| 4 | Cada artigo abre e está no índice? | 23 de 23 |
| 5 | Slug inexistente? | 404, não 500 |
| 6 | A landing leva ao manual? | Manual e perguntas |
| 7 | As capturas são servidas? | `<img>` renderizado |
| 8 | Promete o que está fora do escopo? | Nada |
| 9 | Todo artigo tem público, resumo e passos? | 23 de 23 |
| 10 | As quatro telas administrativas estão no capturador? | Rotas atuais e modal de registro |

A seção 2 é a que costuma faltar em verificação de manual: ela pega a
captura que ficou no repositório depois de o texto que a usava ser
reescrito. Peso morto não quebra nada — e é por isso que fica.
