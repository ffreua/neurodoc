"""Bloquear um horario livre, e a duracao que segue o tipo.

Dois relatos do Dr. Fernando, 2026-10-15, testando a 1.14.2:

A. "Quero, no modal do horario livre, bloquear -- alem de excluir. O
   bloqueado entra na estatistica, o excluido nao." O que se tenta quebrar:

   1. o bloqueio e do tamanho da celula, a celula **continua** na grade como
      bloqueada, e o mes e a estatistica a contam como bloqueada -- e o
      excluido continua sem contar;
   2. a celula bloqueada pelo modal se libera com um clique; o bloqueio de
      Configurar horarios, o que ja passou e o de outro medico nao;
   3. so bloqueia o que esta livre, e nenhuma recusa grava nada;
   4. a permissao e a de configurar aquela agenda; a clinica B recebe 404;
   5. o botao esta no modal das tres visoes, e a celula bloqueada vira o
      botao de liberar nas tres.

B. "O retorno das 17h do dia 22 ocupa ate 18h20, e o horario das 17h40 nao
   aparece." Consulta gravada antes da 1.13 com a duracao de outro tipo:

   6. a migracao 0007 encurta a consulta futura para a duracao do tipo,
      preserva a folga pos-consulta, e libera a celula seguinte;
   7. nao mexe no passado, no encaixe, nem na que ja tem a duracao certa;
   8. a remarcacao grava a duracao do tipo, e nao a que a consulta tinha.
"""
from datetime import time, timedelta
from importlib import import_module
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import Client
from django.utils import timezone

from audit.models import AuditEvent
from patients.models import Patient, RegistrationStage
from scheduling import services
from scheduling.availability import _combine, day_grid, month_summary
from scheduling.estatisticas import _ocupacao
from scheduling.models import (
    MOTIVO_BLOQUEIO_PELA_AGENDA, Appointment, AppointmentStatus, AppointmentType, ScheduleBlock,
    ScheduleBlockKind,
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


def celula(dia, inicio, doc=None):
    return next((c for c in day_grid((doc or medico).id, dia) if c['start'] == inicio), None)


def recusa(inicio):
    try:
        services.block_free_slot(ctx, medico, inicio)
        return ''
    except services.SchedulingError as exc:
        return str(exc) or '(sem texto)'


# Longe no futuro e de madrugada, onde nenhuma grade da demonstracao chega.
dia = timezone.localdate() + timedelta(days=409)
antes = set(ScheduleBlock.objects.filter(physician_membership__tenant=tenant).values_list('id', flat=True))
criados = []
pacientes = []


def paciente_novo(nome):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome, registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    pacientes.append(p.id)
    return p


def consulta(paciente, inicio, fim, tipo, folga=timedelta(0), **extra):
    a = Appointment.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        starts_at=inicio, ends_at=fim, occupied_range=DateTimeTZRange(inicio, fim + folga, '[)'),
        type=tipo, **{'status': AppointmentStatus.SCHEDULED, **extra},
    )
    criados.append(a.id)
    return a


