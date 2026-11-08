"""A agenda de amanhã por e-mail a cada médico (1.36) tenta ser quebrada.

O que este roteiro cobra, e onde da errado:

- **o que entra**: os horarios vivos do medico **amanha**, em ordem, com
  horario, paciente, tipo e confirmacao ("A confirmar" ou "Confirmado") e o
  encaixe marcado; cancelado, falta, o de hoje e o de depois de amanha nao;
- **amanha e o de Brasilia**: a rodada das 23h30 (ja dia seguinte em UTC)
  manda a agenda do dia seguinte de Brasilia, e nao a de dois dias depois;
- **quem recebe**: medico ativo com a opcao ligada, em clinica nao
  encerrada (a suspensa recebe); a secretaria, o vinculo revogado, quem
  desligou e o dia sem horario nao;
- **por onde sai**: `send_email` com a **clinica** e sem o vinculo do
  medico -- servidor da clinica, senao o da instalacao;
- **uma vez por dia**: a segunda rodada nao envia, e a falha no envio fica
  registrada sem virar repeticao;
- **a tela de desligar**: so o proprio medico, pelo vinculo da rota, com a
  trilha; o vinculo de outra pessoa e o da secretaria sao 404.

Tudo dentro de uma transacao desfeita no fim: nada fica no banco, e o envio
e interceptado (dentro da transacao o e-mail de verdade nunca sairia, porque
`send_email` so enfileira depois do commit).
"""
import uuid
from datetime import datetime, time, timedelta
from unittest import mock

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import Client
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from patients.models import Patient
from scheduling import agenda_por_email
from scheduling.models import AgendaPorEmailEnvio, Appointment, AppointmentStatus, AppointmentType
from tenancy.models import Membership, MembershipStatus, Role, Tenant, TenantStatus

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  {'ok  ' if ok else 'FALHA'} {rotulo:<72} -> {obtido!r}")
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado!r}, obtido {obtido!r}')


class Desfazer(Exception):
    pass


clinica = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=clinica.id).filter(status=TenantStatus.ACTIVE).order_by('created_at').first()
pacientes = list(Patient.objects.filter(tenant=clinica).order_by('created_at')[:3])
if len(pacientes) < 3 or outra is None:
    print('  (demonstracao incompleta; roteiro pulado)')
    raise SystemExit(0)

fuso = timezone.get_current_timezone()
hoje = timezone.localdate()
amanha = hoje + timedelta(days=1)


def as_horas(dia, hora, minuto=0):
    return timezone.make_aware(datetime.combine(dia, time(hora, minuto)), fuso)


def vinculo(tenant, nome, papeis, **extra):
    conta = User.objects.create_user(email=f'{nome}-{uuid.uuid4().hex[:6]}@agenda-email.invalid', password=None)
    conta.first_name = nome.capitalize()
    conta.last_name = 'Roteiro'
    conta.save(update_fields=['first_name', 'last_name'])
    return Membership.objects.create(tenant=tenant, user=conta, roles=papeis,
                                     status=extra.pop('status', MembershipStatus.ACTIVE),
                                     activated_at=timezone.now(), **extra)


def consulta(medico, paciente, inicio, minutos=30, **extra):
    fim = inicio + timedelta(minutes=minutos)
    return Appointment.objects.create(
        tenant=medico.tenant, patient=paciente, physician_membership=medico,
        starts_at=inicio, ends_at=fim, occupied_range=DateTimeTZRange(inicio, fim, '[)'),
        **{'status': AppointmentStatus.SCHEDULED, 'type': AppointmentType.FOLLOW_UP, **extra},
    )


enviados = []


def capturar(to_email, subject, body_text, physician_membership=None, tenant_id=None, html_body=None, **_):
    enviados.append({'para': to_email, 'assunto': subject, 'texto': body_text, 'html': html_body or '',
                     'tenant_id': tenant_id, 'medico': physician_membership})


