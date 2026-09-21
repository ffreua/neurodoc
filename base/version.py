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

**Regra de incremento.** Maior quando a mudança quebra alguma coisa para
quem já usa — um caminho que some, um dado que muda de forma. Menor
quando entra funcionalidade sem quebrar nada. Correção sem funcionalidade
nova não mexe em nenhum dos dois: o `RELEASE_ID` já a identifica, e uma
terceira casa que muda toda semana deixa de ser lida.

Mora em código, como os preços e o contrato, e pelo mesmo motivo: mudá-la
é um commit com autor e data. Este módulo não importa nada de propósito —
`ops/deploy.py` roda no host, fora do Django, e precisa ler a versão para
carimbá-la na publicação.
"""

#: A versão do produto. O primeiro deploy é a 1.0.
VERSION = '1.0'

#: Nome do marco, quando houver. Aparece ao lado da versão nas telas de
#: instalação; vazio não mostra nada, e é o padrão — inventar um apelido
#: para cada correção é ruído.
CODENAME = 'primeiro deploy'


def version_display():
    """Como a versão aparece para uma pessoa: `1.0` ou `1.0 (apelido)`."""
    return f'{VERSION} ({CODENAME})' if CODENAME else VERSION
