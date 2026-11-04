"""Os dois e-mails da degustação: o de véspera e o do oitavo dia.

Vão a todo **responsável** ativo da clínica, que é quem contrata. Mesmo
caminho de `boas_vindas.py`: `send_email` enfileira para o worker depois do
commit, a falha vai para o log com o inquilino e sem o endereço, e nada
disso desfaz o encerramento — o e-mail é aviso, e o mesmo aviso está na
faixa do alto de toda tela.

O texto não promete o que o servidor recusa: os números (dias, tetos,
limites do Gratuito) saem de `degustacao.py` e de `plans.py`.
"""
import logging

from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def _responsaveis(tenant):
    from .models import Membership, MembershipStatus, Role

    return list(
        Membership.objects.filter(
            tenant_id=tenant.id, status=MembershipStatus.ACTIVE, roles__contains=[Role.OWNER],
        ).select_related('user').values_list('user__email', flat=True)
    )


def contexto(tenant):
    from base.seo import absoluta

    from . import degustacao
    from .limits import describe_limit
    from .plans import max_doctors, max_patients, plan_label

    return {
        'clinica': tenant.trade_name or tenant.legal_name,
        'plano_degustado': plan_label(degustacao.PLANO_DEGUSTADO),
        'plano_depois': plan_label(degustacao.PLANO_DEPOIS),
        'ultimo_dia': degustacao.ultimo_dia(tenant),
        'pacientes_depois': describe_limit(max_patients(degustacao.PLANO_DEPOIS)),
        'medicos_depois': describe_limit(max_doctors(degustacao.PLANO_DEPOIS)),
        'retirados': len(tenant.degustacao_retirados or []),
        'url_contratar': absoluta(reverse('onboarding:landing')) + '#contato',
        'url_equipe': absoluta(reverse('tenancy:team')),
        'url_entrar': absoluta(reverse('accounts:login')),
    }


def _enviar(tenant, assunto, modelo):
    from communications.email import send_email

    corpo = render_to_string(modelo, contexto(tenant))
    enviados = 0
    for email in _responsaveis(tenant):
        try:
            send_email(email, assunto, corpo, tenant_id=tenant.id)
            enviados += 1
        except Exception:                                   # noqa: BLE001
            logger.warning('degustacao: falha ao enfileirar aviso (tenant=%s)', tenant.id, exc_info=True)
    return enviados


def avisar_que_acaba(tenant):
    nome = tenant.trade_name or tenant.legal_name
    return _enviar(tenant, f'A degustação do NeuroDoc está acabando — {nome}',
                   'tenancy/email/degustacao_acabando.txt')


def avisar_fim(tenant):
    nome = tenant.trade_name or tenant.legal_name
    return _enviar(tenant, f'A degustação do NeuroDoc terminou — {nome}',
                   'tenancy/email/degustacao_fim.txt')
