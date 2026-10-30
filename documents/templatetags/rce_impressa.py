"""A trava da RCE impressa na tela do documento (`documents/rce_impressa.py`)."""

from django import template

from documents import rce_impressa

register = template.Library()


@register.simple_tag
def rce_assinatura_bloqueada(document):
    return rce_impressa.assinatura_digital_bloqueada(document)
