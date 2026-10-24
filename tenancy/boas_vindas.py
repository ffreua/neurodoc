"""O e-mail de boas-vindas da clínica recém-cadastrada.

Existe por causa de um tropeço de quem acabou de chegar: a clínica nasce
só com o **responsável** (`services.accept_platform_invitation`), e o
responsável não abre prontuário — a matriz de `permissions.py` só entrega
leitura e escrita clínica ao papel médico. Quem cadastrava a clínica
entrava, procurava "Novo atendimento" e não achava, sem nada dizendo que
faltava cadastrar um médico. O aviso agora chega por dois caminhos: este
e-mail, que se lê uma vez, e a faixa no alto de toda tela de `/app/`
(`base/context_processors.py`, `nd_sem_medico`), que fica até o problema
ser resolvido.

O texto que muda conforme o plano (IA, SMS) é lido de `plans.py`, e não
escrito no template: o e-mail que diz "o seu plano inclui SMS" para uma
clínica do Gratuito é uma promessa que o servidor recusa no primeiro
lembrete.

Os links saem de `PUBLIC_BASE_URL` (`base.seo.absoluta`), nunca do `Host:`
da requisição — é um e-mail, e ele continua sendo lido depois que a
requisição acabou.
"""

import logging

from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)

#: O artigo do manual para onde o e-mail aponta (`base/help_content.py`).
ARTIGO_PRIMEIROS_PASSOS = 'primeiros-passos'


def contexto(tenant, user):
    from base.seo import absoluta

    from .plans import has_clinical_ai, has_sms, plan_label

    return {
        'clinica': tenant.trade_name or tenant.legal_name,
        'plano': plan_label(tenant.plan),
        'tem_ia': has_clinical_ai(tenant.plan),
        'tem_sms': has_sms(tenant.plan),
        'url_primeiros_passos': absoluta(
            reverse('onboarding:help-article', args=[ARTIGO_PRIMEIROS_PASSOS]),
        ),
        'url_manual': absoluta(reverse('onboarding:help')),
        'url_equipe': absoluta(reverse('tenancy:team')),
        'url_entrar': absoluta(reverse('accounts:login')),
    }


def assunto(tenant):
    return f'Boas-vindas ao NeuroDoc — {tenant.trade_name or tenant.legal_name}'


def corpo(tenant, user):
    return render_to_string('tenancy/email/boas_vindas.txt', contexto(tenant, user))


def enviar_boas_vindas(tenant, user):
    """Enfileira o e-mail. Devolve `True` se ele foi aceito para envio.

    Chamado depois de a clínica existir, fora da transação que a criou: a
    falha de e-mail não desfaz cadastro nem aceite. Sai pelo mesmo caminho
    de toda mensagem da instalação (`send_email` → backend do worker, só
    depois do commit), e não de dentro da requisição (CLAUDE.md §2).

    Não há coluna para registrar o envio, de propósito: diferente da via do
    contrato, que é prova e tem de poder ser reenviada, este e-mail é
    orientação — e o mesmo conteúdo está no manual público e no aviso da
    tela. A falha vai para o log, com o inquilino e sem o endereço.
    """
    from communications.email import send_email

    try:
        send_email(user.email, assunto(tenant), corpo(tenant, user), tenant_id=tenant.id)
    except Exception:  # noqa: BLE001
        logger.warning('boas_vindas: falha ao enfileirar (tenant=%s)', tenant.id, exc_info=True)
        return False
    return True
