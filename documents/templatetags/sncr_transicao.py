"""O aviso transitório do SNCR nas telas da receita.

Tag e não variável de contexto: o aviso aparece em mais de uma tela
(formulário e documento) e em mais de um caminho de cada uma (a tela
normal e a recusa da assinatura, que renderiza o mesmo template com
contexto próprio). Uma tag não depende de cada view lembrar de passar o
aviso — e sai junto com o módulo quando a integração entrar.
"""

from django import template

from documents import sncr_transicao

register = template.Library()


@register.simple_tag
def aviso_sncr(document=None, formato=None):
    return sncr_transicao.aviso(document=document, formato=formato)


@register.simple_tag
def rce_assinatura_bloqueada(document):
    return sncr_transicao.assinatura_digital_bloqueada(document)
