"""O botao "Incluir horario" ao lado do dia, nas tres visoes da agenda.

Pedido de 2026-10-13: a secretaria (ou quem pode configurar a agenda)
abre um horario extra num dia sem sair da agenda. Grava o mesmo
`ScheduleBlock` de atendimento extra que Configurar horarios ja gravava;
o que este roteiro tenta quebrar e o que a porta nova acrescenta:

1. o fim vem da **celula do dia** x quantidade, e as celulas aparecem
   livres na grade -- um extra que nao vira celula e letra morta;
2. recusa, dizendo por que: horario que ja e de atendimento, horario
   sob bloqueio de data, passado e o que atravessa a meia-noite;
3. a permissao e a de configurar **aquela** agenda, conferida no
   servidor, e outra clinica recebe 404;
4. as tres telas desenham o botao e o modal, e o `agenda.js` o abre.
"""
from datetime import time, timedelta
from pathlib import Path

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.utils import timezone

from audit.models import AuditEvent
from scheduling import services
from scheduling.availability import (
    _combine, available_slots, day_grid, slot_minutes_for, suggested_slot_minutes,
)
from scheduling.models import ScheduleBlock, ScheduleBlockKind
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

# Longe no futuro e de madrugada, onde nenhuma grade da demonstracao chega.
dia = timezone.localdate() + timedelta(days=402)
passo = slot_minutes_for(medico.id, dia) or suggested_slot_minutes(medico.id)
antes = set(ScheduleBlock.objects.filter(physician_membership__tenant=tenant).values_list('id', flat=True))


def recusa(*args):
    try:
        services.include_extra_hours(ctx, medico, *args)
        return ''
    except services.SchedulingError as exc:
        return str(exc) or '(sem texto)'


try:
    print('=== 1. incluir vira celula livre, com o fim calculado ===')
    bloco = services.include_extra_hours(ctx, medico, dia, time(1, 0), 2, reason='')
    inicio = _combine(dia, time(1, 0))
    confere(bloco.kind == ScheduleBlockKind.EXTRA_AVAILABILITY, 'grava atendimento extra')
    confere(bloco.start_at == inicio and bloco.end_at == inicio + timedelta(minutes=2 * passo),
            'o fim e a celula do dia vezes a quantidade', f'{bloco.start_at} {bloco.end_at}')
    celulas = [c for c in day_grid(medico.id, dia) if inicio <= c['start'] < bloco.end_at]
    confere(len(celulas) == 2 and all(c['status'] == 'free' for c in celulas),
            'as duas celulas aparecem livres na grade', str([(c['start'], c['status']) for c in celulas]))
    confere(any(s == inicio for s, _ in available_slots(medico.id, dia, minutes=2 * passo)),
            'uma consulta de duas celulas cabe ali')
    confere(AuditEvent.objects.filter(action='scheduling.block_created', object_id=medico.id).exists(),
            'o ato ficou na trilha')

    print('=== 2. o que vira grade torta ou letra morta e recusado ===')
    r = recusa(dia, time(1, 0), 1)
    confere('já é horário de atendimento' in r, 'sobre horario que ja e de atendimento', r)
    meio = (inicio + timedelta(minutes=passo // 2)).time() if passo >= 2 else time(1, 1)
    r = recusa(dia, meio, 1)
    confere('já é horário de atendimento' in r, 'encavalado no meio de um horario existente', r)
    r = recusa(timezone.localdate() - timedelta(days=1), time(23, 0), 1)
    confere('passou' in r, 'no passado', r)
    r = recusa(dia, time(23, 50), 3)
    confere('mesmo dia' in r, 'atravessando a meia-noite', r)
    r = recusa(dia, time(1, 0), 0)
    confere(bool(r), 'quantidade zero')
    ferias = ScheduleBlock.objects.create(
        tenant=tenant, physician_membership=medico, kind=ScheduleBlockKind.VACATION,
        start_at=_combine(dia, time(4, 0)), end_at=_combine(dia, time(5, 0)), reason='Congresso',
    )
    r = recusa(dia, time(4, 0), 1)
    confere('Congresso' in r, 'sob bloqueio de data, dizendo qual', r)

    print('=== 3. a permissao e a de configurar aquela agenda ===')
    url = f'/app/scheduling/{medico.id}/incluir-horario/'
    dados = {'date': dia.isoformat(), 'start_time': '02:30', 'cells': '1',
             'return_to': '/app/scheduling/mes/'}
    r = cliente(secretaria).post(url, dados)
    confere(r.status_code == 302 and ScheduleBlock.objects.filter(
        physician_membership=medico, start_at=_combine(dia, time(2, 30))).exists(),
        'a secretaria inclui pelo POST', str(r.status_code))
    confere('/app/scheduling/mes/' in r.get('Location', ''), 'e volta para a visao de onde veio')

    r = cliente(de_fora).post(url, dict(dados, start_time='03:00'))
    confere(r.status_code == 404 and not ScheduleBlock.objects.filter(
        physician_membership=medico, start_at=_combine(dia, time(3, 0))).exists(),
        'a clinica B recebe 404 e nada e gravado', str(r.status_code))

    so_medico = [m for m in medicos if set(m.roles or []) == {Role.DOCTOR}]
    if len(medicos) > 1 and so_medico:
        outro = next(m for m in medicos if m.id != so_medico[0].id)
        r = cliente(so_medico[0]).post(
            f'/app/scheduling/{outro.id}/incluir-horario/', dict(dados, start_time='03:00'),
        )
        confere(r.status_code == 404, 'medico nao abre horario na agenda do colega', str(r.status_code))
    else:
        print('  --    demonstracao sem dois medicos so-medico; fronteira entre colegas nao exercitada')

    print('=== 4. as tres telas tem o botao, e o modal abre ===')
    raiz = Path(dj_settings.BASE_DIR)
    for nome in ('agenda.html', 'agenda_day.html', 'agenda_month.html'):
        fonte = (raiz / 'templates' / 'scheduling' / nome).read_text(encoding='utf-8')
        confere('data-nd-extra' in fonte and 'pode_incluir_horario' in fonte,
                f'{nome}: o botao, so para quem pode')
    js = (raiz / 'static' / 'scheduling' / 'agenda.js').read_text(encoding='utf-8')
    confere("closest('[data-nd-extra]')" in js and 'extra-modal' in js, 'o agenda.js abre o modal')
    c = cliente(secretaria)
    for rota in ('/app/scheduling/', '/app/scheduling/dia/', '/app/scheduling/mes/'):
        r = c.get(f'{rota}?physician={medico.id}&date={dia.isoformat()}')
        corpo = r.content.decode()
        confere(r.status_code == 200 and 'id="extra-modal"' in corpo,
                f'{rota}: o modal de incluir horario esta na pagina', str(r.status_code))
    r = c.get(f'/app/scheduling/dia/?physician={medico.id}&date={dia.isoformat()}')
    confere('data-nd-extra-day="' + dia.isoformat() + '"' in r.content.decode(),
            'a visao do dia leva o botao com a data do dia')
finally:
    ScheduleBlock.objects.filter(physician_membership__tenant=tenant).exclude(id__in=antes).delete()

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: incluir horario abre celula livre, recusa o que nao abriria nada, e so para quem pode.')
