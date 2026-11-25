"""Teleatendimento: link do vídeo, e-mail ao paciente e termo público (1.58).

Pedido do Dr. Fernando: no horário por vídeo, colar o link da chamada e um
botão "Enviar link" que manda ao paciente o link, as orientações e o aviso do
termo de consentimento — numa página pública, com aceite por participação.

O roteiro tenta quebrar: que o link seja guardado sem a marca de
teleatendimento; que o envio saia sem link ou sem e-mail; que o link vá para a
trilha; que outra clínica alcance o horário; que a página do termo peça login.

Tudo dentro de agendamentos, pacientes e contatos criados e apagados aqui.
"""
from datetime import timedelta

from django.conf import settings as dj

dj.ALLOWED_HOSTS = list(dj.ALLOWED_HOSTS) + ['testserver']
dj.SECURE_SSL_REDIRECT = False
# A caixa em memória, como nos outros roteiros: com EMAIL_ENABLED (o local do
# NeuroDoc) o envio sairia pelo worker até o Mailpit e `mail.outbox` ficaria
# vazia — o roteiro reprovaria por causa do ambiente, não do código.
dj.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from communications import services as comm
from communications.models import Delivery, DeliveryAttempt
from communications.tasks import enviar_link_teleconsulta_task
from patients.contacts import SELF_RELATIONSHIP
from patients.models import Patient, PatientContact, RegistrationStage
from scheduling import services
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'a': [], 'p': []}


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo_de(papel, clinica=tenant):
    return Membership.objects.filter(
        tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').order_by('user__email').first()


medico = vinculo_de('doctor')
secretaria = vinculo_de('secretary')


def ctx_de(v, clinica=tenant):
    return AccessContext(
        user_id=v.user_id, tenant_id=clinica.id, membership_id=v.id,
        permissions=frozenset(v.roles or []), request_id=None,
        tenant_status=clinica.status, capabilities=frozenset(),
    )


def paciente(nome, com_email=True):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome, registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['p'].append(p.id)
    if com_email:
        PatientContact.objects.create(
            tenant=tenant, patient=p, name=nome, relationship=SELF_RELATIONSHIP,
            email='paciente.tele@exemplo.test',
        )
    return p


# Cada horário do roteiro ganha a sua hora: todos são do mesmo médico, e a
# restrição `scheduling_appointment_no_overlap` recusa dois horários
# sobrepostos (com "agora + 3 dias" fixo, o segundo já caía em cima do primeiro).
_proxima_hora = [0]


def marcar(pac, quando=None, status=AppointmentStatus.CONFIRMED, tele=False, link='', minutos=40):
    if quando is None:
        _proxima_hora[0] += 1
        quando = timezone.now() + timedelta(days=40, hours=_proxima_hora[0])
    fim = quando + timedelta(minutes=minutos)
    a = Appointment.objects.create(
        tenant=tenant, patient=pac, physician_membership=medico,
        starts_at=quando, ends_at=fim, occupied_range=(quando, fim), status=status,
        type=AppointmentType.FOLLOW_UP, teleatendimento=tele, teleatendimento_link=link,
    )
    criados['a'].append(a.id)
    return a


def cliente(v, clinica=tenant):
    c = Client()
    c.force_login(v.user)
    s = c.session
    s['tenant_id'] = str(clinica.id)
    s.save()
    return c


LINK = 'https://meet.google.com/abc-defg-hij'
volta = reverse('scheduling:week')
ctxm = ctx_de(medico)


def url_link(a):
    return reverse('scheduling:teleatendimento-link', args=[a.id])


try:
    print('=== 1. a página pública do termo abre, sem login ===')
    r = Client().get('/termo-teleconsulta/')
    conferir('GET /termo-teleconsulta/ responde 200', r.status_code, 200)
    corpo = r.content.decode('utf-8')
    conferir('traz o título do termo', 'Termo de consentimento para teleconsulta' in corpo, True)
    conferir('traz o aceite por participação', 'participar da teleconsulta implica' in corpo, True)
    conferir('traz a cláusula de urgência/emergência', 'urgência ou emergência' in corpo, True)

    print('\n=== 2. o link exige a marca de teleatendimento ===')
    sem = marcar(paciente('ROTEIRO LINK SEM TELE', com_email=False), tele=False)
    try:
        services.set_teleatendimento_link(ctxm, sem, LINK, medico.user_id)
        conferir('link sem a marca é recusado', False, True)
    except services.SchedulingError:
        conferir('link sem a marca é recusado', True, True)
    com = marcar(paciente('ROTEIRO LINK COM TELE'), tele=True)
    services.set_teleatendimento_link(ctxm, com, LINK, medico.user_id)
    com.refresh_from_db()
    conferir('com a marca, o link é guardado', com.teleatendimento_link, LINK)
    services.set_teleatendimento_link(ctxm, com, '', medico.user_id)
    com.refresh_from_db()
    conferir('link em branco limpa o campo', com.teleatendimento_link, '')

    print('\n=== 2b. só endereço web vira link (o serviço não roda full_clean) ===')
    for rotulo, ruim in [
        ('javascript: recusado', 'javascript:alert(1)'),
        ('sem https:// recusado', 'meet.google.com/abc-defg-hij'),
        ('texto qualquer recusado', 'amanhã às 10h pelo Meet'),
        ('ftp recusado', 'ftp://exemplo.test/sala'),
        ('acima de 500 caracteres recusado', 'https://meet.google.com/' + 'a' * 600),
    ]:
        try:
            services.set_teleatendimento_link(ctxm, com, ruim, medico.user_id)
            conferir(rotulo, False, True)
        except services.SchedulingError:
            conferir(rotulo, True, True)
    com.refresh_from_db()
    conferir('  e nada foi gravado', com.teleatendimento_link, '')
    longo = 'https://teams.microsoft.com/l/meetup-join/' + 'b' * 440
    services.set_teleatendimento_link(ctxm, com, longo, medico.user_id)
    com.refresh_from_db()
    conferir('link longo de verdade (482) é aceito', com.teleatendimento_link, longo)
    services.set_teleatendimento_link(ctxm, com, '', medico.user_id)
    r = cliente(medico).post(
        reverse('scheduling:teleatendimento-link', args=[com.id]),
        {'acao': 'enviar', 'link': 'https://x.test/' + 'c' * 700, 'return_to': volta},
    )
    conferir('pela tela, o link enorme vira recusa e não erro 500', r.status_code, 302)
    com.refresh_from_db()
    conferir('  e nada foi gravado nem enviado', com.teleatendimento_link, '')

    print('\n=== 3. o nome da plataforma pelo domínio ===')
    conferir('meet.google.com → Google Meet',
             comm.plataforma_do_link('https://meet.google.com/x'), 'Google Meet')
    conferir('teams.microsoft.com → Microsoft Teams',
             comm.plataforma_do_link('https://teams.microsoft.com/l/x'), 'Microsoft Teams')
    conferir('sub.zoom.us → Zoom',
             comm.plataforma_do_link('https://us02web.zoom.us/j/1'), 'Zoom')
    conferir('domínio desconhecido → vazio',
             comm.plataforma_do_link('https://cockpit.einstein.br/sala/1'), '')

    print('\n=== 4. enviar o link pelo serviço: e-mail ao paciente, com termo ===')
    env = marcar(paciente('ROTEIRO LINK ENVIO'), tele=True, link=LINK)
    mail.outbox = []
    entrega = comm.enviar_link_teleconsulta(ctxm, env, medico.user_id)
    conferir('uma entrega criada', entrega is not None, True)
    conferir('um e-mail na caixa', len(mail.outbox), 1)
    msg = mail.outbox[0] if mail.outbox else None
    if msg:
        conferir('e-mail vai ao endereço do paciente', msg.to, ['paciente.tele@exemplo.test'])
        conferir('o corpo traz o link', LINK in msg.body, True)
        conferir('o corpo traz o endereço do termo', '/termo-teleconsulta/' in msg.body, True)
        conferir('o corpo traz a orientação (bem iluminado)', 'bem iluminado' in msg.body, True)
        conferir('o corpo nomeia a plataforma (Google Meet)', 'Google Meet' in msg.body, True)
    ev = AuditEvent.objects.filter(
        action='communications.teleconsulta_link_sent', object_id=str(env.id),
    ).first()
    conferir('a trilha registra o envio', ev is not None, True)
    conferir('a trilha NÃO guarda o link',
             (ev is not None) and (LINK not in str(ev.integrity_metadata)), True)

    print('\n=== 5. recusas do envio ===')
    try:
        comm.enviar_link_teleconsulta(ctxm, com, medico.user_id)   # tele sim, link vazio
        conferir('sem link é recusado', False, True)
    except comm.SemLinkDeTeleconsulta:
        conferir('sem link é recusado', True, True)
    sem_email = marcar(paciente('ROTEIRO LINK SEM EMAIL', com_email=False), tele=True, link=LINK)
    try:
        comm.enviar_link_teleconsulta(ctxm, sem_email, medico.user_id)
        conferir('sem e-mail é recusado', False, True)
    except comm.NoUsableContact:
        conferir('sem e-mail é recusado', True, True)
    concl = marcar(paciente('ROTEIRO LINK CONCLUIDO'), status=AppointmentStatus.COMPLETED, tele=True)
    try:
        services.set_teleatendimento_link(ctxm, concl, LINK, medico.user_id)
        conferir('horário concluído não aceita link', False, True)
    except services.SchedulingError:
        conferir('horário concluído não aceita link', True, True)

    print('\n=== 6. a view e a task ===')
    sec = cliente(secretaria)
    med = cliente(medico)
    v = marcar(paciente('ROTEIRO LINK VIEW'), tele=True)
    conferir('GET não guarda (405)', med.get(url_link(v)).status_code, 405)
    sec.post(url_link(v), {'acao': 'salvar', 'link': LINK, 'return_to': volta})
    v.refresh_from_db()
    conferir('a secretária salva o link pela view', v.teleatendimento_link, LINK)
    de_fora = vinculo_de('secretary', tenant_b) or vinculo_de('owner', tenant_b)
    fora = cliente(de_fora, tenant_b)
    conferir('outra clínica recebe 404',
             fora.post(url_link(v), {'acao': 'salvar', 'link': LINK}).status_code, 404)
    mail.outbox = []
    enviar_link_teleconsulta_task.apply(args=[str(v.id), medico.user_id, None])
    conferir('a task envia o e-mail', len(mail.outbox), 1)
    v2 = marcar(paciente('ROTEIRO LINK VIEW SEM LINK'), tele=True)
    mail.outbox = []
    resp = sec.post(url_link(v2), {'acao': 'enviar', 'link': '', 'return_to': volta})
    conferir('enviar sem link redireciona (302)', resp.status_code, 302)
    conferir('  e nada é enviado', len(mail.outbox), 0)

    if falhas:
        print('\ncheck_teleconsulta_link: FALHAS')
        for f in falhas:
            print('  -', f)
        raise SystemExit(1)
    print('\ncheck_teleconsulta_link: tudo certo.')
finally:
    # O envio deixa a entrega e a tentativa registradas, e as duas protegem
    # (PROTECT) o que vem antes delas: apaga-se de trás para a frente.
    DeliveryAttempt.objects.filter(delivery__appointment_id__in=criados['a']).delete()
    Delivery.objects.filter(appointment_id__in=criados['a']).delete()
    Appointment.objects.filter(id__in=criados['a']).delete()
    PatientContact.objects.filter(patient_id__in=criados['p']).delete()
    Patient.objects.filter(id__in=criados['p']).delete()
