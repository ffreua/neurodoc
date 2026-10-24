"""Trocar o tipo de um horario marcado, a partir do modal da agenda.

A secretaria marca "primeira consulta", o paciente liga dizendo que ja
veio antes, e o unico caminho era cancelar e marcar de novo. Agora o tipo
se troca no proprio modal -- com duas travas que este roteiro tenta furar:

1. **so antes do check-in**: o tipo escolhe o preco na tabela de
   honorarios, e a cobranca nasce no check-in. Depois dele, trocar o tipo
   deixaria a cobranca dizendo uma coisa e o agendamento outra;
2. **a duracao acompanha o tipo, o inicio nao muda** (desde 2026-10-13;
   antes o horario ficava intacto, e a primeira consulta das 17h trocada
   para retorno continuava ocupando ate 18h20). Encolher libera as celulas
   do fim; esticar so se o tempo seguinte estiver livre, e a recusa nao
   muda nada; encaixe nao passa pela grade; o intervalo pos-consulta da
   reserva e preservado.

E as de sempre: a rota nao pode ser engolida pela rota generica de acao
(`<id>/<action>/`, que daria 404), outra clinica nao alcanca, e o ato
fica na trilha.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db.models import Q
from django.test import Client
from django.urls import resolve
from django.utils import timezone

from audit.models import AuditEvent
from patients.models import Patient, RegistrationStage
from scheduling import services
from scheduling.availability import _combine, day_grid
from scheduling.models import (
    Appointment, AppointmentStatus, AppointmentType, AppointmentTypeDuration, AvailabilityRule,
)
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
    ).select_related('user').order_by('created_at').first()


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


def _dia_sem_grade(dia):
    """Se o medico nao tem regra de horario valendo naquele dia.

    A secao 9 cria uma regra de celulas de 40 min so para o dia seguinte a
    `base` e mede a grade por elas. Num dia em que a demonstracao ja tem a
    grade semanal do medico (09h-17h, celulas de 30 min), e essa a celula
    que a grade usa, a de 40 min nao existe, e o roteiro reprovava -- so
    nos dias da semana em que `base + 1` caia num dia de atendimento. Foi
    assim que ele passou num sabado (2026-10-22) e falhou numa segunda
    (2026-10-24), sem mudanca nenhuma na agenda.
    """
    return not AvailabilityRule.objects.filter(
        physician_membership=medico, weekday=dia.weekday(), starts_on__lte=dia,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=dia)).exists()


for _ in range(7):
    if _dia_sem_grade((base + timedelta(days=1)).date()):
        break
    base += timedelta(days=1)
else:
    raise SystemExit('o medico da demonstracao atende os sete dias da semana; '
                     'a secao 9 precisa de um dia sem grade')


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

# Duracoes fixadas pelo roteiro (e devolvidas no fim): 80 e 40, como no
# consultorio. Sem isto o roteiro dependeria do que a demonstracao tiver.
duracoes_antes = {
    d.appointment_type: d.minutes
    for d in AppointmentTypeDuration.objects.filter(physician_membership=medico)
}
for tipo, minutos in ((AppointmentType.FIRST_VISIT, 80), (AppointmentType.FOLLOW_UP, 80),
                      (AppointmentType.RETURN_VISIT, 40), (AppointmentType.PROCEDURE, 40)):
    AppointmentTypeDuration.objects.update_or_create(
        tenant=tenant, physician_membership=medico, appointment_type=tipo,
        defaults={'minutes': minutos},
    )
regra = None

try:
    print('=== 1. agendado: troca o tipo, e a duracao acompanha ===')
    a = marcar(AppointmentStatus.SCHEDULED, 0)
    inicio, fim, versao = a.starts_at, a.ends_at, a.row_version
    services.change_appointment_type(ctx, a, AppointmentType.RETURN_VISIT, secretaria.user_id)
    a.refresh_from_db()
    confere(a.type == AppointmentType.RETURN_VISIT, 'o tipo mudou')
    confere(a.starts_at == inicio, 'o inicio nao mudou')
    confere(a.ends_at == inicio + timedelta(minutes=40),
            'o fim encolheu para a duracao do retorno', str(a.ends_at))
    confere(a.occupied_range.upper == a.ends_at, 'a faixa ocupada no banco encolheu junto')
    confere(a.row_version == versao + 1, 'a versao da linha avancou')
    trilha = AuditEvent.objects.filter(
        action='scheduling.appointment_type_changed', object_id=a.id).first()
    confere(trilha is not None, 'o ato ficou na trilha')
    if trilha is not None:
        meta = trilha.integrity_metadata or {}
        confere(meta.get('previous_type') == 'first_visit' and meta.get('new_type') == 'return_visit',
                'a trilha diz de que tipo para que tipo', str(meta))
        from datetime import datetime as _dt

        confere(_dt.fromisoformat(meta.get('old_ends_at', '1970-01-01T00:00:00+00:00')) == fim,
                'a trilha guarda o fim anterior', str(meta))

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
        confere(f'<option value="{valor}">{rotulo} — ' in corpo, f'opcao {rotulo}, com os minutos')
    confere('O horário continua o mesmo' not in corpo,
            'o modal nao promete mais que o horario continua o mesmo')

    print('=== 9. a grade: encolher libera, esticar so onde cabe ===')
    dia = (base + timedelta(days=1)).date()
    t0 = _combine(dia, base.time())
    regra = AvailabilityRule.objects.create(
        tenant=tenant, physician_membership=medico, weekday=dia.weekday(),
        local_start=base.time(), local_end=(base + timedelta(hours=4)).time(),
        starts_on=dia, ends_on=dia, slot_minutes=40,
    )

    def no_dia(minutos, duracao, tipo, folga=0, **extra):
        inicio = t0 + timedelta(minutes=minutos)
        fim = inicio + timedelta(minutes=duracao)
        x = Appointment.objects.create(
            tenant=tenant, patient=paciente, physician_membership=medico,
            starts_at=inicio, ends_at=fim,
            occupied_range=(inicio, fim + timedelta(minutes=folga)),
            status=AppointmentStatus.SCHEDULED, type=tipo, **extra,
        )
        criados.append(x.id)
        return x

    def celula(hora):
        return next((cel for cel in day_grid(medico.id, dia) if cel['start'] == hora), {})

    p1 = no_dia(0, 80, AppointmentType.FIRST_VISIT)
    confere(celula(t0 + timedelta(minutes=40)).get('status') == 'busy',
            'antes: a primeira consulta ocupa a segunda celula')
    services.change_appointment_type(ctx, p1, AppointmentType.RETURN_VISIT, secretaria.user_id)
    confere(celula(t0 + timedelta(minutes=40)).get('status') == 'free',
            'trocada para retorno, a segunda celula volta a ficar livre '
            '(o caso das 17h que continuava ate 18h20)')

    services.change_appointment_type(ctx, p1, AppointmentType.FIRST_VISIT, secretaria.user_id)
    p1.refresh_from_db()
    confere(p1.ends_at == t0 + timedelta(minutes=80) and p1.type == AppointmentType.FIRST_VISIT,
            'esticar de volta funciona quando o tempo seguinte esta livre')

    services.change_appointment_type(ctx, p1, AppointmentType.RETURN_VISIT, secretaria.user_id)
    no_dia(40, 40, AppointmentType.RETURN_VISIT)
    try:
        services.change_appointment_type(ctx, p1, AppointmentType.FIRST_VISIT, secretaria.user_id)
        recusa = ''
    except services.SchedulingError as exc:
        recusa = str(exc)
    p1.refresh_from_db()
    confere(bool(recusa), 'esticar sobre outro paciente e recusado')
    confere('remarque' in recusa, 'a recusa diz o caminho (remarcar)', recusa)
    confere(p1.type == AppointmentType.RETURN_VISIT and p1.ends_at == t0 + timedelta(minutes=40),
            'a recusa nao muda nada: nem tipo nem fim')

    ultimo = no_dia(200, 40, AppointmentType.RETURN_VISIT)  # ultima celula da janela de 4h
    try:
        services.change_appointment_type(ctx, ultimo, AppointmentType.FIRST_VISIT, secretaria.user_id)
        recusa = ''
    except services.SchedulingError as exc:
        recusa = str(exc)
    confere('termina' in recusa, 'esticar alem do fim do expediente e recusado, dizendo onde termina',
            recusa)

    encaixe = no_dia(40, 40, AppointmentType.RETURN_VISIT, is_overbook=True,
                     override_reason='roteiro')
    services.change_appointment_type(ctx, encaixe, AppointmentType.FIRST_VISIT, secretaria.user_id)
    encaixe.refresh_from_db()
    confere(encaixe.ends_at == encaixe.starts_at + timedelta(minutes=80),
            'encaixe estica sem passar pela grade, como foi marcado')

    folgado = no_dia(80, 80, AppointmentType.FIRST_VISIT, folga=10)
    services.change_appointment_type(ctx, folgado, AppointmentType.RETURN_VISIT, secretaria.user_id)
    folgado.refresh_from_db()
    confere(folgado.occupied_range.upper == folgado.ends_at + timedelta(minutes=10),
            'o intervalo pos-consulta da reserva e preservado', str(folgado.occupied_range))

    print('=== 10. a tela diz o horario novo ===')
    # O encaixe de 40 a 120 min ocupa a celula de 80: tira-lo do caminho,
    # senao esticar o `folgado` e (corretamente) recusado.
    Appointment.objects.filter(id=encaixe.id).update(status=AppointmentStatus.CANCELLED)
    r = c.post(f'/app/scheduling/{folgado.id}/tipo/', {'appointment_type': 'first_visit'},
               follow=True)
    import html as _html

    pagina = _html.unescape(r.content.decode())
    fim_local = timezone.localtime(folgado.starts_at + timedelta(minutes=80)).strftime('%H:%M')
    confere('Tipo alterado para Primeira consulta' in pagina and f'às {fim_local}' in pagina,
            'a mensagem diz o novo tipo e o novo horario', f'{r.status_code} fim={fim_local}')
finally:
    Appointment.objects.filter(id__in=criados).delete()
    Patient.objects.filter(id=paciente.id).delete()
    if regra is not None:
        regra.delete()
    AppointmentTypeDuration.objects.filter(physician_membership=medico).exclude(
        appointment_type__in=list(duracoes_antes),
    ).delete()
    for tipo, minutos in duracoes_antes.items():
        AppointmentTypeDuration.objects.filter(
            physician_membership=medico, appointment_type=tipo,
        ).update(minutes=minutos)

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o tipo se troca antes da chegada, e a duracao acompanha onde couber.')
