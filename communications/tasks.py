from celery import shared_task

from .reconciliation import reconcile_pending_sms


@shared_task(name='communications.tasks.purge_expired')
def purge_expired_deliveries_task():
    from .retention import purge_expired_deliveries

    return purge_expired_deliveries()


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


@shared_task(
    name='communications.tasks.deliver_document',
    autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3},
    expires=600, bind=True,
)
def deliver_document_task(self, document_id, force_new_link=False):
    """Entrega (ou reentrega) um documento, **no worker**.

    O envio automático já nascia aqui: ele vem do evento
    `documents.document_issued`, despachado por `events.tasks.dispatch_outbox`,
    que roda no worker. O **reenvio pela tela** é que não: ele chamava
    `deliver_document` dentro da requisição, no processo `app` (ver
    `communications/mail_backend.py` e o comentário de `EMAIL_BACKEND` em
    `core/settings.py`).

    O e-mail escapava porque o backend dele já enfileira sozinho. O SMS
    não: `smsdev.send_sms` fazia a requisição na hora, dentro da
    requisição do navegador — sem retentativa, e com a tela presa ao
    tempo do provedor. Uma falha ali derrubava a resposta com o documento
    já assinado, que foi exatamente o que aconteceu.
    """
    from documents.models import MedicalDocument

    from .services import deliver_document

    document = MedicalDocument.objects.filter(id=document_id).first()
    if document is None:
        return 0
    # O id da tarefa é o mesmo em cada nova tentativa: é com ele que a
    # repetição reconhece o que a volta anterior já mandou (ver
    # `deliver_document`).
    return len(deliver_document(
        document, force_new_link=force_new_link, envio_id=self.request.id,
    ))


@shared_task(
    name='communications.tasks.send_confirmation',
    autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3},
    expires=600, bind=True,
)
def send_confirmation_task(self, appointment_id, channel, actor_id, contact_id=None):
    """Envia a confirmação do horário **no worker**.

    Era a última entrega que saía de dentro da requisição, e isso tinha
    uma consequência que só aparece em instalação com mais de uma
    clínica: **o processo `app` não recebe o secret do SMSDEV** (§2 — a
    chave de egresso é do worker). A clínica que informou a própria
    chave funcionava, porque essa fica cifrada no banco e o `app` sabe
    decifrá-la; a clínica que depende da chave da instalação recebia
    `SmsChannelDisabled` e nada saía.

    Foi exatamente o que aconteceu em 06/10/2026: a primeira clínica
    tinha chave própria e nunca viu o defeito; a segunda, no plano
    Completo e sem chave, não recebeu um SMS sequer — e a entrega ficou
    registrada como "sem contato cadastrado".

    O e-mail escapava, de novo, porque o backend dele já enfileira
    sozinho. É o mesmo par de causa e sintoma de `deliver_document_task`,
    na entrega de documento — ali foi corrigido antes, aqui ficou.
    """
    from scheduling.models import Appointment

    from .services import NoUsableContact, send_appointment_confirmation

    appointment = Appointment.objects.filter(id=appointment_id).select_related('tenant').first()
    if appointment is None:
        return {'status': 'skipped'}

    contato = None
    if contact_id:
        from patients.models import PatientContact

        contato = PatientContact.objects.filter(
            tenant_id=appointment.tenant_id, id=contact_id,
        ).first()

    # `context=None`: quem autoriza é a view, antes de enfileirar — a
    # capacidade de mexer na agenda é de quem clicou, e reconstruí-la
    # aqui daria a impressão de que a fila reautoriza, que ela não faz.
    # `send_appointment_confirmation` não lê o parâmetro; o `actor_id`,
    # que é o que vai para a trilha, continua sendo o de quem clicou.
    try:
        entrega = send_appointment_confirmation(
            None, appointment, channel, actor_id, contact=contato, envio_id=self.request.id,
        )
    except NoUsableContact:
        # A view já confere isto antes de enfileirar; chegar aqui
        # significa que o contato sumiu no meio do caminho. Não é motivo
        # para repetir a tarefa três vezes.
        return {'status': 'no_contact'}
    return {'status': entrega.status, 'delivery_id': str(entrega.id)}
