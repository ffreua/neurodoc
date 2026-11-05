"""Balcão impresso, a confirmação que se desfaz e o mês que mostra só o mês.

Pedidos da recepção em 2026-11-05, vindos do uso:

- **imprimir o balcão do dia** — a lista em papel, sem menu nem botões, com
  a clínica e o dia no alto;
- **desfazer a confirmação** dada por engano — no crachá "Confirmado" do
  balcão e no modal do horário, sempre com a pergunta antes. É uma
  transição nova, `Confirmado → Agendado`, e só ela: nada mais volta;
- **o mês mostra só o mês**: os dias do mês vizinho, que completam a
  semana, saem vazios (os pacientes deles atrapalhavam quem procura vaga),
  e cada dia diz `dd/mm`;
- **quem fez check-in sai azul** no mês, como atendido. A recepção não
  aperta "Concluir", a consulta fica em "Check-in feito", e por isso o mês
  passado saía todo vermelho. A cor muda; a vaga e o modal, não;
- **o confirmado se distingue** no mês por um ✓ ao lado da hora, e a falta
  sai riscada em vez de azul.

Tudo dentro de agendamentos criados e apagados aqui.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from patients.models import Patient, RegistrationStage
from scheduling import services
from scheduling.availability import month_summary
from scheduling.models import ALLOWED_TRANSITIONS, Appointment, AppointmentStatus, AppointmentType
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'agendamentos': [], 'pacientes': []}


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')


def vinculo_de(papel):
    return Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').order_by('user__email').first()


medico = vinculo_de('doctor')
secretaria = vinculo_de('secretary')


def paciente(nome):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome, registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['pacientes'].append(p.id)
    return p


def marcar(pac, quando, status, minutos=40):
    fim = quando + timedelta(minutes=minutos)
    a = Appointment.objects.create(
        tenant=tenant, patient=pac, physician_membership=medico,
        starts_at=quando, ends_at=fim, occupied_range=(quando, fim),
        status=status, type=AppointmentType.FOLLOW_UP,
    )
    criados['agendamentos'].append(a.id)
    return a


def celulas_livres(dias, futuro):
    """Primeira célula de grade em `dias` (livre se futuro, vaga se passado)."""
    resumo = month_summary(medico.id, dias)
    alvo = 'free' if futuro else 'past'
    for dia in dias:
        for c in resumo[dia]['cells']:
            if c['status'] == alvo:
                return dia, c['start']
    return None, None


hoje = timezone.localdate()
inicio_mes = hoje.replace(day=1)
proximo_mes = (inicio_mes + timedelta(days=32)).replace(day=1)
dias_do_mes = [inicio_mes + timedelta(days=i) for i in range((proximo_mes - inicio_mes).days)]

try:
    sec = Client()
    sec.force_login(secretaria.user)
    # A secretária da demonstração atende em mais de uma clínica: sem a
    # clínica na sessão, toda tela de /app/ manda escolher a organização.
    sessao = sec.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()

    print('\n1. A transição nova é uma só: Confirmado -> Agendado')
    conferir('confirmado pode voltar a agendado',
             AppointmentStatus.SCHEDULED in ALLOWED_TRANSITIONS[AppointmentStatus.CONFIRMED], True)
    conferir('check-in continua sem volta',
             ALLOWED_TRANSITIONS[AppointmentStatus.CHECKED_IN], {AppointmentStatus.IN_PROGRESS})
    conferir('falta e cancelado continuam sem saida',
             (ALLOWED_TRANSITIONS[AppointmentStatus.NO_SHOW], ALLOWED_TRANSITIONS[AppointmentStatus.CANCELLED]),
             (set(), set()))

    dia_f, inicio_f = celulas_livres([d for d in dias_do_mes if d > hoje], futuro=True)
    if dia_f is None:
        # Fim do mês sem grade à frente: procura no seguinte.
        seguinte = [proximo_mes + timedelta(days=i) for i in range(28)]
        dia_f, inicio_f = celulas_livres(seguinte, futuro=True)
    confirmado = marcar(paciente('ROTEIRO BALCAO CONFIRMADO'), inicio_f, AppointmentStatus.CONFIRMED)

    print('\n2. O balcão: imprimir e desfazer a confirmação')
    pagina = sec.get(reverse('scheduling:desk') + f'?date={dia_f:%Y-%m-%d}').content.decode()
    conferir('botão Imprimir no balcão', 'data-nd-print' in pagina, True)
    conferir('cabeçalho só de papel com o dia', 'nd-balcao-impresso' in pagina
             and f'{dia_f:%d/%m/%Y}' in pagina, True)
    conferir('coluna de ações fora da impressão', pagina.count('text-end pe-4 nd-no-print') >= 2, True)
    acao = reverse('scheduling:action', args=[confirmado.id, 'unconfirm'])
    conferir('o crachá Confirmado desfaz, com a pergunta antes',
             f'action="{acao}"' in pagina and 'Desfazer a confirmação de' in pagina, True)
    conferir('sem GET: desfazer exige POST', sec.get(acao).status_code, 405)

    resposta = sec.post(acao, {'return_to': reverse('scheduling:desk')})
    confirmado.refresh_from_db()
    conferir('POST volta o horário a Agendado', confirmado.status, AppointmentStatus.SCHEDULED)
    conferir('  e devolve ao balcão do dia', resposta.status_code == 302
             and resposta['Location'].startswith(reverse('scheduling:desk')), True)
    sec.post(acao, {'return_to': reverse('scheduling:desk')})
    confirmado.refresh_from_db()
    conferir('desfazer de novo não muda nada', confirmado.status, AppointmentStatus.SCHEDULED)
    sec.post(reverse('scheduling:action', args=[confirmado.id, 'confirm']))
    confirmado.refresh_from_db()
    conferir('e confirmar de novo funciona', confirmado.status, AppointmentStatus.CONFIRMED)

    sem = marcar(paciente('ROTEIRO BALCAO CHECKIN'), inicio_f - timedelta(days=400), AppointmentStatus.CHECKED_IN)
    try:
        services.transition_appointment(sem, AppointmentStatus.SCHEDULED, secretaria.user_id)
        voltou = True
    except services.SchedulingError:
        voltou = False
    conferir('check-in não volta a Agendado pelo serviço', voltou, False)

    print('\n3. O modal da agenda oferece desfazer só no confirmado')
    modal = open('templates/scheduling/_booking_modals.html', encoding='utf-8').read()
    js = open('static/scheduling/agenda.js', encoding='utf-8').read()
    conferir('formulário escondido de saída e com pergunta',
             'id="slot-unconfirm-form" hidden' in modal and 'data-nd-confirm="Desfazer a confirmação' in modal, True)
    conferir('o JS mostra só para confirmado',
             "unconfirmForm.hidden = status !== 'confirmed'" in js, True)

    print('\n4. O mês mostra só o mês, com dd/mm')
    url_mes = reverse('scheduling:month') + f'?physician={medico.id}&date={dia_f:%Y-%m-%d}'
    mes = sec.get(url_mes).content.decode()
    inicio_m = dia_f.replace(day=1)
    fim_m = (inicio_m + timedelta(days=32)).replace(day=1)
    grade_ini = inicio_m - timedelta(days=inicio_m.weekday())
    grade_fim = fim_m + timedelta(days=(7 - fim_m.weekday()) % 7)
    fora = (inicio_m - grade_ini).days + (grade_fim - fim_m).days
    conferir('um td vazio por dia de outro mês', mes.count('nd-month-fora'), fora)
    conferir('o dia diz dd/mm', f'>\n                                    {dia_f:%d/%m}\n' in mes
             or f'{dia_f:%d/%m}' in mes, True)
    conferir('o ✓ do confirmado aparece', 'nd-month-slot-ok" title="Confirmado"' in mes, True)
    conferir('a legenda explica o ✓ e a falta', 'paciente confirmado' in mes and 'Riscado — falta' in mes, True)

    print('\n5. Quem chegou sai azul, a falta sai riscada')
    dia_p, inicio_p = celulas_livres([d for d in dias_do_mes if d < hoje], futuro=False)
    if dia_p is None:
        print('  (sem dia de grade vencido neste mês; seção pulada)')
    else:
        veio = marcar(paciente('ROTEIRO MES CHEGOU'), inicio_p, AppointmentStatus.CHECKED_IN)
        mes_p = sec.get(reverse('scheduling:month') + f'?physician={medico.id}&date={dia_p:%Y-%m-%d}').content.decode()
        trecho = mes_p.split(f'data-nd-appointment="{veio.id}"')[0][-400:]
        conferir('o check-in continua célula ocupada e clicável', f'data-nd-appointment="{veio.id}"' in mes_p, True)
        conferir('  com o data-status que o CSS pinta de azul', 'data-status="checked_in"' in trecho, True)
        Appointment.objects.filter(id=veio.id).update(status=AppointmentStatus.NO_SHOW)
        mes_p = sec.get(reverse('scheduling:month') + f'?physician={medico.id}&date={dia_p:%Y-%m-%d}').content.decode()
        conferir('a falta sai riscada e não azul', 'nd-month-slot-falta' in mes_p, True)

    print('\n6. A ficha mostra os agendamentos futuros')
    pac = paciente('ROTEIRO FICHA FUTUROS')
    agora = timezone.now()
    depois = marcar(pac, agora + timedelta(days=9), AppointmentStatus.SCHEDULED)
    antes = marcar(pac, agora + timedelta(days=2), AppointmentStatus.CONFIRMED)
    marcar(pac, agora - timedelta(days=30), AppointmentStatus.CHECKED_IN)
    marcar(pac, agora + timedelta(days=5), AppointmentStatus.CANCELLED)
    outro = marcar(paciente('ROTEIRO FICHA OUTRO'), agora + timedelta(days=3), AppointmentStatus.SCHEDULED)
    ficha = sec.get(reverse('patients:detail', args=[pac.id])).content.decode()
    bloco = ficha.split('id="agendamentos-futuros"')[1].split('Dados de base')[0] if 'id="agendamentos-futuros"' in ficha else ''
    d1 = timezone.localtime(antes.starts_at)
    d2 = timezone.localtime(depois.starts_at)
    conferir('o cartão existe', bool(bloco), True)
    conferir('os dois futuros, o mais próximo primeiro',
             f'{d1:%d/%m/%Y} às {d1:%H:%M}' in bloco and f'{d2:%d/%m/%Y}' in bloco
             and bloco.index(f'{d1:%d/%m/%Y}') < bloco.index(f'{d2:%d/%m/%Y}'), True)
    conferir('passado e cancelado ficam fora', bloco.count('list-group-item'), 2)
    conferir('o horário de outro paciente fica fora',
             f'{timezone.localtime(outro.starts_at):%d/%m/%Y às %H:%M}' in bloco, False)
    conferir('a data leva à agenda daquele dia', f'date={d1:%Y-%m-%d}' in bloco, True)
    vazio = paciente('ROTEIRO FICHA SEM HORARIO')
    conferir('sem horário, diz que não há',
             'Nenhum agendamento futuro.' in sec.get(reverse('patients:detail', args=[vazio.id])).content.decode(), True)

    css = open('static/duralux/neurodoc.css', encoding='utf-8').read()
    conferir('o CSS pinta o check-in de azul',
             'button.nd-month-slot-busy[data-status="checked_in"]' in css, True)
    conferir('a impressão esconde o título do balcão',
             '.nxl-container:has(.nd-balcao-impresso) .page-header' in css, True)
finally:
    Appointment.objects.filter(id__in=criados['agendamentos']).delete()
    n = Patient.objects.filter(id__in=criados['pacientes']).delete()[0]
    print(f'\n  limpeza: {n} objeto(s) de paciente removidos')

if falhas:
    print(f'\n{len(falhas)} falha(s):')
    for f in falhas:
        print('FALHA: ' + f)
    raise SystemExit(1)
print('\nTudo certo.')
