"""Declaracao de comparecimento: o que o papel diz, e o que nao pode dizer.

Este e um documento que sai da clinica e vai para a mao de um empregador.
Tudo que ele carregar a mais do que precisa, carrega para alguem que nao
tinha direito a saber.

O que este roteiro cobra, e onde da errado:

- **nao ha diagnostico, CID nem motivo no papel.** Informacao de saude e
  dado pessoal sensivel (LGPD art. 5, II), e o paciente levaria o papel
  sem saber o que estava levando. A assercao varre o HTML atras do CID do
  atendimento e do texto do diagnostico;
- **nao e atestado, e o texto nao da margem.** Atestado afirma
  incapacidade e e ato medico; isto afirma presenca. O rodape tem de
  negar a leitura errada com todas as letras;
- **a secretaria emite, o paciente nao.** A capacidade e a da agenda. Quem
  nao tem vinculo com a clinica nao alcanca o horario de ninguem;
- **a fronteira entre clinicas:** agendamento da clinica B nao vira papel
  timbrado da clinica A;
- **saida antes da entrada nao imprime.** Papel dizendo "das 16h as 14h"
  chegaria ao departamento pessoal como erro da clinica;
- **ver nao e emitir.** GET nao pode gravar emissao na trilha, senao
  ajustar o horario tres vezes deixaria tres emissoes registradas e
  atualizar a pagina emitiria de novo;
- **a emissao fica na trilha, sem conteudo clinico junto.**
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from clinical.models import (
    DiagnosisCertainty, Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus,
)
from patients.models import Patient, RegistrationStage
from scheduling.declaracao import _duracao, horarios
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'agendamentos': [], 'pacientes': [], 'encontros': [], 'diagnosticos': []}

EVENTO = 'scheduling.attendance_statement_issued'


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:60} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')


def vinculo_de(dono, papel):
    return Membership.objects.filter(
        tenant=dono, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').first()


medico = vinculo_de(tenant, 'doctor')
secretaria = vinculo_de(tenant, 'secretary')
agora = timezone.localtime()


def sessao(vinculo, dono):
    c = Client()
    c.force_login(vinculo.user)
    s = c.session
    s['tenant_id'] = str(dono.id)
    s.save()
    return c


def marcar(dono, quem, paciente, inicio, minutos=60):
    fim = inicio + timedelta(minutes=minutos)
    a = Appointment.objects.create(
        tenant=dono, patient=paciente, physician_membership=quem,
        starts_at=inicio, ends_at=fim, occupied_range=(inicio, fim),
        status=AppointmentStatus.COMPLETED, type=AppointmentType.OTHER,
    )
    criados['agendamentos'].append(a.id)
    return a


def novo_paciente(nome, dono=None, cpf=''):
    p = Patient.objects.create(
        tenant=dono or tenant, full_name=nome, cpf=cpf,
        registration_stage=RegistrationStage.COMPLETE,
    )
    criados['pacientes'].append(p.id)
    return p


def emissoes(agendamento):
    return AuditEvent.objects.filter(
        action=EVENTO, object_id=agendamento.id,
    ).count()


try:
    print('\n1. A conta dos horarios')
    ontem = (agora - timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    paciente = novo_paciente('Roteiro Declaracao Paciente', cpf='52998224725')
    consulta = marcar(tenant, medico, paciente, ontem, minutos=90)

    padrao = horarios(consulta)
    conferir('sem digitar nada, vem do agendamento',
             padrao['entrada'].strftime('%H:%M'), '14:00')
    conferir('e a saida tambem', padrao['saida'].strftime('%H:%M'), '15:30')
    conferir('a duracao sai legivel', padrao['duracao'], '1h30')
    conferir('hora redonda nao vira "2h00"', _duracao(*[
        horarios(consulta, '14:00', '16:00')[k] for k in ('entrada', 'saida')
    ]), '2h')
    conferir('menos de uma hora sai em minutos',
             horarios(consulta, '14:00', '14:40')['duracao'], '40 minutos')

    corrigido = horarios(consulta, '13:45', '16:10')
    conferir('o que a secretaria digita vence a grade',
             corrigido['entrada'].strftime('%H:%M'), '13:45')
    conferir('hora malformada nao quebra e cai no padrao',
             horarios(consulta, 'lixo', '')['entrada'].strftime('%H:%M'), '14:00')
    invertido = horarios(consulta, '16:00', '14:00')
    conferir('saida antes da entrada e sinalizada', invertido['invertido'], True)
    conferir('e a duracao nao inventa numero negativo', invertido['duracao'], '')

    print('\n2. O papel nao carrega diagnostico')
    # O paciente tem CID no prontuario. Nada disso pode vazar para o papel
    # que vai ao empregador.
    atendimento = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        occurred_at=ontem, status=EncounterStatus.FINALIZED,
        kind=EncounterKind.FREE_TEXT, free_text='Roteiro.', plan_text='Roteiro.',
    )
    criados['encontros'].append(atendimento.id)
    diag = EncounterDiagnosis.objects.create(
        tenant=tenant, encounter=atendimento, code_snapshot='G40.2',
        description_snapshot='Epilepsia sintomatica', certainty=DiagnosisCertainty.CONFIRMED,
        rank=1,
    )
    criados['diagnosticos'].append(diag.id)

    cliente = sessao(secretaria, tenant)
    url = reverse('scheduling:declaracao', args=[consulta.id])
    resposta = cliente.get(url)
    conferir('a secretaria abre a declaracao', resposta.status_code, 200)
    papel = resposta.content.decode()

    conferir('o CID nao aparece', 'G40' in papel, False)
    conferir('o texto do diagnostico nao aparece', 'Epilepsia' in papel, False)
    conferir('o motivo/queixa nao aparece', 'queixa' in papel.lower(), False)
    conferir('mas o nome do paciente sim', paciente.full_name in papel, True)
    conferir('e o CPF, que identifica para o empregador', '52998224725' in papel, True)
    conferir('e o medico que atendeu',
             medico.user.get_full_name() in papel, True)

    print('\n3. Nao e atestado, e o papel diz isso')
    conferir('o titulo e "declaracao de comparecimento"',
             'Declaração de comparecimento' in papel, True)
    conferir('o rodape nega ser atestado',
             'Não constitui' in papel and 'atestado médico' in papel, True)
    conferir('e nega atestar incapacidade',
             'incapacidade para o trabalho' in papel, True)
    conferir('e explica por que nao traz diagnostico',
             'não contém diagnóstico' in papel, True)
    # A palavra "atestamos" abriria a leitura que o rodape fecha.
    for proibida in ['atestamos', 'apto', 'inapto', 'afastamento', 'repouso']:
        if proibida in papel.lower():
            falhas.append(f'o papel usa linguagem de atestado: "{proibida}"')
    conferir('sem linguagem de atestado no corpo',
             any(p in papel.lower() for p in ['atestamos', 'afastamento', 'repouso']), False)

    print('\n4. Ver nao e emitir')
    conferir('nada na trilha depois de abrir', emissoes(consulta), 0)
    cliente.get(url, {'entrada': '13:50', 'saida': '15:40'})
    conferir('nem depois de ajustar os horarios', emissoes(consulta), 0)

    emitida = cliente.post(url, {'entrada': '13:50', 'saida': '15:40'})
    conferir('o POST emite', emitida.status_code, 200)
    conferir('e a trilha registra uma vez', emissoes(consulta), 1)
    impresso = emitida.content.decode()
    conferir('a folha pede impressao', 'data-nd-imprimir="1"' in impresso, True)
    conferir('com os horarios corrigidos', '13:50' in impresso and '15:40' in impresso, True)
    conferir('a visualizacao nao pede impressao',
             'data-nd-imprimir' in cliente.get(url).content.decode(), False)

    registro = AuditEvent.objects.filter(
        action=EVENTO, object_id=consulta.id,
    ).order_by('-created_at').first()
    metadados = str(registro.integrity_metadata)
    conferir('a trilha guarda os horarios emitidos', '13:50' in metadados, True)
    conferir('e nao guarda conteudo clinico', 'G40' in metadados, False)

    print('\n5. Horario invertido nao vira papel')
    torto = cliente.post(url, {'entrada': '16:00', 'saida': '14:00'})
    conferir('a tela responde mesmo assim', torto.status_code, 200)
    conferir('mas avisa em vez de imprimir',
             'data-nd-imprimir' in torto.content.decode(), False)
    conferir('e diz o que corrigir',
             'saída está antes da entrada' in torto.content.decode(), True)
    conferir('e nao registra emissao', emissoes(consulta), 1)

    print('\n6. O acompanhante, quando ha')
    com_acompanhante = cliente.post(url, {
        'entrada': '14:00', 'saida': '15:30', 'acompanhante': 'Maria da Silva',
    }).content.decode()
    conferir('o nome sai no papel', 'Maria da Silva' in com_acompanhante, True)
    conferir('dizendo que acompanhou', 'Acompanhou' in com_acompanhante, True)
    sem = cliente.post(url, {'entrada': '14:00', 'saida': '15:30'}).content.decode()
    conferir('sem acompanhante, a frase some', 'Acompanhou' in sem, False)

    print('\n7. A fronteira entre clinicas')
    outra = Tenant.objects.exclude(id=tenant.id).filter(
        membership__status=MembershipStatus.ACTIVE,
    ).distinct().first()
    if outra is not None:
        medico_b = vinculo_de(outra, 'doctor')
        if medico_b is not None:
            de_fora = novo_paciente('Roteiro Declaracao Outra', dono=outra)
            consulta_b = marcar(
                outra, medico_b, de_fora,
                ontem.replace(hour=9), minutos=30,
            )
            alheia = cliente.get(reverse('scheduling:declaracao', args=[consulta_b.id]))
            conferir('a clinica A nao emite papel do agendamento da B',
                     alheia.status_code, 404)

    print('\n8. As portas onde a secretaria a encontra')
    balcao = cliente.get(reverse('scheduling:desk'), {'date': ontem.date().isoformat()})
    conferir('o balcao do dia oferece a declaracao',
             f'/declaracao/' in balcao.content.decode(), True)
    modais = cliente.get(reverse('scheduling:week')).content.decode()
    conferir('e o menu do horario na agenda tambem',
             'slot-declaracao' in modais, True)

finally:
    # A trilha nao se apaga -- nem por roteiro. `check_imutabilidade` cobra
    # exatamente isso, e o usuario da aplicacao nao tem permissao de DELETE
    # na tabela. As linhas ficam, apontando para agendamentos que ja nao
    # existem, que e o comportamento correto de um registro imutavel.
    EncounterDiagnosis.objects.filter(id__in=criados['diagnosticos']).delete()
    Encounter.objects.filter(id__in=criados['encontros']).delete()
    Appointment.objects.filter(id__in=criados['agendamentos']).delete()
    n = Patient.objects.filter(id__in=criados['pacientes']).delete()[0]
    print(f'\n  limpeza: {n} objeto(s) de paciente e '
          f"{len(criados['agendamentos'])} agendamento(s) removidos")

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o papel afirma presenca e horario, nao carrega diagnostico,')
print('    nega ser atestado, e ver nao emite.')
