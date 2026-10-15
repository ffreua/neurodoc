"""Excluir um horario livre, no modal que abre ao clicar nele.

Pedido de 2026-10-15: o avesso de "Incluir horario". Quem clica num
horario livre ja via "paciente cadastrado" e "pre-cadastro"; agora ve
tambem "Excluir este horario". O que este roteiro tenta quebrar:

1. a celula do horario semanal vira **horario excluido** do tamanho da
   celula, **some** da grade e nao aceita mais reserva; e Incluir horario
   no mesmo lugar a **reabre** em vez de recusar;
2. a celula que **e** um atendimento extra inteiro tem o extra apagado
   (incluir e excluir e desfazer); a do meio de um extra maior some sem
   levar as vizinhas;
2b. o caso relatado na 1.14 (2026-10-15): incluir dois horarios, excluir
   os dois -- o mes nao pode dizer "fechado" -- e incluir de novo no
   mesmo lugar, que antes era recusado como "ja e horario de atendimento";
3. so fecha o que esta livre: ocupado, ja bloqueado, passado e horario
   que nunca existiu sao recusados, sem gravar nada;
4. a permissao e a de configurar **aquela** agenda, e outra clinica
   recebe 404;
5. o botao esta no modal de marcar das tres visoes, so para quem pode, e
   o agenda.js preenche o horario.
"""
from datetime import time, timedelta
from pathlib import Path

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.utils import timezone

