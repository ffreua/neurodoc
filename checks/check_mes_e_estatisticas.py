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
    # Um dia **que ja passou e em que o medico atende**, procurado e nao
    # assumido.
    #
    # Era `hoje - 7 dias`, que preserva o dia da semana -- e o medico da
    # base de demonstracao atende so terca e quinta. O roteiro passava em
    # dois dias da semana e reprovava nos outros cinco, sem defeito nenhum
    # no produto. Rodado numa quinta, parecia saudavel; na sexta seguinte,
    # a bateria inteira ficava vermelha.
    #
    # Verificacao que depende do dia em que e executada nao verifica: ela
    # ensina quem a le a ignorar o vermelho.
    #
    # E no **mes anterior**, nao em qualquer dia passado: a secao 5 compara
    # as estatisticas do mes do atendimento concluido com as do mes do
    # agendamento futuro, e as duas tem de ser meses diferentes. Procurar
    # so "um dia passado com grade" fazia os dois cairem em outubro no
    # inicio do mes, e a contagem de atendidos vazava de um para o outro.
    hoje = timezone.localdate()
    ultimo_do_mes_anterior = hoje.replace(day=1) - timedelta(days=1)
    dia = None
    for recuo in range(0, 31):
        candidato = ultimo_do_mes_anterior - timedelta(days=recuo)
        if month_summary(medico.id, [candidato])[candidato]['cells']:
            dia = candidato
            break
    conferir('ha um dia do mes anterior com grade publicada',
             dia is not None, True)
    if dia is None:
        raise SystemExit(1)
    print(f'     (dia escolhido: {dia}, {["seg","ter","qua","qui","sex","sab","dom"][dia.weekday()]})')
    conferir('e ele e de um mes diferente do de hoje', dia.month != hoje.month, True)
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

    # O horario marcado tem de ser clicavel, e abrir o MESMO modal da
    # semana e do dia. O mecanismo e o `agenda.js`, que escuta
    # `[data-nd-appointment]` no documento: se a celula do mes nao carregar
    # os atributos que ele le, o clique nao faz nada -- e nada e
    # exatamente o que acontecia.
    import re as _re2

    bloco = _re2.search(
        r'<button[^>]*nd-month-slot-busy[^>]*>.{0,400}?</button>', html, _re2.S,
    )
    conferir('o horario ocupado e um botao', bloco is not None, True)
    if bloco:
        marcacao = bloco.group(0)
        for atributo in ('data-nd-appointment', 'data-nd-patient', 'data-nd-patient-id',
                         'data-nd-when', 'data-nd-until', 'data-nd-type',
                         'data-nd-status-label', 'data-nd-preliminary'):
            conferir(f'  carrega {atributo}', atributo in marcacao, True)
        conferir('  e o id do agendamento nao vem vazio',
                 _re2.search(r'data-nd-appointment="[0-9a-f-]{36}"', marcacao) is not None,
                 True)
    # O modal e o script que o movem precisam estar na pagina do mes.
    conferir('o modal do horario esta na pagina', 'id="slot-modal"' in html, True)
    conferir('e o script que o abre tambem', 'scheduling/agenda.js' in html, True)
    # O defeito que originou tudo: "lotado" num dia que so passou.
    passado_html = cliente.get(reverse('scheduling:month'), {
        'physician': str(medico.id), 'date': dia.isoformat(),
    }).content.decode()
    # Contado nas CELULAS, e nao na pagina: a legenda da tela explica o que
    # "lotado" e "encerrado" significam e contem as duas palavras. Procurar
    # na pagina inteira dava verde com o defeito presente -- foi exatamente
    # o que aconteceu, e o usuario viu "lotado" numa tela que o roteiro
    # tinha aprovado.
    import re as _re

    rotulos = _re.findall(r'class="d-block fs-10 mt-1[^"]*">\s*([^<\s]+)', passado_html)
    print(f'      rotulos de dia no mes passado: {rotulos}')
    conferir('nenhum dia vencido diz "lotado"', 'lotado' in rotulos, False)
    conferir('e ha dia dizendo "encerrado"', 'encerrado' in rotulos, True)

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

    print('\n6. "Fechado" e o dia inteiro bloqueado, e nada menos')
    # O defeito de 13/10/2026, relatado por quem usa: a secretaria
    # terminou de preencher as vagas da terca e o dia virou **"fechado"**
    # no calendario -- com os oito agendamentos invisiveis, porque o ramo
    # que os lista nem era alcancado.
    #
    # A causa: o rotulo saia de "ha celula bloqueada e nenhuma livre".
    # Isso valia enquanto a unica coisa que bloqueava celula era excecao
    # de **data** -- feriado e ferias tomam o dia todo, entao as duas
    # frases eram a mesma. O intervalo semanal (o almoco) quebrou a
    # equivalencia: ele bloqueia **uma** celula.
    from scheduling.models import AvailabilityRule, RecurringBreak, ScheduleBlock, ScheduleBlockKind

    def rotulos_do_mes(quando):
        """Os rotulos de dia na pagina do mes, por dia do mes."""
        import re as _re3

        pagina = cliente.get(reverse('scheduling:month'), {
            'physician': str(medico.id), 'date': quando.isoformat(),
        }).content.decode()
        # Cada celula de dia comeca com o numero e traz o rotulo adiante.
        achados = {}
        for bloco_dia in _re3.findall(
            r'<div class="nd-month-day.*?</div>\s*</td>', pagina, _re3.S,
        ):
            numero = _re3.search(r'fs-13">\s*(\d+)\s*<', bloco_dia)
            if not numero:
                continue
            rotulo = ''
            if 'fechado' in bloco_dia:
                rotulo = 'fechado'
            elif 'encerrado' in bloco_dia:
                rotulo = 'encerrado'
            elif 'lotado' in bloco_dia:
                rotulo = 'lotado'
            elif 'livre' in bloco_dia:
                rotulo = 'livres'
            achados[int(numero.group(1))] = rotulo
        return achados

    # Um dia **que ja passou** e em que o medico atende: ali `free` e
    # sempre zero (a hora passou), que e a metade da condicao antiga. Com
    # um intervalo no dia, a outra metade tambem fica verdadeira -- e o
    # dia dizia "fechado" sem haver feriado nenhum. Reproduz o defeito
    # sem precisar lotar a agenda.
    regra_do_dia = AvailabilityRule.objects.filter(
        physician_membership=medico, weekday=dia.weekday(),
    ).first()
    pausa_teste = None
    bloqueio_teste = None
    try:
        if regra_do_dia is None:
            conferir('ha regra no dia vencido para exercitar o rotulo', False, True)
        else:
            pausa_teste = RecurringBreak.objects.create(
                tenant=tenant, physician_membership=medico, weekday=dia.weekday(),
                local_start=regra_do_dia.local_start,
                local_end=(
                    timezone.datetime.combine(dia, regra_do_dia.local_start)
                    + timedelta(minutes=20)
                ).time(),
                starts_on=dia - timedelta(days=1), reason='Cafe do roteiro',
            )
            rotulos = rotulos_do_mes(dia)
            print(f'      dia {dia.day} (vencido, com intervalo): {rotulos.get(dia.day)!r}')
            conferir('dia vencido com intervalo NAO diz "fechado"',
                     rotulos.get(dia.day) == 'fechado', False)
            conferir('  e diz "encerrado", que e o que de fato houve',
                     rotulos.get(dia.day), 'encerrado')

            # E o contrario tem de continuar valendo: dia inteiro tomado
            # por excecao de data **e** fechado, e a palavra tem de sair.
            #
            # Uma semana depois de `futuro`, e nao `futuro`: aquele ja
            # tem consultas marcadas por este roteiro, e dia com paciente
            # nao e fechado -- a celula ocupada vence o bloqueio. Com ele,
            # a assercao reprovaria por culpa do cenario, nao do produto.
            # Mesmo dia da semana para a regra continuar valendo.
            alvo_bloqueio = futuro + timedelta(days=7)
            antes = rotulos_do_mes(alvo_bloqueio).get(alvo_bloqueio.day)
            print(f'      dia {alvo_bloqueio.day} antes do bloqueio: {antes!r}')
            conferir('  o dia escolhido nao estava fechado antes',
                     antes == 'fechado', False)

            inicio_dia = timezone.make_aware(
                timezone.datetime.combine(alvo_bloqueio, timezone.datetime.min.time()),
            )
            bloqueio_teste = ScheduleBlock.objects.create(
                tenant=tenant, physician_membership=medico,
                start_at=inicio_dia, end_at=inicio_dia + timedelta(days=1),
                kind=ScheduleBlockKind.HOLIDAY, reason='Feriado do roteiro',
            )
            rotulos = rotulos_do_mes(alvo_bloqueio)
            print(f'      dia {alvo_bloqueio.day} (bloqueado o dia todo): '
                  f'{rotulos.get(alvo_bloqueio.day)!r}')
            conferir('dia inteiro bloqueado continua dizendo "fechado"',
                     rotulos.get(alvo_bloqueio.day), 'fechado')
    finally:
        if pausa_teste is not None:
            pausa_teste.delete()
        if bloqueio_teste is not None:
            bloqueio_teste.delete()

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
