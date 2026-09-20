"""Quem pediu contato pela página de vendas.

Fica em `tenancy` porque um lead é a pré-história de um inquilino: ele
vira `Invitation` e depois `Tenant`, e quem o lê é quem opera a
instalação, no mesmo console. O app `crm` foi removido do produto em
08/09/2026 (PRD 25.9) e não se ressuscita um funil inteiro para guardar
sete campos.

## Gravar antes de enviar

O pedido é gravado **antes** de o e-mail ser enfileirado. Com o envio
direto, o SMTP fora significaria lead perdido — e lead perdido é a única
falha desta tela que ninguém percebe, porque quem preencheu vê a mesma
mensagem de sucesso.

## Destinatário fixo no servidor

`settings.LEADS_EMAIL`, nunca um campo do formulário. Formulário público
que aceita destinatário do cliente é um relay aberto: qualquer um mandaria
mensagem com o remetente do domínio da clínica para qualquer endereço.
"""

import re

from django.conf import settings
from base.net import client_ip

#: Quantos pedidos por IP, e em quanto tempo. Generoso de propósito: uma
#: clínica atrás de um NAT pode ter várias pessoas olhando ao mesmo tempo,
#: e barrar um lead legítimo custa mais caro do que receber três repetidos.
RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 900

#: Versão do aviso de privacidade que a pessoa aceitou ao enviar. Gravada
#: junto: demonstrar consentimento exige saber **a que** se consentiu, e
#: o texto muda com o tempo.
PRIVACY_NOTICE_VERSION = '2026-09-12'


def rate_limited(request):
    """Conta pedidos por IP. Falha **aberto** se a cache estiver fora.

    A mesma escolha do portal do paciente, pela mesma razão: falhar
    fechado transformaria uma indisponibilidade do Redis em página de
    vendas que não recebe contato. O risco aceito é o inverso — durante a
    indisponibilidade, um robô passaria, e o registro fica no banco.
    """
    from django.core.cache import cache

    ip = client_ip(request)
    key = f'leads:{ip}'
    try:
        cache.get_or_set(key, 0, RATE_WINDOW_SECONDS)
        return cache.incr(key) > RATE_LIMIT
    except Exception:                                   # noqa: BLE001
        return False


def _resumo(lead):
    """O corpo do e-mail de aviso. Texto simples, e só o que foi digitado."""
    from .plans import plan_label

    linhas = [
        'Novo pedido de contato pela página de vendas do NeuroDoc.',
        '',
        f'Nome:     {lead.name}',
        f'E-mail:   {lead.email}',
        f'Telefone: {lead.phone or "não informado"}',
        f'Clínica:  {lead.clinic_name or "não informada"}',
        f'Plano:    {plan_label(lead.plan) if lead.plan else "não indicado"}',
        '',
        'Mensagem:',
        lead.message or '(sem mensagem)',
        '',
        f'Recebido em {lead.created_at:%d/%m/%Y %H:%M}.',
    ]
    return '\n'.join(linhas)


def notify(lead):
    """Avisa o endereço comercial. Falha aqui não perde o lead.

    O erro é gravado em `notify_error` e a tela continua respondendo
    sucesso a quem preencheu — porque, do ponto de vista dela, o pedido
    **foi** recebido: está no banco. Dizer "erro, tente de novo" faria a
    pessoa reenviar um pedido que já chegou.
    """
    from django.utils import timezone

    from communications.email import send_email

    try:
        send_email(
            settings.LEADS_EMAIL,
            f'[NeuroDoc] Contato de {lead.name}',
            _resumo(lead),
        )
    except Exception as exc:                            # noqa: BLE001
        # A mensagem é truncada e guardada; o corpo do erro pode trazer
        # endereço de servidor e usuário de SMTP, então nada disso vai
        # para a tela de quem preencheu.
        lead.notify_error = f'{type(exc).__name__}: {exc}'[:255]
        lead.save(update_fields=['notify_error', 'updated_at'])
        return False
    lead.notified_at = timezone.now()
    lead.notify_error = ''
    lead.save(update_fields=['notified_at', 'notify_error', 'updated_at'])
    return True


def normalize_phone(raw):
    """Só os dígitos, com o `+` inicial quando houver.

    Guardar a máscara digitada faria dois pedidos da mesma pessoa
    parecerem de pessoas diferentes.
    """
    bruto = (raw or '').strip()
    digitos = re.sub(r'\D', '', bruto)
    if not digitos:
        return ''
    return ('+' if bruto.startswith('+') else '') + digitos[:30]
