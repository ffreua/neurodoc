from celery import shared_task

from .reconciliation import reconcile_pending_sms


@shared_task(name='communications.tasks.reconcile_pending_sms')
def reconcile_pending_sms_task():
    return reconcile_pending_sms()


@shared_task(name='communications.tasks.run_campaign_batch', expires=300)
def run_campaign_batch(campaign_id):
    """Envia uma fatia da campanha e reagenda a próxima para daqui a um minuto.

    Reagendar em vez de dormir: um `sleep` de sessenta segundos dentro da
    tarefa prende um worker que tem outras filas para atender, e uma
    campanha de mil pessoas prenderia o worker por quase uma hora.

    A tarefa é o único lugar que avança a campanha, e ela para sozinha
    quando o estado deixa de ser "enviando" — é assim que o botão de pausar
    funciona sem precisar cancelar tarefa nenhuma na fila.
    """
    from .marketing import send_batch
    from .models import CampaignStatus, MarketingCampaign

    campaign = MarketingCampaign.objects.filter(id=campaign_id).first()
    if campaign is None or campaign.status != CampaignStatus.SENDING:
        return {'skipped': True}

    resultado = send_batch(campaign)
    if resultado['restantes']:
        campaign.refresh_from_db(fields=['status'])
        if campaign.status == CampaignStatus.SENDING:
            run_campaign_batch.apply_async((str(campaign.id),), countdown=60)
    return resultado


@shared_task(
    name='communications.tasks.deliver_installation_email',
    autoretry_for=(OSError,), retry_backoff=True, retry_backoff_max=600,
    max_retries=5, retry_jitter=True,
)
def deliver_installation_email(dados):
    """Fala com o servidor SMTP da instalação. Roda no worker.

    É o outro lado de `communications.mail_backend.WorkerEmailBackend`:
    a view enfileira, e a entrega acontece aqui, onde existe saída para a
    internet e onde a senha do SMTP está disponível.

    A conexão é pedida **explicitamente** pelo backend SMTP, e não pelo
    padrão das configurações. Sem isso, o worker leria `EMAIL_BACKEND`,
    encontraria o backend que enfileira, e a mensagem daria voltas na fila
    para sempre.

    `OSError` cobre a família de falhas de rede e de `smtplib` (que herda
    de `OSError`): servidor fora do ar, recusa temporária, nome que não
    resolve. Repetir com espera crescente é o certo aí — a alternativa é
    perder um e-mail de confirmação de conta porque o SMTP piscou.
    """
    from django.core.mail import EmailMultiAlternatives, get_connection

    mensagem = EmailMultiAlternatives(
        subject=dados['subject'], body=dados['body'],
        from_email=dados['from_email'], to=dados['to'],
        cc=dados.get('cc') or None, bcc=dados.get('bcc') or None,
        reply_to=dados.get('reply_to') or None,
    )
    for conteudo, tipo in dados.get('alternatives') or []:
        mensagem.attach_alternative(conteudo, tipo)

    conexao = get_connection(backend='django.core.mail.backends.smtp.EmailBackend')
    enviadas = conexao.send_messages([mensagem])
    return {'enviadas': enviadas}
