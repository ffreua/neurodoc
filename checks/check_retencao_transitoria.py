"""Dados transitórios somem nos prazos aprovados, e só eles.

Notificação lida fica sete dias desde a leitura; não lida fica quinze dias
desde a criação. O log de entregas e suas tentativas fica quinze dias. As
fronteiras exatas permanecem, e executar a coleta de novo não muda nada.
"""
import uuid

from django.conf import settings as dj_settings
from django.utils import timezone

from communications.models import (
    Delivery, DeliveryAttempt, DeliveryAttemptOutcome, DeliveryChannel,
    DeliveryStatus,
)
from notifications.models import Notification
from patients.models import PatientContact
from scheduling.models import Appointment
from tenancy.models import Membership, Tenant

falhas = []
marca = f'retencao-{uuid.uuid4()}'
referencia = timezone.now() - timezone.timedelta(days=365)


def conferir(rotulo, condicao):
    print(f'  {"ok " if condicao else "FALHA"}  {rotulo}')
    if not condicao:
        falhas.append(rotulo)


tenant = Tenant.objects.get(slug='demo-clinica-a')
# De paciente com contato: a entrega exige um, e o `.first()` sem filtro
# caía às vezes num paciente sem contato nenhum (a demonstração do manual
# acrescenta pacientes assim) e o roteiro quebrava antes de testar.
agendamento = (
    Appointment.objects.filter(tenant=tenant, patient__contacts__isnull=False)
    .select_related('patient').order_by('created_at').first()
)
contato = PatientContact.objects.filter(
    tenant=tenant, patient=agendamento.patient,
).first()
usuario = Membership.objects.filter(
    tenant=tenant, status='active',
).select_related('user').first().user

notificacoes = {}
entregas = {}

try:
    # auto_now_add ignora o valor no create; a data de cada cenário é
    # posicionada explicitamente depois, sem depender do relógio do roteiro.
    for nome in ('lida_vencida', 'lida_fronteira', 'nao_lida_vencida',
                 'nao_lida_fronteira', 'lida_recente'):
        notificacoes[nome] = Notification.objects.create(
            tenant=tenant, user=usuario, kind=marca,
            sanitized_title=f'{marca}-{nome}',
        )

    Notification.objects.filter(id=notificacoes['lida_vencida'].id).update(
        created_at=referencia-timezone.timedelta(days=20),
        read_at=referencia-timezone.timedelta(days=7, seconds=1),
    )
    Notification.objects.filter(id=notificacoes['lida_fronteira'].id).update(
        created_at=referencia-timezone.timedelta(days=20),
        read_at=referencia-timezone.timedelta(days=7),
    )
    Notification.objects.filter(id=notificacoes['nao_lida_vencida'].id).update(
        created_at=referencia-timezone.timedelta(days=15, seconds=1), read_at=None,
    )
    Notification.objects.filter(id=notificacoes['nao_lida_fronteira'].id).update(
        created_at=referencia-timezone.timedelta(days=15), read_at=None,
    )
    Notification.objects.filter(id=notificacoes['lida_recente'].id).update(
        created_at=referencia-timezone.timedelta(days=30),
        read_at=referencia-timezone.timedelta(days=1),
    )

    for nome, idade in (('vencida', timezone.timedelta(days=15, seconds=1)),
                        ('fronteira', timezone.timedelta(days=15)),
                        ('recente', timezone.timedelta(days=2))):
        entrega = Delivery.objects.create(
            tenant=tenant, appointment=agendamento, contact=contato,
            channel=DeliveryChannel.EMAIL, event_version=1,
            status=DeliveryStatus.ACCEPTED,
            idempotency_key=f'{marca}-{nome}',
        )
        Delivery.objects.filter(id=entrega.id).update(created_at=referencia-idade)
        DeliveryAttempt.objects.create(
            tenant=tenant, delivery=entrega, attempt_number=1,
            started_at=referencia-idade, ended_at=referencia-idade,
            outcome=DeliveryAttemptOutcome.ACCEPTED,
        )
        entregas[nome] = entrega

    try:
        from communications.retention import purge_expired_deliveries
        from notifications.retention import purge_expired_notifications
        from communications.tasks import purge_expired_deliveries_task
        from notifications.tasks import purge_expired_notifications_task
    except ImportError as exc:
        falhas.append(f'rotinas de retenção ainda não existem: {exc}')
    else:
        print('\n1. Notificações respeitam leitura e fronteiras')
        resultado = purge_expired_notifications(now=referencia)
        conferir('apagou exatamente duas notificações', resultado['notifications'] == 2)
        conferir('lida há mais de sete dias saiu',
                 not Notification.objects.filter(id=notificacoes['lida_vencida'].id).exists())
        conferir('não lida há mais de quinze dias saiu',
                 not Notification.objects.filter(id=notificacoes['nao_lida_vencida'].id).exists())
        conferir('lida na fronteira de sete dias ficou',
                 Notification.objects.filter(id=notificacoes['lida_fronteira'].id).exists())
        conferir('não lida na fronteira de quinze dias ficou',
                 Notification.objects.filter(id=notificacoes['nao_lida_fronteira'].id).exists())
        conferir('antiga mas lida recentemente ficou',
                 Notification.objects.filter(id=notificacoes['lida_recente'].id).exists())

        print('\n2. Entregas levam as tentativas, sem tocar a fronteira')
        resultado = purge_expired_deliveries(now=referencia)
        conferir('apagou uma entrega', resultado['deliveries'] == 1)
        conferir('apagou a tentativa filha', resultado['attempts'] == 1)
        conferir('entrega vencida saiu',
                 not Delivery.objects.filter(id=entregas['vencida'].id).exists())
        conferir('entrega na fronteira ficou',
                 Delivery.objects.filter(id=entregas['fronteira'].id).exists())
        conferir('entrega recente ficou',
                 Delivery.objects.filter(id=entregas['recente'].id).exists())

        print('\n3. Repetição é idempotente e tarefas estão agendadas')
        conferir('segunda limpeza de notificações não apagou outra linha',
                 purge_expired_notifications(now=referencia)['notifications'] == 0)
        segundo = purge_expired_deliveries(now=referencia)
        conferir('segunda limpeza de entregas não apagou outra linha',
                 segundo == {'deliveries': 0, 'attempts': 0})
        conferir('tarefa de notificações tem nome estável',
                 purge_expired_notifications_task.name == 'notifications.tasks.purge_expired')
        conferir('tarefa de entregas tem nome estável',
                 purge_expired_deliveries_task.name == 'communications.tasks.purge_expired')
        conferir('notificações estão no Celery Beat',
                 'notifications-purge-expired' in dj_settings.CELERY_BEAT_SCHEDULE)
        conferir('entregas estão no Celery Beat',
                 'communications-purge-expired' in dj_settings.CELERY_BEAT_SCHEDULE)
finally:
    DeliveryAttempt.objects.filter(delivery__idempotency_key__startswith=marca).delete()
    Delivery.objects.filter(idempotency_key__startswith=marca).delete()
    Notification.objects.filter(kind=marca).delete()

if falhas:
    for falha in falhas:
        print('FALHA:', falha)
    raise SystemExit(1)

print('\nOK: notificações vencem em 7/15 dias e entregas em 15 dias, com exclusão física.')
