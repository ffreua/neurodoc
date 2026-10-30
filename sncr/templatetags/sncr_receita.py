"""O que a tela do documento mostra da receita eletrônica do SNCR."""

from django import template

register = template.Library()

_RECEITUARIO = {
    'rce': 'Receita de Controle Especial',
    'notificacao_a': 'Notificação de Receita A',
    'notificacao_b': 'Notificação de Receita B',
    'notificacao_b2': 'Notificação de Receita B2',
    'notificacao_retinoide': 'Notificação de Receita de retinoide',
    'notificacao_talidomida': 'Notificação de Receita de talidomida',
    'sem_retencao': 'sem retenção',
    'proscrita': 'uso proibido',
}


@register.simple_tag
def receita_sncr(document):
    """`None` para documento que não é receita eletrônica do SNCR."""
    from sncr.pdf_oficial import numeros_do_documento
    from sncr.receita import eh_eletronica, tipo_do_documento

    if not eh_eletronica(document):
        return None
    snapshot = document.content_snapshot or {}
    meta = (document.signature_metadata or {}).get('sncr') or {}
    # Um número por folha, na ordem dos medicamentos (decisão I12). Só a
    # emitida tem número; a lista vazia deixa cada linha sem.
    numeros = (meta.get('numeros') or numeros_do_documento(document)) if document.status == 'issued' else []
    itens = []
    for n, (item, cls) in enumerate(zip(snapshot.get('itens') or [], snapshot.get('classificacao') or [])):
        itens.append({
            'item': item,
            'numero': numeros[n] if n < len(numeros) else '',
            'origem': cls.get('origem'),
            'substancias': [
                dict(s, receituario_texto=_RECEITUARIO.get(s.get('receituario'), s.get('receituario')))
                for s in cls.get('substancias') or []
            ],
        })
    return {
        'tipo': tipo_do_documento(document),
        'numeros': numeros,
        'folhas': len(itens),
        'homologacao': meta.get('ambiente') == 'homologacao',
        'itens': itens,
        'confirmada': snapshot.get('classificacao_confirmada'),
        'lista_oficial': snapshot.get('lista_oficial'),
    }


@register.simple_tag
def saldos_sncr(user):
    """Os números livres do médico logado, para o formulário da receita.

    `None` com a integração desligada ou sem perfil profissional. É o que
    poupa o médico de descobrir na assinatura que o bloco acabou: o saldo
    está na tela em que ele escreve a receita, com o caminho para pedir.
    """
    from accounts.models import PhysicianProfile
    from sncr.models import Configuracao, TipoReceita
    from sncr.numeracao import saldo

    config = Configuracao.carregar()
    perfil = PhysicianProfile.objects.filter(user=user).first() if getattr(user, 'pk', None) else None
    if not config.ativo or perfil is None:
        return None
    return {
        'rce': saldo(perfil, TipoReceita.RCE, config.ambiente),
        'ret': saldo(perfil, TipoReceita.RET, config.ambiente),
        'ambiente': config.get_ambiente_display(),
        'homologacao': config.ambiente == 'homologacao',
    }