try:
    seis = services.include_extra_hours(ctx, medico, dia, time(1, 0), 6)
    passo = (seis.end_at - seis.start_at) / 6
    inicios = [seis.start_at + passo * n for n in range(6)]

    print('=== 1. bloquear: a celula fica, e conta como bloqueada ===')
    resumo_antes = month_summary(medico.id, [dia])[dia]
    bloco = services.block_free_slot(ctx, medico, inicios[0])
    confere(bloco.kind == ScheduleBlockKind.BLOCK and bloco.reason == MOTIVO_BLOQUEIO_PELA_AGENDA
            and bloco.start_at == inicios[0] and bloco.end_at == inicios[1],
            'grava bloqueio exatamente do tamanho da celula')
    c = celula(dia, inicios[0])
    confere(c is not None and c['status'] == 'blocked' and c['unblock_id'] == bloco.id,
            'a celula continua na grade, bloqueada e liberavel', str(c and c['status']))
    vizinha = celula(dia, inicios[1])
    confere(vizinha is not None and vizinha['status'] == 'free', 'a vizinha continua livre')
    resumo = month_summary(medico.id, [dia])[dia]
    confere(resumo['blocked'] == resumo_antes['blocked'] + 1
            and resumo['free'] == resumo_antes['free'] - 1,
            'o mes conta um bloqueado a mais e um livre a menos')
    confere(resumo['blocked'] < resumo['total'], 'e o dia nao vira "fechado"')
    ocup = _ocupacao(dia, dia, [medico])
    bloqueados = ocup[0]['bloqueados'] if isinstance(ocup, tuple) else ocup['bloqueados']
    confere(bloqueados == resumo['blocked'], 'a estatistica do mes conta o bloqueado',
            f'{bloqueados} != {resumo["blocked"]}')
    services.remove_free_slot(ctx, medico, inicios[1])
    ocup2 = _ocupacao(dia, dia, [medico])
    linha2 = ocup2[0] if isinstance(ocup2, tuple) else ocup2
    confere(linha2['bloqueados'] == bloqueados and linha2['total'] == resumo['total'] - 1,
            'o excluido sai do total e nao entra nos bloqueados')
    confere(AuditEvent.objects.filter(action='scheduling.block_created', object_id=medico.id).exists(),
            'o bloqueio ficou na trilha')

    print('=== 2. liberar com um clique, e so o que o modal bloqueou ===')
    inicio_unblock = services.unblock_slot(ctx, medico, bloco.id)
    c = celula(dia, inicios[0])
    confere(inicio_unblock == inicios[0] and c is not None and c['status'] == 'free'
            and not ScheduleBlock.objects.filter(id=bloco.id).exists(),
            'liberar apaga o bloqueio e a celula volta livre')
    confere(AuditEvent.objects.filter(action='scheduling.block_deleted', object_id=medico.id,
                                      integrity_metadata__origem='desbloquear_horario').exists(),
            'a liberacao ficou na trilha')
    manual = services.create_block(ctx, medico, ScheduleBlockKind.BLOCK, inicios[2], inicios[3],
                                   reason='Cirurgia')
    c = celula(dia, inicios[2])
    confere(c['status'] == 'blocked' and c['unblock_id'] is None,
            'bloqueio de Configurar horarios nao vira botao de liberar')
    try:
        services.unblock_slot(ctx, medico, manual.id)
        r = ''
    except services.SchedulingError as exc:
        r = str(exc)
    confere('Configurar horários' in r and ScheduleBlock.objects.filter(id=manual.id).exists(),
            'e nao se libera por aqui', r)
    if len(medicos) > 1:
        outro_bloco = services.block_free_slot(ctx, medico, inicios[3])
        try:
            services.unblock_slot(ctx, medicos[1], outro_bloco.id)
            r = ''
        except services.SchedulingError as exc:
            r = str(exc)
        confere(r and ScheduleBlock.objects.filter(id=outro_bloco.id).exists(),
                'o bloqueio de um medico nao se libera pela agenda de outro')
        services.unblock_slot(ctx, medico, outro_bloco.id)
    ontem = timezone.now() - timedelta(days=1)
    velho = ScheduleBlock.objects.create(
        tenant=tenant, physician_membership=medico, kind=ScheduleBlockKind.BLOCK,
        reason=MOTIVO_BLOQUEIO_PELA_AGENDA, start_at=ontem, end_at=ontem + passo,
    )
    try:
        services.unblock_slot(ctx, medico, velho.id)
        r = ''
    except services.SchedulingError as exc:
        r = str(exc)
    confere('já passou' in r and ScheduleBlock.objects.filter(id=velho.id).exists(),
            'o que ja passou fica como registro do dia', r)

    print('=== 3. so bloqueia o que esta livre ===')
    n = ScheduleBlock.objects.filter(physician_membership=medico).count()
    ocupado = consulta(paciente_novo('PACIENTE BLOQUEAR HORARIO'), inicios[4], inicios[5],
                       AppointmentType.RETURN_VISIT)
    confere('não está mais livre' in recusa(inicios[4]), 'o que tem paciente marcado')
    confere('não está mais livre' in recusa(inicios[2]), 'o que ja esta bloqueado')
    confere('não está mais livre' in recusa(inicios[1]), 'o que foi excluido')
    confere('não está mais livre' in recusa(_combine(dia, time(5, 17))), 'horario que nunca existiu')
    passada = next(iter(day_grid(medico.id, timezone.localdate() - timedelta(days=1))), None)
    if passada is not None:
        confere('não está mais livre' in recusa(passada['start']), 'horario que ja passou')
    confere(ScheduleBlock.objects.filter(physician_membership=medico).count() == n,
            'nenhuma recusa gravou nada')

    print('=== 4. permissao e fronteira ===')
    alvo = inicios[3]
    url = f'/app/scheduling/{medico.id}/bloquear-horario/'
    dados = {'starts_at': timezone.localtime(alvo).isoformat(), 'date': dia.isoformat(),
             'return_to': '/app/scheduling/mes/'}
    r = cliente(de_fora).post(url, dados)
    confere(r.status_code == 404 and celula(dia, alvo)['status'] == 'free',
            'a clinica B recebe 404 e nada muda', str(r.status_code))
    so_medico = [m for m in medicos if set(m.roles or []) == {Role.DOCTOR}]
    if len(medicos) > 1 and so_medico:
        outro = next(m for m in medicos if m.id != so_medico[0].id)
        r = cliente(so_medico[0]).post(f'/app/scheduling/{outro.id}/bloquear-horario/', dados)
        confere(r.status_code == 404, 'medico nao bloqueia horario na agenda do colega', str(r.status_code))
    r = cliente(secretaria).post(url, dados)
    c = celula(dia, alvo)
    confere(r.status_code == 302 and c['status'] == 'blocked' and c['unblock_id'],
            'a secretaria bloqueia pelo POST', str(r.status_code))
    confere('/app/scheduling/mes/' in r.get('Location', ''), 'e volta para a visao de onde veio')
    r = cliente(secretaria).post(url, {'starts_at': 'lixo', 'date': dia.isoformat()})
    confere(r.status_code == 302, 'horario ilegivel volta com aviso, sem erro 500', str(r.status_code))

    print('=== 5. o botao no modal e a celula liberavel nas tres visoes ===')
    raiz = Path(dj_settings.BASE_DIR)
    modal = (raiz / 'templates' / 'scheduling' / '_booking_modals.html').read_text(encoding='utf-8')
    confere('form="slot-block-form"' in modal and 'id="slot-block-form"' in modal,
            'o botao pertence ao formulario de bloquear')
    js = (raiz / 'static' / 'scheduling' / 'agenda.js').read_text(encoding='utf-8')
    confere('slot-block-starts-at' in js, 'o agenda.js preenche o horario clicado')
    c = cliente(secretaria)
    unblock = f'/app/scheduling/{medico.id}/desbloquear-horario/'
    for rota in ('/app/scheduling/', '/app/scheduling/dia/', '/app/scheduling/mes/'):
        r = c.get(f'{rota}?physician={medico.id}&date={dia.isoformat()}')
        corpo = r.content.decode()
        confere(r.status_code == 200 and 'Bloquear este horário' in corpo and unblock in corpo,
                f'{rota}: bloquear no modal e liberar na celula', str(r.status_code))
    bloco_view = ScheduleBlock.objects.get(physician_membership=medico, start_at=alvo,
                                           reason=MOTIVO_BLOQUEIO_PELA_AGENDA)
    r = cliente(de_fora).post(unblock, {'block_id': str(bloco_view.id), 'date': dia.isoformat()})
    confere(r.status_code == 404 and ScheduleBlock.objects.filter(id=bloco_view.id).exists(),
            'a clinica B nao libera', str(r.status_code))
    r = c.post(unblock, {'block_id': str(bloco_view.id), 'date': dia.isoformat(),
                         'return_to': '/app/scheduling/dia/'})
    confere(r.status_code == 302 and celula(dia, alvo)['status'] == 'free',
            'a secretaria libera pelo POST', str(r.status_code))

    print('=== 6. retorno gravado com 80 min volta aos 40 do tipo ===')
    ret = services.duration_for(medico.id, AppointmentType.RETURN_VISIT)
    dia_b = dia + timedelta(days=1)
    grande = services.include_extra_hours(ctx, medico, dia_b, time(1, 0), 8)
    p_b = (grande.end_at - grande.start_at) / 8
    inicio_ret = grande.start_at
    folga = timedelta(minutes=5)
    longo = consulta(paciente_novo('PACIENTE RETORNO LONGO'), inicio_ret,
                     inicio_ret + timedelta(minutes=ret * 2), AppointmentType.RETURN_VISIT, folga=folga)
    certo = consulta(paciente_novo('PACIENTE RETORNO CERTO'), inicio_ret + timedelta(minutes=ret * 3),
                     inicio_ret + timedelta(minutes=ret * 4), AppointmentType.RETURN_VISIT)
    encaixe = consulta(paciente_novo('PACIENTE ENCAIXE LONGO'), inicio_ret + timedelta(minutes=ret * 4),
                       inicio_ret + timedelta(minutes=ret * 6), AppointmentType.RETURN_VISIT,
                       is_overbook=True, override_reason='Roteiro')
    ontem_1h = _combine(timezone.localdate() - timedelta(days=2), time(1, 0))
    passado = consulta(paciente_novo('PACIENTE PASSADO LONGO'), ontem_1h,
                       ontem_1h + timedelta(minutes=ret * 2), AppointmentType.RETURN_VISIT)
    # As celulas que so o tempo a mais ocupava: depois do fim do tipo (e da
    # folga) e antes do fim gravado. A celula da demonstracao pode nao ter
    # 40 min, por isso a busca e por intervalo, e nao por um inicio exato.
    def sobra():
        return [c for c in day_grid(medico.id, dia_b)
                if c['start'] >= inicio_ret + timedelta(minutes=ret) + folga
                and c['start'] < inicio_ret + timedelta(minutes=ret * 2)]
    confere(sobra() and all(c['status'] == 'busy' for c in sobra()),
            'antes: o tempo a mais ocupa a celula seguinte (o defeito)',
            str([c['status'] for c in sobra()]))
    migracao = import_module('scheduling.migrations.0007_duracao_segue_o_tipo')
    migracao.encurta(django_apps, None)
    longo.refresh_from_db()
    confere(longo.ends_at == inicio_ret + timedelta(minutes=ret),
            'o retorno longo passa a terminar na duracao do tipo', str(longo.ends_at))
    confere(longo.occupied_range.upper == longo.ends_at + folga,
            'a folga pos-consulta e preservada', str(longo.occupied_range))
    confere(sobra() and all(c['status'] == 'free' for c in sobra()),
            'e a celula seguinte volta livre', str([c['status'] for c in sobra()]))

    print('=== 7. o que a migracao nao toca ===')
    for a, rotulo, fim in (
        (certo, 'o que ja tem a duracao certa', certo.ends_at),
        (encaixe, 'o encaixe', encaixe.ends_at),
        (passado, 'o passado', passado.ends_at),
    ):
        a.refresh_from_db()
        confere(a.ends_at == fim, f'{rotulo} fica como esta', str(a.ends_at))

    print('=== 8. a remarcacao grava a duracao do tipo ===')
    longo.ends_at = inicio_ret + timedelta(minutes=ret * 2)
    longo.occupied_range = DateTimeTZRange(longo.starts_at, longo.ends_at, '[)')
    longo.save()
    # Num dia so dele, longe do encaixe e da consulta certa.
    vazio = services.include_extra_hours(ctx, medico, dia_b + timedelta(days=1), time(1, 0), 8)
    destino = vazio.start_at
    if destino + timedelta(minutes=ret) <= vazio.end_at:
        r = cliente(secretaria).post(f'/app/scheduling/{longo.id}/remarcar/', {
            'starts_at': timezone.localtime(destino).strftime('%Y-%m-%dT%H:%M'),
            'row_version': longo.row_version,
        })
        longo.refresh_from_db()
        confere(r.status_code == 302 and longo.starts_at == destino
                and longo.ends_at == destino + timedelta(minutes=ret),
                'remarcar grava a duracao do tipo, e nao a que a consulta tinha',
                f'{r.status_code} {longo.starts_at} {longo.ends_at}')
    else:
        print('  --    extra curto demais para remarcar dentro dele; caso nao exercitado')
finally:
    Appointment.objects.filter(id__in=criados).delete()
    Patient.objects.filter(id__in=pacientes).delete()
    ScheduleBlock.objects.filter(physician_membership__tenant=tenant).exclude(id__in=antes).delete()

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: bloquear conta, excluir nao conta, liberar e de um clique, e a duracao segue o tipo.')
