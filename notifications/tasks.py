from celery import shared_task


@shared_task(name='notifications.tasks.purge_expired')
def purge_expired_notifications_task():
    from .retention import purge_expired_notifications

    return purge_expired_notifications()


@shared_task(name='notifications.tasks.enviar_push', ignore_result=True)
def enviar_push(user_ids, tipo, url='', tag='', ttl=86400):
    """O aviso no celular (`notifications.push.enviar`).

    Sem nova tentativa automática: o aviso que chega dez minutos atrasado
    já não serve para nada, e o aparelho que falhou fica para o próximo.
    """
    from .push import enviar

    return enviar(user_ids, tipo, url, tag, ttl)


@shared_task(name='notifications.tasks.enviar_push_teste', ignore_result=True)
def enviar_push_teste(inscricao_id):
    """O aviso de teste, só para o aparelho que pediu."""
    from .models import PushSubscription
    from .push import enviar

    inscricao = PushSubscription.objects.filter(pk=inscricao_id).first()
    if inscricao is None:
        return None
    from django.urls import reverse

    from django.core.cache import cache

    resultado = enviar([inscricao.user_id], 'teste', reverse('notifications:list'), 'teste', 300,
                       somente=[inscricao.pk])
    # A tela espera por isto (`views.PushTestarView`): a resposta do serviço
    # de push, para quem testa saber se o aviso saiu, e o que o recusou.
    cache.set(f'push:teste:{inscricao_id}', resultado, 120)
    return resultado


@shared_task(name='notifications.tasks.enviar_comunicado', ignore_result=True)
def enviar_comunicado(comunicado_id):
    """O comunicado do console (`notifications.comunicados.enviar`)."""
    from .comunicados import enviar

    return enviar(comunicado_id)
