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
