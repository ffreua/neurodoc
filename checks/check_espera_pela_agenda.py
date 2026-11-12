"""Lista de espera pela agenda, para antecipar quem já tem horário (2026-11-12).

A recepção marca o paciente na data possível e, pelo modal do horário, o
põe na lista de espera para chamá-lo se abrir vaga antes. O que se tenta
quebrar, dentro de uma transação desfeita:

1. **o estado no modal**: `GET` diz se pode incluir, se já está e por qual
   caminho; consulta de hoje, passada, cancelada ou concluída não oferece;
2. **incluir pela agenda**: a espera nasce com o médico, o tipo e a consulta
   do horário, no fim da lista, e o pré-cadastro também entra;
3. **as recusas**: paciente já na lista, consulta de hoje, consulta de outro
   paciente pelo serviço, outra clínica (404), `GET` que não grava;
4. **retirar pela agenda**, com o motivo;
5. **antecipar**: puxado para um horário anterior, a consulta antiga é
   desmarcada na mesma transação, com o motivo e o aviso de cancelamento
   ao paciente; puxado para um horário **depois** dela, a antiga fica;
6. **o dia da consulta**: a tarefa diária tira da lista quem chegou ao dia
   sem antecipação (e só esses: a véspera fica, a espera sem consulta
   fica, a consulta desmarcada por outro caminho deixa a espera de pé), e
   rodar duas vezes não faz nada a mais;
7. **a lista mostra** a consulta a antecipar;
8. **as tabelas de atendimentos** (ficha e prontuário) com Ações na primeira
   coluna, para o botão não ficar atrás da rolagem.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from patients.models import Patient, RegistrationStage
from scheduling import espera
from scheduling.models import (
    Appointment, AppointmentStatus, AppointmentType, EsperaStatus, PacienteEmEspera,
)
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:66} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado!r}, obtido {obtido!r}')


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.get(slug='demo-clinica-b')
medico = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').order_by('id').first()
secretaria = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['secretary'],
).select_related('user').first()
vinculo_b = Membership.objects.filter(tenant=outra, status=MembershipStatus.ACTIVE).select_related('user').first()


def contexto(vinculo):
    return AccessContext(
        user_id=vinculo.user_id, tenant_id=vinculo.tenant_id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles or []), request_id=None,
        tenant_status=vinculo.tenant.status, capabilities=frozenset(),
    )


def cliente_de(vinculo):
    cliente = Client()
    cliente.force_login(vinculo.user)
    sessao = cliente.session
    sessao['tenant_id'] = str(vinculo.tenant_id)
    sessao.save()
    return cliente


hoje = timezone.localdate()


def em(dias, hora=10):
    local = timezone.make_aware(
        timezone.datetime.combine(hoje + timedelta(days=dias), timezone.datetime.min.time())
    ) + timedelta(hours=hora)
    return local


def consulta(pac, dias, hora=10, status=AppointmentStatus.SCHEDULED):
    inicio = em(dias, hora)
    fim = inicio + timedelta(minutes=30)
    return Appointment.objects.create(
        tenant=tenant, patient=pac, physician_membership=medico,
        starts_at=inicio, ends_at=fim, occupied_range=(inicio, fim),
        status=status, type=AppointmentType.FOLLOW_UP,
    )


def paciente(nome, pre=False):
    return Patient.objects.create(
        tenant=tenant, full_name=nome, birth_date_unknown_reason='Roteiro de verificacao.',
        registration_stage=RegistrationStage.PRELIMINARY if pre else RegistrationStage.COMPLETE,
    )


ctx = contexto(secretaria)
c = cliente_de(secretaria)

try:
    with transaction.atomic():
        PacienteEmEspera.objects.filter(tenant=tenant).delete()
        maria = paciente('MARIA ROTEIRO ESPERA AGENDA')
        joao = paciente('JOAO ROTEIRO ESPERA AGENDA', pre=True)
        ana = paciente('ANA ROTEIRO ESPERA AGENDA')
        dez_dias = consulta(maria, 10)
        url = reverse('scheduling:appointment-espera', args=[dez_dias.id])

        print('\n1. O estado no modal')
        r = c.get(url)
        conferir('GET responde', r.status_code, 200)
        conferir('pode incluir, ainda nao esta', (r.json()['pode_incluir'], r.json()['na_lista']), (True, False))
        conferir('GET nao grava nada', PacienteEmEspera.objects.filter(tenant=tenant).count(), 0)
        for rotulo, dias, status in (('consulta de hoje', 0, AppointmentStatus.SCHEDULED),
                                     ('consulta passada', -2, AppointmentStatus.SCHEDULED),
                                     ('consulta cancelada', 5, AppointmentStatus.CANCELLED),
                                     ('consulta concluida', 5, AppointmentStatus.COMPLETED)):
            outra_consulta = consulta(ana, dias, hora=15, status=status)
            r = c.get(reverse('scheduling:appointment-espera', args=[outra_consulta.id]))
            conferir(f'  {rotulo} nao oferece', r.json()['pode_incluir'], False)
            outra_consulta.delete()

        print('\n2. Incluir pela agenda')
        r = c.post(url, {'acao': 'incluir', 'return_to': reverse('scheduling:week')})
        conferir('POST redireciona para a agenda', r.status_code, 302)
        e = PacienteEmEspera.objects.filter(tenant=tenant, patient=maria, status=EsperaStatus.AGUARDANDO).first()
        conferir('a espera nasceu', e is not None, True)
        if e:
            conferir('  com a consulta, o medico e o tipo do horario',
                     (e.consulta_marcada_id, e.physician_membership_id, e.appointment_type),
                     (dez_dias.id, medico.id, AppointmentType.FOLLOW_UP))
            conferir('  no fim da lista', e.posicao, 1)
        r = c.get(url)
        conferir('o modal agora oferece retirar', (r.json()['na_lista'], r.json()['por_esta_consulta']), (True, True))
        pre = consulta(joao, 20)
        c.post(reverse('scheduling:appointment-espera', args=[pre.id]), {'acao': 'incluir'})
        conferir('o pre-cadastro tambem entra',
                 PacienteEmEspera.objects.filter(tenant=tenant, patient=joao, status=EsperaStatus.AGUARDANDO).exists(),
                 True)

        print('\n3. As recusas')
        try:
            espera.incluir(ctx, maria, consulta_marcada=dez_dias)
            conferir('o mesmo paciente de novo e recusado', False, True)
        except espera.EsperaError as exc:
            conferir('o mesmo paciente de novo e recusado', 'já está' in str(exc), True)
        hoje_ana = consulta(ana, 0, hora=16)
        try:
            espera.incluir(ctx, ana, consulta_marcada=hoje_ana)
            conferir('consulta de hoje e recusada', False, True)
        except espera.EsperaError as exc:
            conferir('consulta de hoje e recusada', 'hoje' in str(exc), True)
        try:
            espera.incluir(ctx, ana, consulta_marcada=dez_dias)
            conferir('consulta de outro paciente e recusada', False, True)
        except espera.EsperaError:
            conferir('consulta de outro paciente e recusada', True, True)
        if vinculo_b:
            cb = cliente_de(vinculo_b)
            conferir('outra clinica nao alcanca o horario', cb.get(url).status_code, 404)
            conferir('  nem pelo POST', cb.post(url, {'acao': 'retirar'}).status_code, 404)

        print('\n4. Retirar pela agenda')
        c.post(reverse('scheduling:appointment-espera', args=[pre.id]), {'acao': 'retirar'})
        saida = PacienteEmEspera.objects.filter(tenant=tenant, patient=joao).first()
        conferir('retirado, com o motivo', (saida.status, saida.motivo_saida),
                 (EsperaStatus.RETIRADO, 'Retirado pela agenda.'))
        conferir('maria sobe para o primeiro lugar', PacienteEmEspera.objects.get(id=e.id).posicao, 1)

        print('\n5. Antecipar')
        tres_dias = consulta(maria, 3, hora=9)
        entrada = espera.para_puxar(ctx, e.id, medico)
        desmarcada = espera.marcar_agendada(ctx, entrada, tres_dias)
        dez_dias.refresh_from_db()
        conferir('a consulta antiga foi desmarcada', dez_dias.status, AppointmentStatus.CANCELLED)
        conferir('  com o motivo', 'Antecipada pela lista de espera' in dez_dias.cancellation_reason, True)
        conferir('  e devolvida para a tela', desmarcada is not None and desmarcada.id == dez_dias.id, True)
        conferir('a espera encerrou ligada a nova', (PacienteEmEspera.objects.get(id=e.id).status,
                                                     PacienteEmEspera.objects.get(id=e.id).appointment_id),
                 (EsperaStatus.AGENDADO, tres_dias.id))
        from events.models import OutboxEvent
        from scheduling.events import CANCELLED_TOPIC
        conferir('  e o paciente e avisado do cancelamento',
                 OutboxEvent.objects.filter(aggregate_id=dez_dias.id, topic=CANCELLED_TOPIC).exists(), True)
        ana_vinte = consulta(ana, 20, hora=11)
        e_ana = espera.incluir(ctx, ana, physician_membership=medico, consulta_marcada=ana_vinte)
        mais_tarde = consulta(ana, 25, hora=11)
        desmarcada = espera.marcar_agendada(ctx, espera.para_puxar(ctx, e_ana.id, medico), mais_tarde)
        ana_vinte.refresh_from_db()
        conferir('horario depois da consulta nao desmarca a antiga',
                 (desmarcada, ana_vinte.status), (None, AppointmentStatus.SCHEDULED))

        print('\n6. O dia da consulta')
        p1, p2, p3, p4 = (paciente(f'PACIENTE ROTEIRO DIA {n}') for n in range(4))
        amanha = consulta(p1, 1, hora=8)
        depois = consulta(p2, 2, hora=8)
        cancelada = consulta(p3, 1, hora=9)
        e1 = espera.incluir(ctx, p1, consulta_marcada=amanha)
        e2 = espera.incluir(ctx, p2, consulta_marcada=depois)
        e3 = espera.incluir(ctx, p3, consulta_marcada=cancelada)
        e4 = espera.incluir(ctx, p4)
        Appointment.objects.filter(id=cancelada.id).update(status=AppointmentStatus.CANCELLED)
        conferir('na vespera ninguem sai', espera.encerrar_no_dia_da_consulta(hoje), 0)
        amanha_dia = hoje + timedelta(days=1)
        conferir('no dia, sai so quem chegou a consulta', espera.encerrar_no_dia_da_consulta(amanha_dia), 1)
        estados = {x.id: (x.status, x.motivo_saida) for x in PacienteEmEspera.objects.filter(id__in=[e1.id, e2.id, e3.id, e4.id])}
        conferir('  a do dia saiu, com o motivo',
                 (estados[e1.id][0], 'Chegou o dia da consulta' in estados[e1.id][1]),
                 (EsperaStatus.RETIRADO, True))
        conferir('  a de depois de amanha fica', estados[e2.id][0], EsperaStatus.AGUARDANDO)
        conferir('  a consulta desmarcada por outro caminho deixa a espera', estados[e3.id][0], EsperaStatus.AGUARDANDO)
        conferir('  a espera sem consulta fica', estados[e4.id][0], EsperaStatus.AGUARDANDO)
        conferir('rodar de novo nao faz nada a mais', espera.encerrar_no_dia_da_consulta(amanha_dia), 0)
        conferir('a lista continua numerada sem buraco',
                 [x.posicao for x in espera.lista(tenant.id)], list(range(1, len(espera.lista(tenant.id)) + 1)))
        from scheduling.tasks import encerrar_esperas_do_dia_task
        conferir('a tarefa diaria existe e roda', 'encerradas' in encerrar_esperas_do_dia_task(), True)
        from django.conf import settings
        conferir('e esta na agenda do worker',
                 any(v['task'] == 'scheduling.tasks.encerrar_esperas_do_dia'
                     for v in settings.CELERY_BEAT_SCHEDULE.values()), True)

        print('\n7. A lista mostra a consulta a antecipar')
        r = c.get(reverse('scheduling:espera'))
        conferir('a tela da lista abre', r.status_code, 200)
        conferir('  com o aviso de antecipar', 'Antecipar a consulta de' in r.content.decode(), True)
        print('\n8. A coluna Acoes no inicio das tabelas de atendimentos')
        import re as _re
        from clinical.models import Encounter, EncounterKind, EncounterStatus
        Encounter.objects.create(
            tenant=tenant, patient=maria, physician_membership=medico, occurred_at=timezone.now(),
            status=EncounterStatus.IN_PROGRESS, kind=EncounterKind.FREE_TEXT, free_text='x',
        )
        cm = cliente_de(medico)
        for rotulo, endereco in (('ficha do paciente', reverse('patients:detail', args=[maria.id])),
                                 ('prontuario', reverse('clinical:timeline', args=[maria.id]))):
            html = cm.get(endereco).content.decode()
            cabecalhos = _re.findall(r'<th[^>]*>\s*(?:<a[^>]*>)?\s*([A-Za-zÀ-ú]+)', html)
            conferir(f'  {rotulo}: Acoes e a primeira coluna', cabecalhos[:2], ['Ações', 'Abertura'])
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: a lista de espera pela agenda inclui, retira, antecipa e esquece no dia da consulta.')
