"""O nome do paciente, numa forma só.

Três pessoas cadastram e saem três grafias: "maria da silva", "MARIA DA
SILVA", "Maria Da  Silva". A lista de pacientes vira um mosaico, a agenda
também, e o documento impresso herda a pressa de quem digitou.

A forma canônica é **caixa alta, sem espaço sobrando** — decisão do
responsável pelo produto em 30/09/2026, para padronizar a aparência do
sistema inteiro.

**É gravado assim, e não só exibido assim.** Foi a escolha feita, com a
alternativa (guardar a grafia original e aplicar caixa alta na tela)
apresentada e recusada. A consequência está escrita aqui porque quem ler
este módulo daqui a dois anos precisa saber: **a grafia original não é
recuperável**. "Nakagawa" e "NAKAGAWA" passam a ser a mesma coisa no
banco, e nome próprio não se reconstrói por regra — não há como saber se
"DA" era "da" ou "Da", nem se "MCDONALD" era "McDonald". A rede de
segurança é o backup cifrado tomado imediatamente antes da migração.

**O acento permanece.** "JOSÉ", e não "JOSE": tirar acento não é
padronizar aparência, é escrever o nome errado. `str.upper()` do Python
já trata acento corretamente.

**O espaço em excesso some junto.** É a mesma operação de padronizar, e
dois espaços no meio de um nome não aparecem na tela — aparecem na busca,
quando ninguém acha "Maria  Silva" procurando por "Maria Silva".
"""


def normalizar_nome(valor):
    """Devolve o nome na forma canônica: caixa alta, espaços colapsados.

    Idempotente: aplicar duas vezes dá o mesmo resultado. Isso importa
    porque esta função roda no `clean()` **e** no `save()` — o primeiro
    para que o formulário já mostre o nome como ele vai ficar, o segundo
    porque paciente nasce por caminhos que não passam por formulário
    nenhum (pré-cadastro da agenda, importação, `seed_demo`).

    `None` e string vazia devolvem string vazia, e não estouram: o campo é
    obrigatório, mas quem valida isso é o formulário, e um normalizador
    que levanta exceção transformaria "campo vazio" em erro 500.
    """
    return ' '.join((valor or '').split()).upper()
