"""A marca de teleatendimento no agendamento (1.43).

Pedido do Dr. Fernando em 2026-11-10: a secretária marca o horário como
teleatendimento, e a marca aparece no modal do horário e em toda tela que
lista agendamento -- como o ✓ do confirmado --, para o médico e a recepção
saberem que aquele paciente não vem ao balcão.

É **marca de agenda, e nada além disso**. O roteiro tenta quebrar
exatamente isso: que ela mude versão, tipo, duração ou situação do horário;
que apareça em quem não foi marcado; que um GET a ligue; que outra clínica a
alcance; que ela siga para o paciente que entrou no lugar do anterior.

Tudo dentro de agendamentos e pacientes criados e apagados aqui.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from django.utils import timezone, translation

from audit.models import AuditEvent
from patients.models import Patient, RegistrationStage
from scheduling import agenda_por_email, services
from scheduling.availability import month_summary
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'agendamentos': [], 'pacientes': []}
ACAO = 'scheduling.appointment_teleatendimento_changed'


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo_de(papel, clinica=tenant):
    return Membership.objects.filter(
        tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[papel],
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


def marcar(pac, quando, status=AppointmentStatus.SCHEDULED, minutos=40, **extra):
    fim = quando + timedelta(minutes=minutos)
    a = Appointment.objects.create(
        tenant=tenant, patient=pac, physician_membership=medico,
        starts_at=quando, ends_at=fim, occupied_range=(quando, fim),
        status=status, type=AppointmentType.FOLLOW_UP, **extra,
    )
    criados['agendamentos'].append(a.id)
    return a


def celulas_livres(a_partir, quantas):
    """As primeiras células livres da grade, de `a_partir` em diante.

    Uma por dia: os horários do roteiro não podem encostar um no outro, e
    cada tela é conferida num dia que só tem o horário que interessa.
    """
    achadas = []
    dias = [a_partir + timedelta(days=i) for i in range(1, 75)]
    resumo = month_summary(medico.id, dias)
    for dia in dias:
        for c in resumo[dia]['cells']:
            if c['status'] == 'free':
                achadas.append((dia, c['start']))
                break
        if len(achadas) == quantas:
            break
    return achadas


def cliente(vinculo, clinica=tenant):
    c = Client()
    c.force_login(vinculo.user)
    sessao = c.session
    sessao['tenant_id'] = str(clinica.id)
    sessao.save()
    return c


def trilha(a):
    return AuditEvent.objects.filter(action=ACAO, object_id=str(a.id)).count()


hoje = timezone.localdate()
volta = reverse('scheduling:week')

try:
    sec = cliente(secretaria)
    livres = celulas_livres(hoje, 3)
    if len(livres) < 3:
        raise SystemExit('A demonstração não tem três dias com horário livre nos próximos 75 dias.')
    (dia1, ini1), (dia2, ini2), (dia3, ini3) = livres

    print('\n1. O campo nasce desligado, e o banco tem o padrão')
    campo = Appointment._meta.get_field('teleatendimento')
    conferir('padrão do modelo é presencial', campo.default, False)
    conferir('padrão também no banco (código antigo grava sem o campo)', campo.db_default, False)
    comum = marcar(paciente('ROTEIRO TELE PRESENCIAL'), ini1, AppointmentStatus.CONFIRMED)
    conferir('horário criado sem dizer nada é presencial', comum.teleatendimento, False)

    print('\n2. Marcar e retirar pelo modal: POST, e só a marca muda')
    tele = marcar(paciente('ROTEIRO TELE POR VIDEO'), ini2, AppointmentStatus.CONFIRMED)
    ligar = reverse('scheduling:action', args=[tele.id, 'teleatendimento'])
    desligar = reverse('scheduling:action', args=[tele.id, 'presencial'])
    conferir('GET não marca', sec.get(ligar).status_code, 405)
    tele.refresh_from_db()
    conferir('  e o horário segue presencial', tele.teleatendimento, False)
    antes = (tele.row_version, tele.status, tele.type, tele.starts_at, tele.ends_at)
    r = sec.post(ligar, {'return_to': volta})
    tele.refresh_from_db()
    conferir('POST marca', (r.status_code, tele.teleatendimento), (302, True))
    conferir('versão, situação, tipo e horário intactos',
             (tele.row_version, tele.status, tele.type, tele.starts_at, tele.ends_at), antes)
    conferir('uma linha na trilha', trilha(tele), 1)
    evento = AuditEvent.objects.filter(action=ACAO, object_id=str(tele.id)).first()
    conferir('a trilha diz só ligado ou desligado', evento.integrity_metadata, {'teleatendimento': True})
    sec.post(ligar, {'return_to': volta})
    tele.refresh_from_db()
    conferir('marcar de novo não desmarca (não é alternador)', tele.teleatendimento, True)
    conferir('  nem repete a trilha', trilha(tele), 1)
    sec.post(desligar, {'return_to': volta})
    tele.refresh_from_db()
    conferir('retirar volta a presencial', (tele.teleatendimento, trilha(tele)), (False, 2))
    med = cliente(medico)
    med.post(ligar, {'return_to': volta})
    tele.refresh_from_db()
    conferir('o médico também marca', tele.teleatendimento, True)

    print('\n3. O que já acabou não muda')
    ctx = AccessContext(
        user_id=secretaria.user_id, tenant_id=tenant.id, membership_id=secretaria.id,
        permissions=frozenset(secretaria.roles or []), request_id=None,
        tenant_status=tenant.status, capabilities=frozenset(),
    )
    passado = timezone.now() - timedelta(days=400)
    for n, status in enumerate((AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW, AppointmentStatus.COMPLETED)):
        velho = marcar(paciente(f'ROTEIRO TELE VELHO {n}'), passado - timedelta(days=n), status)
        sec.post(reverse('scheduling:action', args=[velho.id, 'teleatendimento']), {'return_to': volta})
        velho.refresh_from_db()
        conferir(f'{status}: recusado, sem trilha', (velho.teleatendimento, trilha(velho)), (False, 0))
    chegou = marcar(paciente('ROTEIRO TELE CHEGOU'), passado - timedelta(days=9), AppointmentStatus.CHECKED_IN)
    services.set_teleatendimento(ctx, chegou, True, secretaria.user_id)
    chegou.refresh_from_db()
    conferir('depois da chegada ainda marca', chegou.teleatendimento, True)

    print('\n4. Outra clínica não alcança')
    de_fora = vinculo_de('secretary', tenant_b) or vinculo_de('owner', tenant_b)
    fora = cliente(de_fora, tenant_b)
    conferir('POST de outra clínica dá 404', fora.post(desligar).status_code, 404)
    tele.refresh_from_db()
    conferir('  e a marca fica', tele.teleatendimento, True)

    print('\n5. A câmera em toda tela que lista o horário')
    marca = 'class="nd-tele"'

    def tela(nome, dia):
        return sec.get(reverse(nome) + f'?physician={medico.id}&date={dia:%Y-%m-%d}').content.decode()

    def botao(pagina, a):
        """O botão do horário `a` na grade: da abertura da tag ao fechamento."""
        i = pagina.find(f'data-nd-appointment="{a.id}"')
        if i < 0:
            return ''
        return pagina[pagina.rfind('<button', 0, i):pagina.find('</button>', i)]

    atributo = 'data-nd-appointment' in tela('scheduling:week', dia2)
    conferir('a grade identifica o horário por data-nd-appointment', atributo, True)
    for nome, rotulo in (('scheduling:week', 'semana'), ('scheduling:day', 'dia'), ('scheduling:month', 'mês')):
        b_t, b_c = botao(tela(nome, dia2), tele), botao(tela(nome, dia1), comum)
        conferir(f'{rotulo}: o marcado leva data-nd-tele="1" e a câmera',
                 ('data-nd-tele="1"' in b_t, marca in b_t), (True, True))
        conferir(f'{rotulo}: o presencial leva "0" e nenhuma câmera',
                 ('data-nd-tele="0"' in b_c, marca in b_c), (True, False))
    for nome, rotulo in (('scheduling:week', 'semana'), ('scheduling:month', 'mês')):
        pagina = tela(nome, dia1)
        conferir(f'{rotulo}: a legenda explica a câmera',
                 '</svg>\n Teleatendimento</span>' in pagina or '</svg> Teleatendimento</span>' in pagina, True)

    balcao = sec.get(reverse('scheduling:desk') + f'?date={dia2:%Y-%m-%d}').content.decode()
    linha = balcao[balcao.find('ROTEIRO TELE POR VIDEO'):].split('</tr>')[0]
    conferir('balcão: crachá com a palavra (sai na impressão)',
             'nd-tele-badge' in linha and 'Teleatendimento' in linha, True)
    balcao_c = sec.get(reverse('scheduling:desk') + f'?date={dia1:%Y-%m-%d}').content.decode()
    linha_c = balcao_c[balcao_c.find('ROTEIRO TELE PRESENCIAL'):].split('</tr>')[0]
    conferir('balcão: o presencial sem crachá', bool(linha_c) and 'nd-tele-badge' not in linha_c, True)

    ficha = sec.get(reverse('patients:detail', args=[tele.patient_id])).content.decode()
    bloco = ficha.split('id="agendamentos-futuros"')[1].split('Dados de base')[0]
    conferir('ficha: o agendamento futuro diz teleatendimento', marca in bloco and 'teleatendimento' in bloco, True)
    ficha_c = sec.get(reverse('patients:detail', args=[comum.patient_id])).content.decode()
    conferir('ficha: o presencial não diz',
             marca in ficha_c.split('id="agendamentos-futuros"')[1].split('Dados de base')[0], False)

    print('\n6. O modal: a marca no alto e um botão de cada vez')
    modal = open('templates/scheduling/_booking_modals.html', encoding='utf-8').read()
    js = open('static/scheduling/agenda.js', encoding='utf-8').read()
    conferir('o crachá nasce escondido', 'id="slot-tele" hidden' in modal, True)
    conferir('os dois formulários são POST, escondidos, com CSRF',
             all(f'<form method="post" id="{i}" hidden>' in modal
                 and '{% csrf_token %}' in modal.split(f'id="{i}" hidden>')[1][:80]
                 for i in ('slot-tele-on-form', 'slot-tele-off-form')), True)
    conferir('o JS aponta para as duas ações', "'/teleatendimento/'" in js and "'/presencial/'" in js, True)
    conferir('  e mostra um ou outro', 'teleOnForm.hidden = tele || !teleEditavel' in js
             and 'teleOffForm.hidden = !tele || !teleEditavel' in js, True)
    conferir('a caixa de marcar é limpa a cada abertura', 'bookTele.checked = false' in js, True)
    conferir('a câmera é SVG com nome para o leitor de tela',
             'aria-label="Teleatendimento"' in open('templates/scheduling/_tele.html', encoding='utf-8').read(), True)

    print('\n7. Já ao marcar o horário')
    conferir('a caixa existe no modal de marcar', 'name="teleatendimento"' in modal and 'id="book-tele"' in modal, True)
    book = reverse('scheduling:quick-book', args=[medico.id])

    def marcar_pela_tela(nome, **extra):
        pac = paciente(nome)
        sec.post(book, {
            'starts_at': ini3.isoformat(), 'appointment_type': 'follow_up',
            'patient_id': str(pac.id), 'date': dia3.isoformat(), **extra,
        })
        a = Appointment.objects.filter(tenant=tenant, patient=pac).first()
        if a:
            criados['agendamentos'].append(a.id)
        return a

    novo = marcar_pela_tela('ROTEIRO TELE AO MARCAR', teleatendimento='on')
    conferir('marcado com a caixa: nasce teleatendimento', bool(novo and novo.teleatendimento), True)
    if novo:
        services.cancel_appointment(novo, secretaria.user_id, reason='roteiro')
    sem = marcar_pela_tela('ROTEIRO TELE SEM A CAIXA')
    conferir('sem a caixa: presencial, como sempre', (bool(sem), bool(sem and sem.teleatendimento)), (True, False))

    print('\n8. Remarcar leva a marca; trocar o paciente, não')
    tele.refresh_from_db()
    destino = (ini2 + timedelta(days=200)).replace(minute=3)
    remarcado = services.reschedule_appointment(
        ctx, tele, destino, destino + timedelta(minutes=40), secretaria.user_id,
    )
    remarcado.refresh_from_db()
    conferir('remarcado continua teleatendimento', remarcado.teleatendimento, True)
    outro = paciente('ROTEIRO TELE QUEM ENTROU')
    services.change_appointment_patient(ctx, remarcado, outro, 'Roteiro de verificacao.', secretaria.user_id)
    remarcado.refresh_from_db()
    conferir('paciente trocado: volta a presencial',
             (remarcado.patient_id, remarcado.teleatendimento), (outro.id, False))

    print('\n9. A agenda do dia seguinte por e-mail diz')
    a = marcar(paciente('ROTEIRO TELE NO EMAIL'), ini1 + timedelta(days=300), teleatendimento=True)
    b = marcar(paciente('ROTEIRO TELE FORA DO EMAIL'), ini1 + timedelta(days=300, hours=2))
    dia_e = timezone.localtime(a.starts_at).date()
    for horarios, esperado in (([a], True), ([b], False)):
        dados = agenda_por_email.contexto(medico, dia_e, horarios)
        with translation.override(dj_settings.LANGUAGE_CODE):
            html = render_to_string('scheduling/email/agenda_do_dia.html', dados)
            texto = render_to_string('scheduling/email/agenda_do_dia.txt', dados)
        conferir(f'{"com" if esperado else "sem"} a marca: HTML e texto',
                 ('Teleatendimento' in html, 'teleatendimento' in texto), (esperado, esperado))
        conferir('  sem SVG (o cliente de e-mail o descarta)', '<svg' in html, False)

    print('\n10. O desenho')
    css = open('static/duralux/neurodoc.css', encoding='utf-8').read()
    conferir('a câmera não encolhe com o nome cortado',
             '.nd-tele {' in css and 'flex-shrink: 0' in css.split('.nd-tele {')[1][:200], True)
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
