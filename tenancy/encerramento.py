"""O e-mail ao responsável quando a clínica é encerrada (2026-11).

Encerrar (`TenantStatus.CLOSED`) fecha a porta: ninguém mais entra. Até
aqui a única notícia disso era a tela de "organização encerrada", vista
por quem tentasse entrar — e o responsável podia descobrir o encerramento
semanas depois, já dentro do prazo de 90 dias que a cláusula 13.1 lhe dá
para obter os dados. O e-mail diz no dia, por escrito, **por quê** (o
motivo que o console já exige ao mudar o estado) e o que fazer.

Três decisões:

- **vai a todo responsável ativo**, e só a eles. É o papel que responde
  pela CONTRATANTE; médico e secretária perdem o acesso junto, mas quem
  decide o que fazer com o acervo é o responsável;
- **sai pelo remetente da instalação**, e não pelo da clínica (`send_email`
  sem `tenant_id`): o servidor SMTP de uma clínica encerrada não é por onde
  o NeuroDoc fala com ela, e pode já nem existir;
- **o motivo vai como foi escrito.** O console avisa, no campo, que ao
  encerrar ele é enviado ao responsável — quem escreve sabe que está
  escrevendo para a clínica, e não uma nota interna.

Nada clínico entra no e-mail, nem a contagem de pacientes.
"""

import logging

from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def destinatarios(tenant):
    from .models import Membership, MembershipStatus, Role

    return sorted({
        m.user.email for m in Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE,
            roles__contains=[Role.OWNER], user__is_active=True,
        ).select_related('user') if m.user.email
    })


def assunto(tenant):
    return f'NeuroDoc — encerramento da organização {tenant.trade_name or tenant.legal_name}'


def corpo(tenant):
    from django.urls import reverse

    from base.seo import absoluta

    return render_to_string('tenancy/email/encerramento.txt', {
        'clinica': tenant.trade_name or tenant.legal_name,
        'razao_social': tenant.legal_name,
        'documento': f'{tenant.documento_rotulo} {tenant.documento_formatado}',
        'data': timezone.localtime(tenant.status_changed_at or timezone.now()).strftime('%d/%m/%Y'),
        'motivo': tenant.status_note,
        'url_contrato': absoluta(reverse('onboarding:contrato')),
    })


def avisar_encerramento(tenant):
    """Enfileira o e-mail a cada responsável. Devolve quantos foram aceitos.

    Chamado depois de o estado ter sido gravado, e a falha não desfaz o
    encerramento — vai para o log, com o inquilino e sem o endereço, e o
    console diz quantos e-mails saíram.
    """
    from communications.email import send_email

    texto = corpo(tenant)
    enviados = 0
    for email in destinatarios(tenant):
        try:
            send_email(email, assunto(tenant), texto)
        except Exception:                                   # noqa: BLE001
            logger.warning('encerramento: falha ao enfileirar (tenant=%s)', tenant.id, exc_info=True)
            continue
        enviados += 1
    return enviados
