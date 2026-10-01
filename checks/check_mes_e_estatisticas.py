"""A visao de mes e as estatisticas: o que o passado diz, e o que ele nao pode dizer.

Tres defeitos deram origem a este roteiro, e os dois primeiros sao da
mesma familia: **a tela mentia sobre o passado**.

- **"lotado" num dia que so passou.** O rotulo aparecia sempre que nao
  havia vaga livre -- e num dia vencido nunca ha. Navegando o mes
  anterior, todo dia dizia "lotado", pintando uma agenda cheia que nao
  existiu;
- **a consulta que aconteceu sumia.** `COMPLETED` nao esta em
  `OCCUPYING_STATUSES`, de proposito: atendimento encerrado libera a vaga
  para remarcacao. O efeito colateral era que, no mes passado, a celula
  voltava como "passou e ninguem usou" -- indistinguivel de um horario
  vago. Um mes cheio de trabalho aparecia vazio;
- **o horario ocupado nao dizia de quem era.** A secretaria que recebia
  uma ligacao tinha de abrir o dia para descobrir.

O que este roteiro cobra:

- a celula ocupada traz o **nome do paciente**;
- a consulta concluida aparece como `done`, e **nao** como vaga;
- a vaga que passou aparece como `past`, e a tela a chama de "vago";
- **nada disso mexe na disponibilidade**: as contas de vaga livre tem de
  dar exatamente o mesmo numero de antes;
- as estatisticas somam pela **mesma grade** da agenda, e separam atendido
  de falta e de cancelado;
- a tela de estatisticas abre para a secretaria -- e e informacao de
  operacao, nao de prontuario.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from patients.models import Patient, RegistrationStage
from scheduling.availability import day_grid, month_summary
from scheduling.estatisticas import do_mes, limites_do_mes
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
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
    ).select_related('user').first()


medico = vinculo_de('doctor')
secretaria = vinculo_de('secretary')


def paciente(nome):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome,
        registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['pacientes'].append(p.id)
    return p


def marcar(pac, quando, status, tipo=AppointmentType.FIRST_VISIT, minutos=40):
    fim = quando + timedelta(minutes=minutos)
    a = Appointment.objects.create(
        tenant=tenant, patient=pac, physician_membership=medico,
        starts_at=quando, ends_at=fim, occupied_range=(quando, fim),
        status=status, type=tipo,
    )
    criados['agendamentos'].append(a.id)
    return a


def celula_em(dia, instante):
    """A celula da grade que contem `instante`, com historico carregado."""
    resumo = month_summary(medico.id, [dia])
    for c in resumo[dia]['cells']:
        if c['start'] <= instante < c['end']:
            return c
    return None


try:
    print('\n1. Um dia que passou: quem foi atendido e o que ficou vago')
    # Um dia da semana passada em que o medico atende, para cair na grade.
    hoje = timezone.localdate()
    dia = hoje - timedelta(days=7)
    resumo_antes = month_summary(medico.id, [dia])
    celulas_antes = resumo_antes[dia]['cells']
    conferir('o dia tem grade publicada', len(celulas_antes) > 0, True)
    livres_antes = resumo_antes[dia]['free']
    passados_antes = resumo_antes[dia]['past']
    print(f'      antes: {len(celulas_antes)} celulas, '
          f'{livres_antes} livres, {passados_antes} vagas passadas')

    alvo = celulas_antes[0]
    atendido = paciente('Roteiro Mes Atendido')
    marcar(atendido, alvo['start'], AppointmentStatus.COMPLETED,
           minutos=int((alvo['end'] - alvo['start']).total_seconds() // 60))

    depois = celula_em(dia, alvo['start'])
    conferir('a celula atendida vira "done"', depois['status'], 'done')
    conferir('e traz o paciente para a tela',
             depois['exibida'].patient.full_name, 'ROTEIRO MES ATENDIDO')
    conferir('e nao conta como reserva ativa', depois['appointment'], None)

    resumo_depois = month_summary(medico.id, [dia])
    conferir('as vagas livres nao mudaram', resumo_depois[dia]['free'], livres_antes)
    conferir('e uma vaga passada virou atendimento',
             resumo_depois[dia]['past'], passados_antes - 1)
    conferir('o contador de atendidos subiu', resumo_depois[dia]['realizados'], 1)
    conferir('e o dia aparece como encerrado', resumo_depois[dia]['encerrado'], True)

    print('\n2. Um horario ocupado agora diz de quem e')
    # Um dia futuro em que o medico atende.
    futuro = None
    for n in range(1, 15):
        candidato = hoje + timedelta(days=n)
        r = month_summary(medico.id, [candidato])
        if r[candidato]['free']:
            futuro = candidato
            livre = next(c for c in r[candidato]['cells'] if c['status'] == 'free')
            break
    conferir('ha um dia futuro com vaga', futuro is not None, True)

    marcado = paciente('Roteiro Mes Ocupado')
    marcar(marcado, livre['start'], AppointmentStatus.SCHEDULED,
           minutos=int((livre['end'] - livre['start']).total_seconds() // 60))
    ocupada = celula_em(futuro, livre['start'])
    conferir('a celula fica ocupada', ocupada['status'], 'busy')
    conferir('com o nome do paciente',
             ocupada['exibida'].patient.full_name, 'ROTEIRO MES OCUPADO')
    conferir('e marcada como inicio da reserva', ocupada['is_start'], True)

    print('\n3. A disponibilidade nao mudou de comportamento')
    # `day_grid` sem historico tem de produzir exatamente o que produzia:
    # e dela que sai a oferta de vaga, e mexer nisso seria oferecer ou
    # esconder horario sem ninguem pedir.
    sem_hist = day_grid(medico.id, dia)
    conferir('sem historico, nenhuma celula "done"',
             sum(1 for c in sem_hist if c['status'] == 'done'), 0)
    conferir('e o numero de vagas livres e o mesmo',
             sum(1 for c in sem_hist if c['status'] == 'free'),
             resumo_depois[dia]['free'])
    conferir('a chave `exibida` existe para quem nao passa historico',
             'exibida' in sem_hist[0], True)

    print('\n4. A tela do mes mostra o nome, e chama o vago de vago')
    cliente = Client()
    cliente.force_login(medico.user)
    sessao = cliente.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()
    pagina = cliente.get(reverse('scheduling:month'), {
        'physician': str(medico.id), 'date': futuro.isoformat(),
    })
    conferir('a agenda do mes abre', pagina.status_code, 200)
    html = pagina.content.decode()
    conferir('o nome do paciente ocupado aparece',
             'ROTEIRO MES OCUPADO' in html, True)
    conferir('"Vago" aparece para o que passou', 'Vago' in html, True)
    conferir('a legenda explica o azul', 'já atendido' in html, True)
    # O defeito que originou tudo: "lotado" num dia que so passou.
    passado_html = cliente.get(reverse('scheduling:month'), {
        'physician': str(medico.id), 'date': dia.isoformat(),
    }).content.decode()
    conferir('dia encerrado nao diz "lotado"', 'encerrado' in passado_html, True)

    print('\n5. As estatisticas do mes')
    primeiro, ultimo, _ = limites_do_mes(futuro.year, futuro.month)
    dados = do_mes(tenant.id, futuro.year, futuro.month, [medico])
    por_tipo = {l['tipo']: l for l in dados['linhas']}
    conferir('a primeira consulta marcada entra como agendada',
             por_tipo[AppointmentType.FIRST_VISIT]['agendados'] >= 1, True)
    conferir('e nao como atendida',
             por_tipo[AppointmentType.FIRST_VISIT]['atendidos'], 0)
    conferir('os cinco tipos aparecem', len(dados['linhas']), 5)
    conferir('a ocupacao vem da grade',
             dados['ocupacao']['total'] > 0, True)
    conferir('e a taxa esta entre 0 e 100',
             0 <= dados['ocupacao']['taxa'] <= 100, True)

    # O mes do atendimento concluido.
    do_passado = do_mes(tenant.id, dia.year, dia.month, [medico])
    tipo_passado = {l['tipo']: l for l in do_passado['linhas']}
    conferir('o atendimento concluido conta como atendido',
             tipo_passado[AppointmentType.FIRST_VISIT]['atendidos'] >= 1, True)

    # Falta e cancelamento NAO podem somar ao movimento.
    faltou = paciente('Roteiro Mes Faltou')
    cancelou = paciente('Roteiro Mes Cancelou')
    base = timezone.make_aware(
        timezone.datetime.combine(dia, timezone.datetime.min.time())
    ) + timedelta(hours=9)
    marcar(faltou, base, AppointmentStatus.NO_SHOW)
    marcar(cancelou, base + timedelta(hours=1), AppointmentStatus.CANCELLED)
    recontado = do_mes(tenant.id, dia.year, dia.month, [medico])
    t = recontado['totais']
    conferir('a falta entra na coluna de falta', t['faltas'] >= 1, True)
    conferir('o cancelado na de cancelado', t['cancelados'] >= 1, True)
    conferir('e nenhum dos dois no de atendidos',
             t['atendidos'], do_passado['totais']['atendidos'])

    print('\n6. A tela de estatisticas abre para a secretaria')
    # Sao contagens de operacao do consultorio, nao prontuario: a recepcao
    # opera a agenda tanto quanto o medico.
    outro = Client()
    outro.force_login(secretaria.user)
    s2 = outro.session
    s2['tenant_id'] = str(tenant.id)
    s2.save()
    url = reverse('scheduling:estatisticas')
    resposta = outro.get(url)
    conferir('a secretaria abre', resposta.status_code, 200)
    corpo = resposta.content.decode()
    conferir('ve as contagens', 'Atendidos no mês' in corpo, True)
    # E nao pode haver nome de paciente numa tela aberta por contagem.
    conferir('e nao ve nome de paciente',
             'ROTEIRO MES OCUPADO' in corpo or 'ROTEIRO MES ATENDIDO' in corpo, False)
    conferir('mes invalido nao derruba',
             outro.get(url, {'mes': '13', 'ano': '2026'}).status_code, 200)
    conferir('ano absurdo nao derruba',
             outro.get(url, {'mes': '1', 'ano': '99999'}).status_code, 200)
    conferir('texto no lugar do mes nao derruba',
             outro.get(url, {'mes': 'abc'}).status_code, 200)
    conferir('medico inexistente nao derruba',
             outro.get(url, {'physician': 'nao-e-uuid'}).status_code, 200)

finally:
    Appointment.objects.filter(id__in=criados['agendamentos']).delete()
    n = Patient.objects.filter(id__in=criados['pacientes']).delete()[0]
    print(f'\n  limpeza: {n} objeto(s) de paciente removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o mes diz o que houve -- quem foi atendido, o que ficou vago --')
print('    sem mexer na oferta de vaga, e as estatisticas somam pela mesma grade.')
