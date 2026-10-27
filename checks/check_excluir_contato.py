"""Excluir um contato da ficha do paciente.

Pedido de 2026-10-27: a lista de Contatos tinha "Editar" e nao tinha
"Excluir". O que se tenta quebrar:

1. o contato **sem historico** sai do banco, e a trilha guarda o id e o
   desfecho -- nunca o nome nem o telefone;
2. o contato **com historico** (uma entrega apontando para ele) nao pode
   sair do banco -- a entrega e `PROTECT`, e e o comprovante de para quem
   uma mensagem foi. Ele e **encerrado**: some da ficha, perde as
   autorizacoes, o link de documento aberto e revogado, e **nenhum caminho
   de envio o enxerga mais** (documento e confirmacao);
3. o encerrado nao volta pela URL antiga de edicao, nem e excluido duas
   vezes;
4. so `POST`; outra clinica e outro paciente dao 404;
5. a tela tem o botao, com a pergunta do modal do sistema;
6. as telas que mostram o primeiro contato (balcao, retornos, gaveta) usam
   o mesmo filtro.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from base.templatetags.nd import nd_confirmation_contacts, nd_contatos_vigentes
from communications.models import Delivery, DeliveryStatus
from communications.services import _eligible_document_contacts, confirmation_contacts
from patients.models import Patient, PatientContact, RegistrationStage
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:62} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo(t, papel):
    return Membership.objects.filter(
        tenant=t, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').order_by('user__email').first()


secretaria = vinculo(tenant, 'secretary')
medico = vinculo(tenant, 'doctor')
de_fora = vinculo(tenant_b, 'secretary') or vinculo(tenant_b, 'owner')


def cliente(m):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(m.tenant_id)
    s.save()
    return c


paciente = Patient.objects.create(
    tenant=tenant, full_name='PACIENTE EXCLUIR CONTATO',
    registration_stage=RegistrationStage.COMPLETE,
    birth_date_unknown_reason='Roteiro de verificacao.',
)
outro_paciente = Patient.objects.create(
    tenant=tenant, full_name='OUTRO PACIENTE EXCLUIR CONTATO',
    registration_stage=RegistrationStage.COMPLETE,
    birth_date_unknown_reason='Roteiro de verificacao.',
)


def contato(nome, **extra):
    agora = timezone.now()
    campos = dict(
        tenant=tenant, patient=paciente, name=nome, relationship='Filha',
        phone='11987654321', email='contato.roteiro@exemplo.invalid',
        sms_enabled=True, email_enabled=True, authorized_for_documents=True,
        verified_phone_at=agora, verified_email_at=agora,
    )
    campos.update(extra)
    return PatientContact.objects.create(**campos)


url_excluir = lambda c, p=None: reverse('patients:delete-contact', args=[(p or paciente).id, c.id])
url_editar = lambda c: reverse('patients:edit-contact', args=[paciente.id, c.id])
ficha = reverse('patients:detail', args=[paciente.id])
consulta = entrega = None

try:
    sec = cliente(secretaria)

    print('=== 1. sem historico: sai do banco ===')
    simples = contato('CONTATO SEM HISTORICO')
    html = sec.get(ficha).content.decode()
    conferir('a ficha mostra o botao Excluir', url_excluir(simples) in html, True)
    conferir('  dentro de um formulario com a pergunta do modal',
             'data-nd-confirm="Excluir o contato CONTATO SEM HISTORICO?' in html, True)
    conferir('GET na rota de excluir nao apaga',
             sec.get(url_excluir(simples)).status_code in (405, 404), True)
    conferir('  e o contato continua', PatientContact.objects.filter(id=simples.id).exists(), True)
    r = sec.post(url_excluir(simples))
    conferir('POST redireciona para a ficha', (r.status_code, r.get('Location')), (302, ficha))
    conferir('o contato sem historico saiu do banco',
             PatientContact.objects.filter(id=simples.id).exists(), False)
    ev = AuditEvent.objects.filter(
        tenant_id=tenant.id, action='patients.contact_removed', object_id=paciente.id,
    ).order_by('-created_at').first()
    conferir('a trilha registra a exclusao', ev is not None, True)
    if ev is not None:
        meta = str(ev.integrity_metadata)
        conferir('  com o desfecho "apagado"', (ev.integrity_metadata or {}).get('desfecho'), 'apagado')
        conferir('  e sem nome nem telefone', 'CONTATO SEM HISTORICO' in meta or '11987654321' in meta, False)

    print('=== 2. com historico: encerrado, e ninguem mais envia para ele ===')
    comhist = contato('CONTATO COM HISTORICO')
    inicio = timezone.now() + timedelta(days=500)
    consulta = Appointment.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        starts_at=inicio, ends_at=inicio + timedelta(minutes=40),
        occupied_range=(inicio, inicio + timedelta(minutes=40)),
        status=AppointmentStatus.CANCELLED, type=AppointmentType.FOLLOW_UP,
    )
    entrega = Delivery.objects.create(
        tenant=tenant, appointment=consulta, contact=comhist, channel='sms',
        event_version=1, status=DeliveryStatus.FAILED,
        idempotency_key=f'roteiro-excluir-contato:{comhist.id}',
    )
    conferir('antes: elegivel para documento', comhist in _eligible_document_contacts(paciente), True)
    r = sec.post(url_excluir(comhist))
    conferir('POST redireciona', r.status_code, 302)
    comhist_db = PatientContact.objects.filter(id=comhist.id).first()
    conferir('o contato com historico continua no banco', comhist_db is not None, True)
    conferir('a entrega continua apontando para ele',
             Delivery.objects.filter(id=entrega.id, contact_id=comhist.id).exists(), True)
    if comhist_db is not None:
        conferir('  validade vencida', comhist_db.valid_until is not None
                 and comhist_db.valid_until <= timezone.now(), True)
        conferir('  sem autorizacoes',
                 (comhist_db.sms_enabled, comhist_db.email_enabled,
                  comhist_db.authorized_for_documents, comhist_db.legal_authority),
                 (False, False, False, False))
    paciente_fresco = Patient.objects.get(id=paciente.id)
    conferir('nao e mais elegivel para documento',
             any(c.id == comhist.id for c in _eligible_document_contacts(paciente_fresco)), False)
    for canal in ('sms', 'email'):
        conferir(f'nem para a confirmacao de horario ({canal})',
                 any(getattr(c, 'id', None) == comhist.id for c in confirmation_contacts(
                     Appointment.objects.get(id=consulta.id), canal)), False)
    conferir('a ficha nao lista mais o contato',
             'CONTATO COM HISTORICO' in sec.get(ficha).content.decode(), False)
    ev = AuditEvent.objects.filter(
        tenant_id=tenant.id, action='patients.contact_removed', object_id=paciente.id,
    ).order_by('-created_at').first()
    conferir('a trilha diz "encerrado"', (ev.integrity_metadata or {}).get('desfecho') if ev else None,
             'encerrado')

    print('=== 3. o encerrado nao volta ===')
    conferir('a edicao pela URL antiga da 404', sec.get(url_editar(comhist)).status_code, 404)
    conferir('  nem por POST', sec.post(url_editar(comhist), {'name': 'VOLTOU'}).status_code, 404)
    conferir('excluir de novo da 404', sec.post(url_excluir(comhist)).status_code, 404)

    print('=== 4. fronteiras ===')
    alheio = contato('CONTATO DE FRONTEIRA')
    if de_fora is not None:
        conferir('outra clinica nao exclui',
                 cliente(de_fora).post(url_excluir(alheio)).status_code, 404)
    conferir('pela rota de outro paciente nao exclui',
             sec.post(url_excluir(alheio, outro_paciente)).status_code, 404)
    conferir('  e o contato continua inteiro',
             PatientContact.objects.filter(id=alheio.id, valid_until__isnull=True).exists(), True)

    print('=== 5. o filtro das outras telas ===')
    lista = list(Patient.objects.get(id=paciente.id).contacts.all())
    vigentes = nd_contatos_vigentes(lista)
    conferir('o filtro tira o encerrado', any(c.id == comhist.id for c in vigentes), False)
    conferir('  e mantem o vigente', any(c.id == alheio.id for c in vigentes), True)
    # O telefone mostrado na agenda nao pode ser o do contato excluido.
    PatientContact.objects.filter(id=alheio.id).delete()
    conferir('a agenda nao oferece o telefone do excluido',
             nd_confirmation_contacts(Patient.objects.get(id=paciente.id))['phone'], '')
finally:
    if entrega is not None:
        Delivery.objects.filter(id=entrega.id).delete()
    if consulta is not None:
        Appointment.objects.filter(id=consulta.id).delete()
    PatientContact.objects.filter(patient__in=[paciente, outro_paciente]).delete()
    Patient.objects.filter(id__in=[paciente.id, outro_paciente.id]).delete()

print()
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: excluir contato apaga o que nao tem historico e encerra o que tem.')
