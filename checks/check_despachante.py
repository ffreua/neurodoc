"""O despachante da outbox e os consumidores que ele chama.

Nasceu da auditoria externa de 2026-10-09, que leu o despachante e achou
oito defeitos de coordenação. Este roteiro cobre os que foram corrigidos,
cada um pelo caminho que o quebrava -- e contra o PostgreSQL de verdade,
que é onde o `UPDATE` condicional e o `select_for_update` valem:

1. **posse do lease**: quem perdeu o evento para outro despachante não
   roda o consumidor nem grava o desfecho (A1);
2. a posse é conferida **antes de cada consumidor**, e não só no começo;
3. o consumidor roda **fora** de uma transação externa -- o que ele grava
   está visível para outras conexões antes de ele mandar qualquer coisa
   para fora (A3, A4);
4. falha de consumidor **deixa log com nome** (A8);
5. evento sem consumidor **não gasta tentativa** (A7);
6. o aviso ao paciente mede a idade por `created_at` (A6);
7. o lembrete confere o estado da consulta e se foi substituído (A5), e
   **não** cala o lembrete da consulta confirmada;
8. o job de IA parado na fila é retomado, e o abandonado vira falha
   explicada (A3).

Detalhe em `docs/homologation/despachante-da-outbox.md`.
"""
import logging
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings as dj_settings
from django.db import connection
from django.utils import timezone

from events import dispatcher
from events.models import OutboxEvent, OutboxEventStatus, ProcessedEvent
from scheduling.models import Appointment
from tenancy.models import Membership

failures = []
raiz = Path(dj_settings.BASE_DIR)


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


