"""Um envio por endereco, e nao por contato.

Relatado em 2026-10-15, testando o servidor SMTP da clinica: o aviso de
cancelamento chegou duas vezes na mesma caixa. O evento e um so, e a
entrega e idempotente -- mas **por contato**: o paciente com dois
contatos de mesmo e-mail (o dele e o da mae que usa a caixa dele, ou o
contato digitado de novo) recebia uma mensagem por contato. O que este
roteiro tenta quebrar:

1. o aviso de cancelamento sai **uma** vez para o endereco repetido,
   mesmo com caixa e espaco diferentes, e fica no contato do proprio
   paciente; o contato com outro e-mail continua recebendo o seu;
2. o lembrete, por e-mail e por SMS, segue a mesma regra (telefone
   comparado pelos digitos);
3. a confirmacao manual lista cada endereco uma vez;
4. repetir a entrega do mesmo evento continua nao reenviando.
"""
from datetime import timedelta

from django.utils import timezone

from communications.models import Delivery, DeliveryAttempt, DeliveryChannel
from communications.services import (
    confirmation_contacts, deliver_appointment_notice, deliver_appointment_reminder,
)
from events.models import OutboxEvent
from patients.contacts import SELF_RELATIONSHIP
from patients.models import Patient, PatientContact, RegistrationStage
from scheduling import services as agenda
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.models import Membership, MembershipStatus, Role, Tenant

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
).order_by('created_at').first()

agora = timezone.now()
paciente = Patient.objects.create(
    tenant=tenant, full_name='PACIENTE UM ENVIO POR ENDERECO',
    registration_stage=RegistrationStage.COMPLETE,
    birth_date_unknown_reason='Roteiro de verificacao.',
)


def contato(nome, relacao, email, phone):
    return PatientContact.objects.create(
        tenant=tenant, patient=paciente, name=nome, relationship=relacao,
        email=email, phone=phone, email_enabled=True, sms_enabled=True,
        verified_email_at=agora, verified_phone_at=agora,
    )


# A mae primeiro, de proposito: quem fica com a entrega tem de ser o
# proprio paciente, e nao quem foi cadastrado antes.
mae = contato('MAE', 'Mãe', ' Teste.Endereco@Exemplo.com ', '(11) 98888-7777')
proprio = contato(paciente.full_name, SELF_RELATIONSHIP, 'teste.endereco@exemplo.com', '11988887777')
outro = contato('IRMAO', 'Irmão', 'outro.endereco@exemplo.com', '11977776666')

inicio = timezone.localtime(agora).replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=404)
consulta = Appointment.objects.create(
    tenant=tenant, patient=paciente, physician_membership=medico,
    starts_at=inicio, ends_at=inicio + timedelta(minutes=40),
    occupied_range=(inicio, inicio + timedelta(minutes=40)),
    status=AppointmentStatus.SCHEDULED, type=AppointmentType.RETURN_VISIT,
)


def entregas(prefixo):
    return list(Delivery.objects.filter(
        appointment=consulta, idempotency_key__startswith=prefixo,
    ).select_related('contact'))


try:
    print('=== 3. a confirmacao manual lista cada endereco uma vez ===')
    lista = confirmation_contacts(consulta, DeliveryChannel.EMAIL)
    confere(len(lista) == 2 and lista[0].id == proprio.id,
            'dois enderecos, o do proprio paciente primeiro', str([c.name for c in lista]))
    lista = confirmation_contacts(consulta, DeliveryChannel.SMS)
    confere(len(lista) == 2, 'telefone com e sem mascara conta como um so', str(len(lista)))

    print('=== 2. o lembrete, por e-mail e por SMS ===')
    deliver_appointment_reminder(consulta, consulta.row_version)
    lembretes = entregas('reminder:')
    por_canal = {
        canal: sorted(d.contact.name for d in lembretes if d.channel == canal)
        for canal in (DeliveryChannel.EMAIL, DeliveryChannel.SMS)
    }
    confere(len(por_canal[DeliveryChannel.EMAIL]) == 2, 'um e-mail por endereco',
            str(por_canal[DeliveryChannel.EMAIL]))
    confere(len(por_canal[DeliveryChannel.SMS]) == 2, 'um SMS por numero', str(por_canal[DeliveryChannel.SMS]))
    confere(not any(d.contact_id == mae.id for d in lembretes), 'nenhum no contato repetido da mae')

    print('=== 1. o aviso de cancelamento ===')
    consulta = agenda.cancel_appointment(consulta, medico.user_id, reason='Roteiro')
    deliver_appointment_notice(consulta, 'cancelled', consulta.row_version)
    avisos = entregas('notice:cancelled:')
    confere(len(avisos) == 2, 'dois avisos: um por endereco, e nao tres', str(len(avisos)))
    confere({d.contact_id for d in avisos} == {proprio.id, outro.id},
            'o do endereco repetido fica no contato do proprio paciente')

    print('=== 4. repetir o evento nao reenvia ===')
    deliver_appointment_notice(consulta, 'cancelled', consulta.row_version)
    confere(len(entregas('notice:cancelled:')) == 2, 'a mesma entrega, sem copia nova')
finally:
    DeliveryAttempt.objects.filter(delivery__contact__patient=paciente).delete()
    Delivery.objects.filter(contact__patient=paciente).delete()
    OutboxEvent.objects.filter(aggregate_id=consulta.id).delete()
    Appointment.objects.filter(patient=paciente).delete()
    PatientContact.objects.filter(patient=paciente).delete()
    Patient.objects.filter(id=paciente.id).delete()

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o mesmo endereco recebe a mesma mensagem uma vez so.')