try:
    with transaction.atomic():
        ana = vinculo(clinica, 'ana', [Role.DOCTOR])
        vazio = vinculo(clinica, 'bruno', [Role.DOCTOR])
        desligado = vinculo(clinica, 'carla', [Role.DOCTOR], agenda_por_email=False)
        revogado = vinculo(clinica, 'davi', [Role.DOCTOR], status=MembershipStatus.REVOKED)
        secretaria = vinculo(clinica, 'eva', [Role.SECRETARY])
        de_outra = vinculo(outra, 'fabio', [Role.DOCTOR])
        p1, p2, p3 = pacientes

        consulta(ana, p2, as_horas(amanha, 10), status=AppointmentStatus.CONFIRMED, type=AppointmentType.FIRST_VISIT)
        consulta(ana, p1, as_horas(amanha, 8))
        consulta(ana, p3, as_horas(amanha, 8, 30), is_overbook=True, override_reason='roteiro',
                 type=AppointmentType.RETURN_VISIT)
        consulta(ana, p3, as_horas(amanha, 11), status=AppointmentStatus.CANCELLED)
        consulta(ana, p1, as_horas(amanha, 12), status=AppointmentStatus.NO_SHOW)
        consulta(ana, p1, as_horas(hoje, 23, 0))
        consulta(ana, p2, as_horas(amanha + timedelta(days=1), 9))
        for m in (desligado, revogado):
            consulta(m, p1, as_horas(amanha, 14))
        consulta(de_outra, Patient.objects.filter(tenant=outra).first() or p1, as_horas(amanha, 15)) \
            if Patient.objects.filter(tenant=outra).exists() else None

        print('\n1. O que entra na agenda')
        horarios = agenda_por_email.horarios_do_dia(ana, amanha)
        conferir('tres horarios: cancelado, falta, hoje e depois de amanha de fora', len(horarios), 3)
        conferir('em ordem de horario',
                 [timezone.localtime(a.starts_at).strftime('%H:%M') for a in horarios], ['08:00', '08:30', '10:00'])
        conferir('a confirmacao em portugues',
                 [agenda_por_email.situacao(a) for a in horarios], ['A confirmar', 'A confirmar', 'Confirmado'])

        print('\n2. Quem recebe')
        ids = set(agenda_por_email.destinatarios().values_list('id', flat=True))
        conferir('o medico ativo recebe', ana.id in ids, True)
        conferir('quem desligou nao', desligado.id in ids, False)
        conferir('o vinculo revogado nao', revogado.id in ids, False)
        conferir('a secretaria nao', secretaria.id in ids, False)
        Tenant.objects.filter(id=outra.id).update(status=TenantStatus.SUSPENDED)
        conferir('a clinica suspensa recebe (congela a escrita, nao a agenda)',
                 de_outra.id in set(agenda_por_email.destinatarios().values_list('id', flat=True)), True)
        Tenant.objects.filter(id=outra.id).update(status=TenantStatus.CLOSED)
        conferir('a encerrada nao',
                 de_outra.id in set(agenda_por_email.destinatarios().values_list('id', flat=True)), False)

        print('\n3. A rodada e o e-mail')
        with mock.patch('communications.email.send_email', side_effect=capturar):
            agora = as_horas(hoje, 19)
            resultado = agenda_por_email.rodada(agora)
        da_ana = [e for e in enviados if e['para'] == ana.user.email]
        conferir('a Ana recebe um e-mail', len(da_ana), 1)
        conferir('quem nao tem horario amanha nao recebe',
                 any(e['para'] == vazio.user.email for e in enviados), False)
        conferir('quem desligou e o revogado nao recebem',
                 any(e['para'] in (desligado.user.email, revogado.user.email) for e in enviados), False)
        email = da_ana[0] if da_ana else {'assunto': '', 'texto': '', 'html': '', 'tenant_id': None, 'medico': 1}
        conferir('sai pela clinica, sem o remetente pessoal do medico',
                 (email['tenant_id'], email['medico']), (clinica.id, None))
        nome = clinica.trade_name or clinica.legal_name
        conferir('o assunto tem o dia e a clinica', email['assunto'], f'Sua agenda de {amanha:%d/%m} — {nome}')
        texto = email['texto']
        conferir('o texto lista os tres pacientes, nessa ordem',
                 [texto.find(p.full_name) >= 0 for p in (p1, p3, p2)], [True, True, True])
        conferir('com horario, tipo e confirmacao',
                 all(t in texto for t in ('08:00–08:30', 'Seguimento', 'Retorno', 'Primeira consulta',
                                          'A confirmar', 'Confirmado')), True)
        conferir('o encaixe marcado', 'encaixe' in texto, True)
        conferir('o resumo: 3 horarios, 1 confirmado', '3 horários, 1 confirmado' in texto, True)
        conferir('o dia por extenso, em portugues', any(d in texto.lower() for d in (
            'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo')), True)
        conferir('a hora em que a lista foi tirada', 'às 19:00' in texto, True)
        conferir('o link da agenda daquele dia', f'?date={amanha.isoformat()}' in texto, True)
        conferir('o link de desligar leva o vinculo', f'/agenda-por-email/{ana.id}/' in texto, True)
        conferir('o cancelado nao aparece', texto.count(p3.full_name), 1)
        conferir('o HTML traz a tabela com os mesmos pacientes',
                 ('<table' in email['html'], all(p.full_name in email['html'] for p in (p1, p2, p3))), (True, True))
        # 2026-11-08: com quatro colunas o Gmail do celular cortava a da
        # confirmação. Duas colunas por linha, e a confirmação no HTML.
        import re as _re
        linha_html = _re.search(r'<tr[^>]*>(.*?)</tr>', email['html'], _re.S)
        conferir('o HTML cabe no celular: duas colunas por linha, sem cabecalho de quatro',
                 (linha_html.group(1).count('<td') if linha_html else 0, '<th' in email['html']), (2, False))
        conferir('o HTML diz quem confirmou', ('Confirmado' in email['html'], 'A confirmar' in email['html']),
                 (True, True))
        conferir('o envio fica registrado, com o numero de horarios e sem os nomes',
                 list(AgendaPorEmailEnvio.objects.filter(membership=ana, dia=amanha)
                      .values_list('horarios', flat=True)), [3])

        print('\n4. Uma vez por dia')
        antes = len(enviados)
        with mock.patch('communications.email.send_email', side_effect=capturar):
            segunda = agenda_por_email.rodada(agora)
        conferir('a segunda rodada nao manda nada de novo', len(enviados), antes)
        conferir('e conta como repetido', segunda['repetido'] >= 1, True)

        print('\n5. O dia e o de Brasilia')
        tarde_da_noite = as_horas(hoje, 23, 30)
        conferir('as 23h30 (ja amanha em UTC) a agenda e a de amanha de Brasilia',
                 agenda_por_email.amanha(tarde_da_noite), amanha)

        print('\n6. A falha no envio')
        bruno_horario = consulta(vazio, p1, as_horas(amanha, 16))
        with mock.patch('communications.email.send_email', side_effect=OSError('smtp fora')):
            conferir('a falha vira "falhou", sem excecao', agenda_por_email.enviar(vazio, amanha, agora), 'falhou')
        registro = AgendaPorEmailEnvio.objects.get(membership=vazio, dia=amanha)
        conferir('fica registrada com o erro e sem data de envio', (registro.erro, registro.enviado_em),
                 ('OSError', None))
        with mock.patch('communications.email.send_email', side_effect=capturar):
            conferir('e nao se repete na rodada seguinte', agenda_por_email.enviar(vazio, amanha, agora), 'repetido')

        print('\n7. A tela de desligar')
        def entrar(m):
            m.user.email_verified_at = timezone.now()
            m.user.save(update_fields=['email_verified_at'])
            c = Client()
            c.force_login(m.user)
            s = c.session
            s['tenant_id'] = str(m.tenant_id)
            s.save()
            return c

        c_ana = entrar(ana)
        url = f'/app/scheduling/agenda-por-email/{ana.id}/'
        pagina = c_ana.get(url)
        conferir('o medico abre a propria', (pagina.status_code, 'Não quero mais receber' in pagina.content.decode()),
                 (200, True))
        r = c_ana.post(url, {'ligar': '0'})
        ana.refresh_from_db()
        conferir('desliga com um clique', (r.status_code, ana.agenda_por_email), (302, False))
        conferir('na trilha', AuditEvent.objects.filter(
            action='scheduling.agenda_por_email_desligada', object_id=str(ana.id)).count(), 1)
        conferir('desligado, sai da lista de quem recebe',
                 ana.id in set(agenda_por_email.destinatarios().values_list('id', flat=True)), False)
        c_ana.post(url, {'ligar': '1'})
        ana.refresh_from_db()
        conferir('e religa', ana.agenda_por_email, True)
        conferir('o vinculo de outra pessoa e 404',
                 c_ana.get(f'/app/scheduling/agenda-por-email/{vazio.id}/').status_code, 404)
        conferir('e o POST nele tambem, sem mudar nada',
                 (c_ana.post(f'/app/scheduling/agenda-por-email/{vazio.id}/', {'ligar': '0'}).status_code,
                  Membership.objects.get(id=vazio.id).agenda_por_email), (404, True))
        c_sec = entrar(secretaria)
        conferir('a secretaria nao tem a tela',
                 c_sec.get(f'/app/scheduling/agenda-por-email/{secretaria.id}/').status_code, 404)

        print('\n8. O agendamento')
        agenda = dj_settings.CELERY_BEAT_SCHEDULE['scheduling-enviar-agenda-de-amanha']
        conferir('a tarefa diaria na hora do settings',
                 (agenda['task'], str(agenda['schedule']._orig_hour), str(agenda['schedule']._orig_minute)),
                 ('scheduling.tasks.enviar_agenda_de_amanha', str(dj_settings.AGENDA_POR_EMAIL_HORA), '0'))
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print('FALHAS (%d):' % len(falhas))
    for falha in falhas:
        print('  -', falha)
    raise SystemExit(1)
print('OK: o que entra, quem recebe, por onde sai, uma vez por dia, o dia de Brasilia, '
      'a falha registrada e a tela de desligar.')