class _Captura(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.registros = []

    def emit(self, record):
        self.registros.append(record)


def capturar(nome):
    logger = logging.getLogger(nome)
    captura = _Captura()
    logger.addHandler(captura)
    nivel_antes = logger.level
    logger.setLevel(logging.DEBUG)
    return logger, captura, nivel_antes


membro = Membership.objects.select_related('tenant').first()
if membro is None:
    print('FALTA DADO: nenhum vinculo no banco; o roteiro nao pode afirmar nada')
    raise SystemExit(1)
tenant = membro.tenant

PREFIXO = f'roteiro.despachante.{uuid.uuid4().hex[:8]}'
criados = []


def evento_em_posse(sufixo, attempts=1, topic=None):
    """Um evento já reclamado, como `_claim_batch` o devolveria.

    Nasce em `processing` com o prazo no futuro, e não `pending`: assim o
    worker local, que despacha a cada cinco segundos, não o disputa com
    este roteiro.
    """
    ev = OutboxEvent.objects.create(
        tenant=tenant, topic=topic or f'{PREFIXO}.{sufixo}', aggregate_type='roteiro',
        aggregate_id=uuid.uuid4(), event_version=1, payload_minimal={},
        status=OutboxEventStatus.PROCESSING, available_at=timezone.now(),
        locked_until=timezone.now() + timedelta(seconds=dispatcher.LEASE_SECONDS),
        attempts=attempts,
    )
    criados.append(ev.id)
    return OutboxEvent.objects.get(id=ev.id)


def outro_despachante_toma(ev):
    """O que `_claim_batch` faz com um lease vencido, visto de fora."""
    OutboxEvent.objects.filter(id=ev.id).update(
        locked_until=timezone.now() + timedelta(seconds=dispatcher.LEASE_SECONDS, microseconds=7),
        attempts=ev.attempts + 1,
    )


chamadas = []

try:
    print('=== 1. quem perdeu a posse nao roda o consumidor ===')
    dispatcher.register_handler(f'{PREFIXO}.posse', 'roteiro.posse', lambda e: chamadas.append(e.id))
    velho = evento_em_posse('posse')
    outro_despachante_toma(velho)
    resultado = dispatcher._process_one(velho)
    confere(resultado == 'lease_lost', 'o despachante antigo reconhece que perdeu', resultado)
    confere(chamadas == [], 'e nao roda o consumidor -- era o que a auditoria reproduziu')
    agora = OutboxEvent.objects.get(id=velho.id)
    confere(agora.status == OutboxEventStatus.PROCESSING,
            'nem grava o desfecho por cima do novo dono', agora.status)
    confere(not ProcessedEvent.objects.filter(event_id=velho.id).exists(),
            'nem deixa marcador de processado')

    novo = OutboxEvent.objects.get(id=velho.id)
    resultado = dispatcher._process_one(novo)
    confere(resultado == 'completed', 'o dono atual processa normalmente', resultado)
    confere(chamadas == [velho.id], 'uma vez so', str(len(chamadas)))

    print('=== 2. a posse e conferida antes de cada consumidor ===')
    segundo = []

    def primeiro_consumidor(e):
        # Enquanto este consumidor roda, outro despachante toma o evento.
        outro_despachante_toma(OutboxEvent.objects.get(id=e.id))

    dispatcher.register_handler(f'{PREFIXO}.meio', 'roteiro.meio.a', primeiro_consumidor)
    dispatcher.register_handler(f'{PREFIXO}.meio', 'roteiro.meio.b', lambda e: segundo.append(e.id))
    ev = evento_em_posse('meio')
    resultado = dispatcher._process_one(ev)
    confere(resultado == 'lease_lost', 'perde a posse no meio e para', resultado)
    confere(segundo == [], 'o segundo consumidor nao comeca depois de a posse ter passado')

    print('=== 3. o consumidor roda fora de transacao externa ===')
    visto = {}

    def consumidor_que_olha(e):
        visto['em_transacao'] = connection.in_atomic_block

    dispatcher.register_handler(f'{PREFIXO}.transacao', 'roteiro.transacao', consumidor_que_olha)
    dispatcher._process_one(evento_em_posse('transacao'))
    confere(visto.get('em_transacao') is False,
            'nenhum atomic em volta: o que o consumidor grava ja esta visivel '
            'antes de ele mandar SMS ou publicar na fila', str(visto))

    print('=== 4. falha de consumidor deixa log com nome ===')
    logger, captura, nivel = capturar('events.dispatcher')

    def consumidor_que_quebra(e):
        raise RuntimeError('falha sintetica do roteiro')

    dispatcher.register_handler(f'{PREFIXO}.falha', 'roteiro.falha', consumidor_que_quebra)
    try:
        ev = evento_em_posse('falha')
        resultado = dispatcher._process_one(ev)
        confere(resultado == 'retrying', 'volta para nova tentativa', resultado)
        reg = [r for r in captura.registros if getattr(r, 'consumer', '') == 'roteiro.falha']
        confere(bool(reg), 'o log diz qual consumidor falhou')
        if reg:
            confere(getattr(reg[0], 'event_id', '') == str(ev.id), 'e qual evento')
            confere(getattr(reg[0], 'error_class', '') == 'RuntimeError', 'e que classe de erro')
            confere(reg[0].exc_info is not None, 'com o traceback para diagnostico')
        confere(not ProcessedEvent.objects.filter(event_id=ev.id).exists(),
                'e nao marca como processado o que falhou')
        confere(OutboxEvent.objects.get(id=ev.id).status == OutboxEventStatus.PENDING,
                'o evento volta a pendente')

        captura.registros.clear()
        ultimo = evento_em_posse('falha', attempts=dispatcher.MAX_ATTEMPTS)
        resultado = dispatcher._process_one(ultimo)
        confere(resultado == 'failed', 'na ultima tentativa, abandona', resultado)
        confere(any(r.levelno >= logging.ERROR and 'abandonado' in r.getMessage()
                    for r in captura.registros),
                'e o abandono sai como erro no log, nao em silencio')
    finally:
        logger.removeHandler(captura)
        logger.setLevel(nivel)

    print('=== 5. evento sem consumidor nao gasta tentativa ===')
    orfao = evento_em_posse('ninguem.consome', attempts=1, topic=f'semdono.{PREFIXO}')
    resultado = dispatcher._process_one(orfao)
    confere(resultado == 'no_handler', 'reconhece que nao ha consumidor', resultado)
    orfao.refresh_from_db()
    confere(orfao.attempts == 0,
            'a tentativa do claim e devolvida -- o contador chegou a 2.886 em producao',
            str(orfao.attempts))
    confere(orfao.status == OutboxEventStatus.PENDING, 'e o evento espera, pendente')

    print('=== 6. o aviso ao paciente mede a idade pelo created_at ===')
    from communications.handlers import _aviso

    logger, captura, nivel = capturar('communications.handlers')
    try:
        class _EventoEmpurrado:
            """Nasceu ha dez dias; o despachante o empurrou ha um minuto."""
            topic = 'scheduling.appointment_reserved'
            event_version = 1
            created_at = timezone.now() - timedelta(days=10)
            available_at = timezone.now() - timedelta(minutes=1)
            payload_minimal = {'appointment_id': str(uuid.uuid4())}

        _aviso(_EventoEmpurrado(), 'booked')
        confere(any('evento antigo' in r.getMessage() for r in captura.registros),
                'o evento de dez dias e barrado mesmo com available_at recente')
    finally:
        logger.removeHandler(captura)
        logger.setLevel(nivel)
    fonte = Path(raiz, 'communications', 'handlers.py').read_text(encoding='utf-8')
    corpo_aviso = fonte.split('def _aviso(')[1].split('\ndef ')[0]
    confere('event.available_at' not in corpo_aviso.replace('`available_at`', ''),
            'e o codigo nao le mais available_at para medir idade')

    print('=== 7. o lembrete confere o estado de agora ===')
    from communications import services as com_services
    from scheduling import handlers as sched_handlers
    from scheduling.events import REMINDER_TOPIC_PREFIX
    from scheduling.models import AppointmentStatus

    base = Appointment.objects.select_related('patient').first()
    if base is None:
        confere(False, 'FALTA DADO: nenhum agendamento no banco para o lembrete')
    else:
        alcancou = []
        original = com_services._eligible_reminder_contacts
        com_services._eligible_reminder_contacts = lambda p: alcancou.append(p.id) or []
        inicio = timezone.now() + timedelta(days=2)
        ap = Appointment.objects.create(
            tenant_id=base.tenant_id, patient=base.patient, physician_membership=base.physician_membership,
            starts_at=inicio, ends_at=inicio + timedelta(minutes=30),
            occupied_range=(inicio + timedelta(days=3650), inicio + timedelta(days=3650, minutes=30)),
            status=AppointmentStatus.SCHEDULED, type=base.type,
        )
        try:
            def tentar(status, starts_at=None):
                alcancou.clear()
                Appointment.objects.filter(id=ap.id).update(
                    status=status, starts_at=starts_at or inicio,
                )
                ap.refresh_from_db()
                com_services.deliver_appointment_reminder(ap, 1)
                return bool(alcancou)

            confere(tentar(AppointmentStatus.SCHEDULED),
                    'agendada: o lembrete segue -- senao o resto mede o nada')
            confere(tentar(AppointmentStatus.CONFIRMED),
                    'confirmada: segue (confirmar sobe a versao e nao pode calar o lembrete)')
            for status in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW,
                           AppointmentStatus.CHECKED_IN, AppointmentStatus.COMPLETED):
                confere(not tentar(status), f'{status}: nao sai lembrete')
            confere(not tentar(AppointmentStatus.SCHEDULED, timezone.now() - timedelta(minutes=5)),
                    'consulta que ja comecou: nao sai lembrete')

            # Remarcada: o lembrete da versao antiga foi substituido.
            Appointment.objects.filter(id=ap.id).update(status=AppointmentStatus.SCHEDULED, starts_at=inicio)
            entregues = []
            original_handler = sched_handlers.deliver_appointment_reminder
            sched_handlers.deliver_appointment_reminder = lambda a, v: entregues.append(v)
            try:
                topico = f'{REMINDER_TOPIC_PREFIX}.24h'
                eventos = []
                for versao in (1, 2):
                    eventos.append(OutboxEvent.objects.create(
                        tenant_id=base.tenant_id, topic=topico, aggregate_type='appointment',
                        aggregate_id=ap.id, event_version=versao,
                        payload_minimal={'appointment_id': str(ap.id), 'hours_before': 24},
                        status=OutboxEventStatus.CANCELLED, available_at=inicio - timedelta(hours=24),
                    ))
                criados.extend(e.id for e in eventos)
                sched_handlers.handle_appointment_reminder(eventos[0])
                confere(entregues == [], 'versao antiga com lembrete mais novo: nao sai', str(entregues))
                sched_handlers.handle_appointment_reminder(eventos[1])
                confere(entregues == [2], 'a versao mais nova sai', str(entregues))
            finally:
                sched_handlers.deliver_appointment_reminder = original_handler
        finally:
            com_services._eligible_reminder_contacts = original
            OutboxEvent.objects.filter(aggregate_id=ap.id).delete()
            ap.delete()

    print('=== 8. job de IA parado na fila e retomado ===')
    from ai import tasks as ai_tasks
    from ai.models import AIJob, AIJobKind, AIJobStatus
    from notifications.models import Notification

    fonte = Path(raiz, 'ai', 'handlers.py').read_text(encoding='utf-8')
    confere('transaction.on_commit(lambda: run_ai_job.delay' in fonte,
            'o resumo automatico vai para a fila depois do commit')
    confere('ai-retomar-jobs-parados' in dj_settings.CELERY_BEAT_SCHEDULE,
            'a retomada esta agendada no beat')

    publicados = []
    original_delay = ai_tasks.run_ai_job.delay
    ai_tasks.run_ai_job.delay = lambda job_id: publicados.append(job_id)
    jobs = []
    try:
        for idade, sufixo in ((timedelta(minutes=5), 'recente'), (timedelta(hours=1), 'parado'),
                              (timedelta(days=2), 'abandonado')):
            job = AIJob.objects.create(
                tenant=tenant, user_id=membro.user_id, membership=membro,
                kind=AIJobKind.ENCOUNTER_SUMMARY, source_version=0, purpose='roteiro do despachante',
                idempotency_key=f'roteiro-despachante:{sufixo}:{uuid.uuid4().hex[:8]}',
                status=AIJobStatus.QUEUED,
            )
            AIJob.objects.filter(id=job.id).update(updated_at=timezone.now() - idade)
            jobs.append(job)
        ai_tasks.retomar_jobs_parados()
        recente, parado, abandonado = (AIJob.objects.get(id=j.id) for j in jobs)
        confere(str(recente.id) not in publicados,
                'o de cinco minutos nao e mexido -- a mensagem original pode estar na fila')
        confere(str(parado.id) in publicados, 'o de uma hora volta para a fila')
        confere(parado.status == AIJobStatus.QUEUED, 'e continua na fila, nao falha')
        confere(abandonado.status == AIJobStatus.FAILED, 'o de dois dias vira falha', abandonado.status)
        confere('Peça de novo' in abandonado.status_detail,
                'com a explicacao que o medico le', abandonado.status_detail)
        confere(str(abandonado.id) not in publicados, 'e nao roda sozinho dias depois')
        publicados.clear()
        ai_tasks.retomar_jobs_parados()
        confere(str(parado.id) not in publicados,
                'a rodada seguinte nao republica o que acabou de republicar')
    finally:
        ai_tasks.run_ai_job.delay = original_delay
        ids = [j.id for j in jobs]
        Notification.objects.filter(target_type='ai_job', target_id__in=ids).delete()
        AIJob.objects.filter(id__in=ids).delete()

finally:
    ProcessedEvent.objects.filter(event_id__in=criados).delete()
    OutboxEvent.objects.filter(id__in=criados).delete()
    for prefixo in list(dispatcher._HANDLERS):
        if PREFIXO in prefixo:
            dispatcher._HANDLERS.pop(prefixo)

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - quem perde a posse para, o consumidor ve o proprio commit, e a falha tem nome.')