from audit.models import AuditEvent
from patients.models import Patient, RegistrationStage
from scheduling import services
from scheduling.availability import _combine, available_slots, day_grid, month_summary
from scheduling.models import (
    Appointment, AppointmentStatus, AppointmentType, ScheduleBlock, ScheduleBlockKind,
)
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculos(t, papel):
    return list(Membership.objects.filter(
        tenant=t, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').order_by('created_at'))


medicos = vinculos(tenant, Role.DOCTOR)
medico = medicos[0]
secretaria = vinculos(tenant, Role.SECRETARY)[0]
de_fora = (vinculos(tenant_b, Role.OWNER) or vinculos(tenant_b, Role.SECRETARY))[0]


def cliente(m):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(m.tenant_id)
    s.save()
    return c


ctx = AccessContext(
    user_id=secretaria.user_id, tenant_id=tenant.id, membership_id=secretaria.id,
    permissions=frozenset(secretaria.roles or []), request_id=None,
    tenant_status=tenant.status, capabilities=frozenset(),
)


def celula(dia, inicio):
    return next((c for c in day_grid(medico.id, dia) if c['start'] == inicio), None)


def recusa(inicio):
    try:
        services.remove_free_slot(ctx, medico, inicio)
        return ''
    except services.SchedulingError as exc:
        return str(exc) or '(sem texto)'


# Longe no futuro e de madrugada, onde nenhuma grade da demonstracao chega.
dia = timezone.localdate() + timedelta(days=403)
antes = set(ScheduleBlock.objects.filter(physician_membership__tenant=tenant).values_list('id', flat=True))
criados = []
paciente = None

try:
    print('=== 1. horario da grade semanal vira bloqueio da celula ===')
    semanal = None
    for n in range(1, 60):
        d = timezone.localdate() + timedelta(days=n)
        livres = [c for c in day_grid(medico.id, d) if c['status'] == 'free']
        # Celula da regra, e nao de um extra que a demonstracao tenha gravado.
        livres = [c for c in livres if not ScheduleBlock.objects.filter(
            physician_membership=medico, kind=ScheduleBlockKind.EXTRA_AVAILABILITY,
            start_at__lte=c['start'], end_at__gte=c['end'],
        ).exists()]
        if livres:
            semanal = (d, livres[0])
            break
    if semanal is None:
        print('  --    demonstracao sem horario semanal livre nos proximos 60 dias; caso nao exercitado')
    else:
        d, c = semanal
        bloco = services.remove_free_slot(ctx, medico, c['start'])
        confere(bloco is not None and bloco.kind == ScheduleBlockKind.REMOVED_SLOT
                and bloco.start_at == c['start'] and bloco.end_at == c['end'],
                'grava horario excluido exatamente do tamanho da celula')
        confere(celula(d, c['start']) is None, 'a celula some da grade (nada de "fechado")')
        confere(all(s != c['start'] for s, _ in available_slots(medico.id, d, minutes=1)),
                'e some da lista de horarios livres')
        confere(AuditEvent.objects.filter(action='scheduling.block_created', object_id=medico.id).exists(),
                'o ato ficou na trilha')
        hora = timezone.localtime(c['start']).time()
        r = services.include_extra_hours(ctx, medico, d, hora, 1)
        volta = celula(d, c['start'])
        confere(r is None and volta is not None and volta['status'] == 'free'
                and not ScheduleBlock.objects.filter(id=bloco.id).exists(),
                'incluir no mesmo lugar reabre, sem extra por cima', str(volta and volta['status']))
        confere(AuditEvent.objects.filter(action='scheduling.slot_reopened', object_id=medico.id).exists(),
                'a reabertura ficou na trilha')
        try:
            services.include_extra_hours(ctx, medico, d, hora, 1)
            r = ''
        except services.SchedulingError as exc:
            r = str(exc)
        confere('já é horário de atendimento' in r,
                'incluir sobre horario semanal que nao foi excluido continua recusado', r)

    print('=== 2. atendimento extra: desfazer o inteiro, bloquear o do meio ===')
    um = services.include_extra_hours(ctx, medico, dia, time(1, 0), 1)
    r = services.remove_free_slot(ctx, medico, um.start_at)
    confere(r is None and not ScheduleBlock.objects.filter(id=um.id).exists(),
            'o extra de uma celula e apagado, sem bloqueio por cima')
    confere(celula(dia, um.start_at) is None, 'e a celula some da grade')
    confere(AuditEvent.objects.filter(action='scheduling.block_deleted', object_id=medico.id).exists(),
            'o apagamento ficou na trilha')

    tres = services.include_extra_hours(ctx, medico, dia, time(2, 0), 3)
    passo = (tres.end_at - tres.start_at) / 3
    meio = tres.start_at + passo
    r = services.remove_free_slot(ctx, medico, meio)
    confere(r is not None and r.kind == ScheduleBlockKind.REMOVED_SLOT
            and ScheduleBlock.objects.filter(id=tres.id).exists() and celula(dia, meio) is None,
            'a do meio de um extra maior some e o extra fica')
    vizinhas = [celula(dia, tres.start_at), celula(dia, meio + passo)]
    confere(all(v is not None and v['status'] == 'free' for v in vizinhas),
            'as vizinhas continuam livres', str([v and v['status'] for v in vizinhas]))

    print('=== 2b. incluir dois, excluir os dois, incluir de novo ===')
    dia2 = dia + timedelta(days=1)
    dois = services.include_extra_hours(ctx, medico, dia2, time(1, 0), 2)
    meia = (dois.end_at - dois.start_at) / 2
    for inicio in (dois.start_at, dois.start_at + meia):
        services.remove_free_slot(ctx, medico, inicio)
    resumo = month_summary(medico.id, [dia2])[dia2]
    confere(resumo['blocked'] == 0 and not any(
        c['start'] in (dois.start_at, dois.start_at + meia) for c in resumo['cells']),
        'o mes nao desenha os excluidos nem diz "fechado"', str(resumo['blocked']))
    try:
        r = services.include_extra_hours(ctx, medico, dia2, time(1, 0), 2)
        recusado = ''
    except services.SchedulingError as exc:
        recusado = str(exc)
    confere(not recusado, 'incluir de novo no mesmo lugar e aceito', recusado)
    livres = [celula(dia2, dois.start_at), celula(dia2, dois.start_at + meia)]
    confere(all(c is not None and c['status'] == 'free' for c in livres),
            'e os dois horarios voltam livres', str([c and c['status'] for c in livres]))
    confere(not ScheduleBlock.objects.filter(
        physician_membership=medico, kind=ScheduleBlockKind.REMOVED_SLOT,
        start_at__gte=dois.start_at, end_at__lte=dois.end_at).exists(),
        'sem horario excluido sobrando por baixo')
    services.remove_free_slot(ctx, medico, dois.start_at + meia)
    r = services.include_extra_hours(ctx, medico, dia2, timezone.localtime(dois.start_at + meia).time(), 2)
    confere(r is not None and r.start_at == dois.end_at and r.end_at == dois.end_at + meia,
            'incluir passando do excluido reabre um e cria extra so para o resto',
            r and f'{r.start_at} {r.end_at}')

    print('=== 3. so fecha o que esta livre ===')
    n = ScheduleBlock.objects.filter(physician_membership=medico).count()
    r = recusa(meio)
    confere('não está mais livre' in r, 'o que ja foi excluido', r)
    paciente = Patient.objects.create(
        tenant=tenant, full_name='PACIENTE EXCLUIR HORARIO',
        registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    ocupada = tres.start_at
    a = Appointment.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        starts_at=ocupada, ends_at=ocupada + passo, occupied_range=(ocupada, ocupada + passo),
        status=AppointmentStatus.SCHEDULED, type=AppointmentType.RETURN_VISIT,
    )
    criados.append(a.id)
    r = recusa(ocupada)
    confere('não está mais livre' in r, 'o que tem paciente marcado', r)
    r = recusa(_combine(dia, time(5, 17)))
    confere('não está mais livre' in r, 'horario que nunca existiu', r)
    ontem = timezone.localdate() - timedelta(days=1)
    passada = next(iter(day_grid(medico.id, ontem)), None)
    if passada is not None:
        r = recusa(passada['start'])
        confere('não está mais livre' in r, 'horario que ja passou', r)
    confere(ScheduleBlock.objects.filter(physician_membership=medico).count() == n,
            'nenhuma recusa gravou nada')

    print('=== 4. a permissao e a de configurar aquela agenda ===')
    livre = tres.start_at + 2 * passo
    url = f'/app/scheduling/{medico.id}/excluir-horario/'
    dados = {'starts_at': timezone.localtime(livre).isoformat(), 'date': dia.isoformat(),
             'return_to': '/app/scheduling/dia/'}
    r = cliente(de_fora).post(url, dados)
    confere(r.status_code == 404 and celula(dia, livre)['status'] == 'free',
            'a clinica B recebe 404 e nada muda', str(r.status_code))
    so_medico = [m for m in medicos if set(m.roles or []) == {Role.DOCTOR}]
    if len(medicos) > 1 and so_medico:
        outro = next(m for m in medicos if m.id != so_medico[0].id)
        r = cliente(so_medico[0]).post(f'/app/scheduling/{outro.id}/excluir-horario/', dados)
        confere(r.status_code == 404, 'medico nao exclui horario na agenda do colega', str(r.status_code))
    else:
        print('  --    demonstracao sem dois medicos so-medico; fronteira entre colegas nao exercitada')
    r = cliente(secretaria).post(url, dados)
    confere(r.status_code == 302 and celula(dia, livre) is None,
            'a secretaria exclui pelo POST', str(r.status_code))
    confere('/app/scheduling/dia/' in r.get('Location', ''), 'e volta para a visao de onde veio')
    r = cliente(secretaria).post(url, {'starts_at': 'lixo', 'date': dia.isoformat()})
    confere(r.status_code == 302, 'horario ilegivel volta com aviso, sem erro 500', str(r.status_code))

    print('=== 5. o botao esta no modal de marcar, so para quem pode ===')
    raiz = Path(dj_settings.BASE_DIR)
    modal = (raiz / 'templates' / 'scheduling' / '_booking_modals.html').read_text(encoding='utf-8')
    confere('form="slot-remove-form"' in modal and 'data-nd-confirm' in modal,
            'o botao pertence ao formulario de excluir e pede confirmacao')
    js = (raiz / 'static' / 'scheduling' / 'agenda.js').read_text(encoding='utf-8')
    confere('slot-remove-starts-at' in js, 'o agenda.js preenche o horario clicado')
    c = cliente(secretaria)
    for rota in ('/app/scheduling/', '/app/scheduling/dia/', '/app/scheduling/mes/'):
        r = c.get(f'{rota}?physician={medico.id}&date={dia.isoformat()}')
        corpo = r.content.decode()
        confere(r.status_code == 200 and 'id="slot-remove-form"' in corpo
                and 'Excluir este horário' in corpo,
                f'{rota}: o botao de excluir esta no modal', str(r.status_code))
    if so_medico and len(medicos) > 1:
        outro = next(m for m in medicos if m.id != so_medico[0].id)
        r = cliente(so_medico[0]).get(f'/app/scheduling/?physician={outro.id}&date={dia.isoformat()}')
        confere(r.status_code != 200 or 'id="slot-remove-form"' not in r.content.decode(),
                'na agenda do colega o medico nao ve o botao')
finally:
    Appointment.objects.filter(id__in=criados).delete()
    if paciente is not None:
        Patient.objects.filter(id=paciente.id).delete()
    ScheduleBlock.objects.filter(physician_membership__tenant=tenant).exclude(id__in=antes).delete()

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: excluir horario fecha so o livre, desfaz o extra, e so para quem pode.')
