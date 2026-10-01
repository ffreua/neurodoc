"""A versão do produto. Uma linha, e o motivo de ela existir.

**Não confundir com `RELEASE_ID`.** São dois números com trabalhos
diferentes, e o sistema precisava dos dois:

- `RELEASE_ID` é o SHA do commit publicado. Identifica **um build**, muda
  a cada publicação, entra no caminho dos estáticos e serve para responder
  "qual código exatamente está rodando neste servidor?". É de quem opera.
- `VERSION` é a versão do **produto**. Muda quando o que a clínica recebe
  muda de forma que importe para ela, e serve para responder "que
  NeuroDoc é este?". É de quem usa, de quem vende e de quem escreve a
  documentação — e é o número que aparece num e-mail de suporte, num
  contrato e numa nota de versão.

Um SHA não responde a segunda pergunta: `2436d01` não diz a ninguém se
faltam funcionalidades, e ninguém o repete ao telefone.

**Regra de incremento.** A partir da entrega imediatamente posterior à
1.0, funcionalidade compatível avança a versão menor (1.1, 1.2...). Uma
mudança relevante e incompatível avança a maior (2.0, 3.0...). Correção sem
funcionalidade nova não muda `VERSION`: o `RELEASE_ID` já identifica o
build exato, e uma terceira casa que muda toda semana deixa de ser lida.

Por decisão de produto, a retirada da captura local, o campo narrativo do
exame e a agenda visual ainda compõem a consolidação da 1.0.

A **1.1** é a primeira atualização funcional depois da publicação: retorno
programado, busca de paciente por diagnóstico, a evolução em gráfico, a
declaração de comparecimento emitida no balcão, e a política de conteúdo
entrando em modo de relatório. Nenhuma delas muda o que já existia — por
isso a versão menor, e não a maior.

A **1.2** traz o nome do paciente numa forma só (caixa alta, gravada) e a
migração de cadastro de outro sistema. O nome muda de aparência para quem
já usa, mas nada deixa de funcionar — busca, documento e mensagem seguem
achando e imprimindo o mesmo paciente —, então a versão menor avança e a
maior não.

Mora em código, como os preços e o contrato, e pelo mesmo motivo: mudá-la
é um commit com autor e data. Este módulo não importa nada de propósito —
`ops/deploy.py` roda no host, fora do Django, e precisa ler a versão para
carimbá-la na publicação.
"""

#: A versão do produto. O primeiro deploy é a 1.0.
#:
#: A terceira casa aparece aqui contra a regra escrita acima, e de
#: propósito: a 1.1.1 corrige o dia errado na agenda, que a 1.1 publicou.
#: Dizer "1.1" para as duas faria o chamado de suporte não distinguir quem
#: já tem a correção de quem ainda vê o defeito -- que é exatamente o que a
#: versão existe para responder.
VERSION = '1.4'

#: Nome do marco, quando houver. Aparece ao lado da versão nas telas de
#: instalação; vazio não mostra nada, e é o padrão — inventar um apelido
#: para cada correção é ruído.
CODENAME = 'quem assina é o autor'


def version_display():
    """Como a versão aparece para uma pessoa: `1.0` ou `1.0 (apelido)`."""
    return f'{VERSION} ({CODENAME})' if CODENAME else VERSION
