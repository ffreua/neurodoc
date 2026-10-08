"""Trocar o tipo de um horario marcado, a partir do modal da agenda.

A secretaria marca "primeira consulta", o paciente liga dizendo que ja
veio antes, e o unico caminho era cancelar e marcar de novo. Agora o tipo
se troca no proprio modal -- com duas travas que este roteiro tenta furar:

1. **so antes do check-in**: o tipo escolhe o preco na tabela de
   honorarios, e a cobranca nasce no check-in. Depois dele, trocar o tipo
   deixaria a cobranca dizendo uma coisa e o agendamento outra;
2. **o horario nao muda**: trocar o tipo nao estica nem encolhe a consulta
   -- esticar podia invadir o horario seguinte, ja ocupado.

E as de sempre: a rota nao pode ser engolida pela rota generica de acao
(`<id>/<action>/`, que daria 404), outra clinica nao alcanca, e o ato
fica na trilha.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import resolve
from django.utils import timezone

from audit.models import AuditEvent
from patients.models import Patient, RegistrationStage
from scheduling import services
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo(t, papel):
    return Membership.objects.filter(
        tenant=t, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').first()


medico = vinculo(tenant, 'doctor')
secretaria = vinculo(tenant, 'secretary')
de_fora = vinculo(tenant_b, 'owner') or vinculo(tenant_b, 'secretary')


def cliente(m):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(m.tenant_id)
    s.save()
    return c


criados = []
paciente = Patient.objects.create(
    tenant=tenant, full_name='PACIENTE TIPO DE CONSULTA',
    registration_stage=RegistrationStage.COMPLETE,
    birth_date_unknown_reason='Roteiro de verificacao.',
)
# Longe no futuro e de madrugada: nao colide com nada da demonstracao.
base = timezone.localtime().replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=400)


def marcar(status, deslocamento_h, tipo=AppointmentType.FIRST_VISIT):
    inicio = base + timedelta(hours=deslocamento_h)
    fim = inicio + timedelta(minutes=80)
    a = Appointment.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        starts_at=inicio, ends_at=fim, occupied_range=(inicio, fim),
        status=status, type=tipo,
    )
    criados.append(a.id)
    return a


ctx = AccessContext(
    user_id=secretaria.user_id, tenant_id=tenant.id, membership_id=secretaria.id,
    permissions=frozenset(secretaria.roles or []), request_id=None,
    tenant_status=tenant.status, capabilities=frozenset(),
)

try:
    print('=== 1. agendado: troca o tipo, e so o tipo ===')
    a = marcar(AppointmentStatus.SCHEDULED, 0)
    inicio, fim, versao = a.starts_at, a.ends_at, a.row_version
    services.change_appointment_type(ctx, a, AppointmentType.RETURN_VISIT, secretaria.user_id)
    a.refresh_from_db()
    confere(a.type == AppointmentType.RETURN_VISIT, 'o tipo mudou')
    confere((a.starts_at, a.ends_at) == (inicio, fim),
            'o horario nao mudou (retorno dura menos, e a consulta nao encolheu)')
    confere(a.row_version == versao + 1, 'a versao da linha avancou')
    trilha = AuditEvent.objects.filter(
        action='scheduling.appointment_type_changed', object_id=a.id).first()
    confere(trilha is not None, 'o ato ficou na trilha')
    if trilha is not None:
        meta = trilha.integrity_metadata or {}
        confere(meta.get('previous_type') == 'first_visit' and meta.get('new_type') == 'return_visit',
                'a trilha diz de que tipo para que tipo', str(meta))

    print('=== 2. o mesmo tipo nao e um ato ===')
    antes = AuditEvent.objects.filter(action='scheduling.appointment_type_changed',
                                      object_id=a.id).count()
    services.change_appointment_type(ctx, a, AppointmentType.RETURN_VISIT, secretaria.user_id)
    depois = AuditEvent.objects.filter(action='scheduling.appointment_type_changed',
                                       object_id=a.id).count()
    confere(antes == depois, 'nenhuma linha nova na trilha')

    print('=== 3. confirmado tambem pode ===')
    b = marcar(AppointmentStatus.CONFIRMED, 2)
    services.change_appointment_type(ctx, b, AppointmentType.FOLLOW_UP, secretaria.user_id)
    b.refresh_from_db()
    confere(b.type == AppointmentType.FOLLOW_UP, 'confirmado aceita a troca')

    print('=== 4. depois da chegada, o tipo ja definiu a cobranca ===')
    for i, status in enumerate([AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_PROGRESS,
                                AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW,
                                AppointmentStatus.CANCELLED]):
        x = marcar(status, 4 + 2 * i)
        try:
            services.change_appointment_type(ctx, x, AppointmentType.RETURN_VISIT, secretaria.user_id)
            recusou = False
        except services.SchedulingError:
            recusou = True
        x.refresh_from_db()
        confere(recusou and x.type == AppointmentType.FIRST_VISIT, f'{status}: recusado')

    print('=== 5. tipo inventado e recusado ===')
    try:
        services.change_appointment_type(ctx, b, 'consulta_vip', secretaria.user_id)
        confere(False, 'tipo inexistente recusado')
    except services.SchedulingError:
        confere(True, 'tipo inexistente recusado')

    print('=== 6. pela tela: a rota e a propria, e a secretaria alcanca ===')
    rota = resolve(f'/app/scheduling/{a.id}/tipo/')
    confere(rota.func.view_class.__name__ == 'ChangeAppointmentTypeView',
            'a rota nao e engolida pela acao generica', rota.func.view_class.__name__)
    c = cliente(secretaria)
    r = c.post(f'/app/scheduling/{a.id}/tipo/', {'appointment_type': 'procedure'})
    a.refresh_from_db()
    confere(r.status_code == 302 and a.type == AppointmentType.PROCEDURE,
            'a secretaria troca o tipo pelo POST', f'{r.status_code} {a.type}')

    chegou = Appointment.objects.get(id=criados[2])
    r = c.post(f'/app/scheduling/{chegou.id}/tipo/', {'appointment_type': 'procedure'})
    chegou.refresh_from_db()
    confere(chegou.type == AppointmentType.FIRST_VISIT, 'POST direto depois da chegada nao troca')

    print('=== 7. outra clinica nao alcanca ===')
    if de_fora is None:
        confere(False, 'a demonstracao tem alguem na clinica B')
    else:
        r = cliente(de_fora).post(f'/app/scheduling/{b.id}/tipo/', {'appointment_type': 'other'})
        b.refresh_from_db()
        confere(r.status_code == 404 and b.type == AppointmentType.FOLLOW_UP,
                'a clinica B recebe 404 e nada muda', f'{r.status_code} {b.type}')

    print('=== 8. o modal tem o seletor, e cada horario diz o proprio tipo ===')
    r = c.get(f'/app/scheduling/?physician={medico.id}&date={base.date().isoformat()}')
    corpo = r.content.decode()
    confere('id="slot-type-form"' in corpo, 'o formulario de troca esta no modal')
    confere('Alterar o tipo de consulta' in corpo, 'o botao esta no modal')
    # O horario do roteiro fica de madrugada, fora da grade que a tela
    # desenha; por isso a celula e conferida no template, e nas tres visoes
    # -- semana, dia e mes -- que incluem o modal.
    from pathlib import Path

    raiz = Path(dj_settings.BASE_DIR)
    for nome in ('agenda.html', 'agenda_day.html', 'agenda_month.html'):
        fonte = (raiz / 'templates' / 'scheduling' / nome).read_text(encoding='utf-8')
        confere('data-nd-type-code="{{ cell.appointment.type }}"' in fonte,
                f'{nome}: a celula leva o codigo do tipo')
    js = (raiz / 'static' / 'scheduling' / 'agenda.js').read_text(encoding='utf-8')
    confere("getAttribute('data-nd-type-code')" in js,
            'o modal abre o seletor no tipo atual')
    for valor, rotulo in AppointmentType.choices:
        confere(f'<option value="{valor}">{rotulo}</option>' in corpo, f'opcao {rotulo}')
finally:
    Appointment.objects.filter(id__in=criados).delete()
    Patient.objects.filter(id=paciente.id).delete()

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o tipo se troca antes da chegada, e so o tipo.')
