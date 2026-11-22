"""Indicadores por tipo de atendimento, e a naturalidade no Dashboard (2026-11-22).

O que este roteiro tenta quebrar:

1. **Consultas atendidas por tipo**, pelo tipo marcado na agenda e com
   check-in: o seguimento e o retorno contados à parte, a falta e o
   cancelado fora, o futuro fora, o horário de outra clínica fora.
2. **A taxa de falta** conta o check-in como atendido (contava só
   "Concluído", e a clínica fecha pelo check-in: saía "sem dados").
3. **A receita por tipo**: primeira consulta, seguimento, retorno e cada
   procedimento numa linha, pelo código TUSS; a consulta sem horário pelo
   tipo da regra de honorário, e sem nenhum dos dois em "sem tipo"; o
   cancelado e o fora do período fora; **o total fecha com a receita por
   competência** da mesma tela; sem procedimento, nenhuma linha de
   procedimento.
4. **A tela de Indicadores** com os cartões de seguimento e retorno e o
   quadro da receita.
5. **A naturalidade**: Brasil só com cidade ou UF de nascimento, o resto
   "Não informado"; país estrangeiro com a célula pequena; a UF de
   nascimento dos brasileiros; e os CSV.

Tudo numa clínica criada aqui, dentro de uma transação desfeita.
"""
import datetime
import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.test import Client
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from catalogs.models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode
from finance.models import ChargeKind, Receivable, ReceivableStatus
from patients.models import Patient, PatientStatus, RegistrationStage
from reporting import operations, painel, patients as rp
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.permissions import capabilities_for

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe and not ok else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


class Desfazer(Exception):
    pass


hoje = timezone.localdate()
inicio = hoje.replace(day=1)


def nova_clinica(nome):
    return Tenant.objects.create(legal_name=nome, slug=f'ind-{uuid.uuid4().hex[:10]}',
                                 cpf=str(uuid.uuid4().int)[:11])


def nova_pessoa(rotulo, tenant, papeis):
    user = User.objects.create_user(email=f'{rotulo}-{uuid.uuid4().hex[:6]}@example.com',
                                    password='Roteiro#2026-ind', first_name=rotulo.capitalize())
    user.email_verified_at = timezone.now()
    user.save(update_fields=['email_verified_at'])
    TOTPDevice.objects.create(user=user, confirmed=True, name='roteiro')
    vinculo = Membership.objects.create(tenant=tenant, user=user, roles=papeis,
                                        status=MembershipStatus.ACTIVE, activated_at=timezone.now())
    return user, vinculo


def paciente(tenant, nome, **extra):
    return Patient.objects.create(
        tenant=tenant, full_name=nome, birth_date_unknown_reason='Roteiro de verificação.',
        status=PatientStatus.ACTIVE, registration_stage=RegistrationStage.COMPLETE, **extra,
    )


_slot = [0]


def horario(tenant, pac, vinculo, tipo, status, dia):
    _slot[0] += 1
    ini = timezone.make_aware(datetime.datetime.combine(dia, datetime.time(7, 0))) + datetime.timedelta(minutes=31 * _slot[0])
    fim = ini + datetime.timedelta(minutes=30)
    return Appointment.objects.create(
        tenant=tenant, patient=pac, physician_membership=vinculo, starts_at=ini, ends_at=fim,
        occupied_range=(ini, fim), status=status, type=tipo,
    )


def cobranca(tenant, pac, valor, *, appointment=None, kind=ChargeKind.CONSULTATION, snapshot=None,
             status=ReceivableStatus.PAID, competencia=None, encounter=None):
    return Receivable.objects.create(
        tenant=tenant, patient=pac, appointment=appointment, encounter=encounter, charge_kind=kind,
        fee_snapshot=snapshot or {'payment_category': 'private'},
        expected_amount=Decimal(valor), charged_amount=Decimal(valor),
        due_date=competencia or hoje, competence_date=competencia or hoje, status=status,
    )


def escopo_de(vinculo, **params):
    ctx = AccessContext(
        user_id=vinculo.user_id, tenant_id=vinculo.tenant_id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles), request_id=uuid.uuid4(),
        capabilities=capabilities_for(vinculo.roles, clinically_enabled=True, ai_contracted=False),
    )
    return painel.resolver_escopo(ctx, params)


def linhas(dados):
    return {l['rotulo']: l['n'] for l in dados}


try:
    with transaction.atomic():
        A = nova_clinica('Clínica dos Indicadores')
        B = nova_clinica('Outra Clínica dos Indicadores')
        dona, v_dona = nova_pessoa('donaind', A, [Role.OWNER, Role.DOCTOR])
        dono_b, v_b = nova_pessoa('donobind', B, [Role.OWNER, Role.DOCTOR])
        p1 = paciente(A, 'PACIENTE IND 1')
        p2 = paciente(A, 'PACIENTE IND 2')
        pb = paciente(B, 'PACIENTE IND B')
        dia = hoje

        print('=== 1. consultas atendidas por tipo ===')
        h_prim = horario(A, p1, v_dona, AppointmentType.FIRST_VISIT, AppointmentStatus.CHECKED_IN, dia)
        h_seg1 = horario(A, p1, v_dona, AppointmentType.FOLLOW_UP, AppointmentStatus.COMPLETED, dia)
        h_seg2 = horario(A, p2, v_dona, AppointmentType.FOLLOW_UP, AppointmentStatus.IN_PROGRESS, dia)
        h_seg3 = horario(A, p2, v_dona, AppointmentType.FOLLOW_UP, AppointmentStatus.CHECKED_IN, dia)
        h_ret = horario(A, p2, v_dona, AppointmentType.RETURN_VISIT, AppointmentStatus.CHECKED_IN, dia)
        h_proc = horario(A, p1, v_dona, AppointmentType.PROCEDURE, AppointmentStatus.CHECKED_IN, dia)
        horario(A, p1, v_dona, AppointmentType.FOLLOW_UP, AppointmentStatus.NO_SHOW, dia)
        horario(A, p1, v_dona, AppointmentType.FOLLOW_UP, AppointmentStatus.CANCELLED, dia)
        horario(A, p2, v_dona, AppointmentType.RETURN_VISIT, AppointmentStatus.SCHEDULED, dia + datetime.timedelta(days=40))
        horario(B, pb, v_b, AppointmentType.FOLLOW_UP, AppointmentStatus.CHECKED_IN, dia)
        tipos = operations.atendidos_por_tipo(A, inicio, hoje)
        conferir('primeira consulta 1', tipos['first_visit'] == 1, str(tipos))
        conferir('seguimento 3 (check-in, em atendimento e concluído); falta e cancelado fora',
                 tipos['follow_up'] == 3, str(tipos))
        conferir('retorno 1 (o marcado daqui a 40 dias fora)', tipos['return_visit'] == 1, str(tipos))
        conferir('procedimento 1', tipos['procedure'] == 1, str(tipos))
        conferir('o horário da outra clínica não entra', sum(tipos.values()) == 6, str(tipos))

        print('=== 2. a taxa de falta conta o check-in ===')
        falta = rp.no_show_rate(A, inicio, hoje)
        conferir('n = 6 atendidos + 1 falta', falta['n'] == 7 and falta['no_show'] == 1 and falta['completed'] == 6,
                 str(falta))
        conferir('taxa 1/7', falta['rate'] is not None and abs(float(falta['rate']) - 1 / 7) < 1e-9, str(falta['rate']))

        # O horário que terminou sem check-in é falta (regra das estatísticas
        # da agenda): ocupou a agenda e o paciente não apareceu.
        meia_noite = timezone.make_aware(datetime.datetime.combine(hoje, datetime.time(0, 0)))
        vencido = Appointment.objects.create(
            tenant=A, patient=p2, physician_membership=v_dona, starts_at=meia_noite,
            ends_at=meia_noite + datetime.timedelta(minutes=1),
            occupied_range=(meia_noite, meia_noite + datetime.timedelta(minutes=1)),
            status=AppointmentStatus.SCHEDULED, type=AppointmentType.FOLLOW_UP,
        )
        falta2 = rp.no_show_rate(A, inicio, hoje)
        conferir('o horário vencido sem check-in conta como falta', falta2['n'] == 8 and falta2['no_show'] == 2
                 and falta2['sem_checkin'] == 1 and falta2['registradas'] == 1, str(falta2))
        from scheduling import estatisticas
        _t, totais, _m = estatisticas._por_tipo(A.id, inicio, hoje)
        conferir('a mesma conta das estatísticas do mês', totais['faltas'] == falta2['no_show']
                 and totais['atendidos'] == falta2['completed'], f'{totais} x {falta2}')
        conferir('o percentual pronto, com vírgula', falta2['percentual'] == '25,0%', str(falta2['percentual']))
        vencido.delete()
        zero = rp.no_show_rate(B, inicio, hoje)
        conferir('taxa zero sai 0,0%, e não "sem dados"', zero['n'] == 1 and zero['percentual'] == '0,0%', str(zero))

        print('=== 3. a receita por tipo ===')
        rel = CatalogRelease.objects.create(system=CatalogSystem.TUSS, version=f'ind-{uuid.uuid4().hex[:6]}',
                                            status=CatalogReleaseStatus.SUPERSEDED,
                                            imported_at=timezone.now())
        eeg = ProcedureCode.objects.create(release=rel, code='40103030', description='ELETROENCEFALOGRAMA EM VIGÍLIA',
                                           starts_on=date(2010, 1, 1), active=True)
        enmg = ProcedureCode.objects.create(release=rel, code='40103650', description='ELETRONEUROMIOGRAFIA',
                                            starts_on=date(2010, 1, 1), active=True)
        cobranca(A, p1, '500.00', appointment=h_prim)
        cobranca(A, p1, '400.00', appointment=h_seg1)
        cobranca(A, p2, '400.00', appointment=h_seg2, status=ReceivableStatus.PENDING)
        cobranca(A, p2, '350.00', appointment=h_seg3)
        cobranca(A, p2, '0.00', appointment=h_ret)
        cobranca(A, p1, '300.00', appointment=h_proc, kind=ChargeKind.PROCEDURE,
                 snapshot={'payment_category': 'private', 'procedure_id': str(eeg.id)})
        cobranca(A, p2, '600.00', kind=ChargeKind.PROCEDURE, appointment=horario(
            A, p2, v_dona, AppointmentType.PROCEDURE, AppointmentStatus.CHECKED_IN, dia),
            snapshot={'payment_category': 'private', 'procedure_id': str(enmg.id)})
        cobranca(A, p2, '600.00', kind=ChargeKind.PROCEDURE, appointment=horario(
            A, p2, v_dona, AppointmentType.PROCEDURE, AppointmentStatus.CHECKED_IN, dia),
            snapshot={'payment_category': 'private', 'procedure_id': str(enmg.id)})
        # Sem horário: a regra de honorário diz o tipo.
        from clinical.models import Encounter, EncounterKind, EncounterStatus
        enc = Encounter.objects.create(tenant=A, patient=p1, physician_membership=v_dona,
                                       occurred_at=timezone.now(), status=EncounterStatus.IN_PROGRESS,
                                       kind=EncounterKind.FREE_TEXT)
        cobranca(A, p1, '450.00', encounter=enc,
                 snapshot={'payment_category': 'private', 'appointment_type': 'follow_up'})
        enc2 = Encounter.objects.create(tenant=A, patient=p2, physician_membership=v_dona,
                                        occurred_at=timezone.now(), status=EncounterStatus.IN_PROGRESS,
                                        kind=EncounterKind.FREE_TEXT)
        cobranca(A, p2, '200.00', encounter=enc2)
        # Fora: cancelada, competência de outro mês, outra clínica.
        cobranca(A, p1, '999.00', appointment=horario(A, p1, v_dona, AppointmentType.FIRST_VISIT,
                                                    AppointmentStatus.CHECKED_IN, dia),
                 status=ReceivableStatus.CANCELLED)
        cobranca(A, p1, '888.00', appointment=horario(A, p1, v_dona, AppointmentType.FIRST_VISIT,
                                                    AppointmentStatus.CHECKED_IN, dia),
                 competencia=inicio - datetime.timedelta(days=5))
        cobranca(B, pb, '777.00', appointment=horario(B, pb, v_b, AppointmentType.FIRST_VISIT,
                                                    AppointmentStatus.CHECKED_IN, dia))

        r = operations.receita_por_tipo(A, inicio, hoje)
        por = {l['rotulo']: l for l in r['linhas']}
        conferir('primeira consulta: 1, R$ 500', por.get('Primeira consulta', {}).get('n') == 1
                 and por['Primeira consulta']['valor'] == Decimal('500.00'), str(por.get('Primeira consulta')))
        conferir('seguimento: 4 (3 da agenda + 1 pela regra de honorário), R$ 1.600',
                 por.get('Seguimento', {}).get('n') == 4 and por['Seguimento']['valor'] == Decimal('1600.00'),
                 str(por.get('Seguimento')))
        conferir('valor médio do seguimento R$ 400', por.get('Seguimento', {}).get('medio') == Decimal('400.00'))
        conferir('retorno de valor zero conta', por.get('Retorno', {}).get('n') == 1, str(por.get('Retorno')))
        conferir('consulta sem horário nem tipo: "sem tipo"',
                 por.get('Consulta sem tipo na agenda', {}).get('valor') == Decimal('200.00'), str(list(por)))
        conferir('EEG numa linha com o código TUSS', any(k.startswith('40103030') and v['n'] == 1 for k, v in por.items()),
                 str(list(por)))
        enmg_linha = next((v for k, v in por.items() if k.startswith('40103650')), None)
        conferir('ENMG: 2, R$ 1.200', enmg_linha is not None and enmg_linha['n'] == 2
                 and enmg_linha['valor'] == Decimal('1200.00'), str(enmg_linha))
        ordem = [l['rotulo'] for l in r['linhas']]
        conferir('ordem: consultas na ordem da agenda, depois procedimentos do que mais rendeu',
                 ordem.index('Primeira consulta') < ordem.index('Seguimento') < ordem.index('Retorno')
                 and ordem.index(next(k for k in ordem if k.startswith('40103650')))
                 < ordem.index(next(k for k in ordem if k.startswith('40103030'))), str(ordem))
        total_tela = operations.revenue_by_competence(A, inicio, hoje)
        conferir('o total fecha com a receita por competência da tela', r['total'] == total_tela,
                 f'{r["total"]} x {total_tela}')
        conferir('cancelada, outro mês e outra clínica fora', r['total'] == Decimal('3800.00'), str(r['total']))
        conferir('as porcentagens somam 100', abs(sum(float(l['pct']) for l in r['linhas']) - 100) < 0.01)
        r_b = operations.receita_por_tipo(B, inicio, hoje)
        conferir('clínica sem procedimento não tem linha de procedimento',
                 all(l['grupo'] == 'consulta' for l in r_b['linhas']), str(r_b['linhas']))

        print('=== 4. a tela de Indicadores ===')
        c = Client()
        c.force_login(dona)
        s = c.session
        s['tenant_id'] = str(A.id)
        s.save()
        resp = c.get(f'/app/reporting/?start={inicio.isoformat()}&end={hoje.isoformat()}')
        html = resp.content.decode()
        conferir('a tela abre', resp.status_code == 200, str(resp.status_code))
        conferir('cartão Seguimentos com 3', '>Seguimentos</h3>' in html and 'counter">3<' in html)
        conferir('cartão Retornos pelo tipo da agenda', '>Retornos</h3>' in html)
        conferir('o quadro da receita por tipo, com o total', 'Receita por tipo de atendimento' in html
                 and 'R$ 3800,00' in html and '40103650' in html)
        conferir('a taxa de falta com o número (10 atendidos e 1 falta até aqui)',
                 '1 falta(s) em 11 consulta(s)' in html and '9,1%' in html and 'sem check-in=0' in html)
        conferir('nada da outra clínica', '777' not in html)

        print('=== 5. a naturalidade no Dashboard ===')
        for i in range(6):
            paciente(A, f'NAT BR {i}', birth_country='BR', birth_state='SP', birth_city='São Paulo')
        paciente(A, 'NAT BR MG', birth_country='BR', birth_state='MG')
        for i in range(5):
            paciente(A, f'NAT PT {i}', birth_country='PT', birth_city='Lisboa')
        paciente(A, 'NAT LB 1', birth_country='LB')
        paciente(A, 'NAT LB 2', birth_country='LB')
        e = escopo_de(v_dona, periodo='12m')
        nat = linhas(painel.naturalidade(e))
        conferir('Brasil só com cidade ou UF de nascimento (7)', nat.get('Brasil') == 7, str(nat))
        conferir('o "BR" padrão sem nada vai para "Não informado" (os 2 pacientes do início)',
                 nat.get('Não informado') == 2, str(nat))
        conferir('Portugal com 5 aparece', nat.get('Portugal') == 5, str(nat))
        conferir('Líbano com 2 vai para "Outros países"', 'Líbano' not in nat
                 and any(k.startswith('Outros países') and v == 2 for k, v in nat.items()), str(nat))
        uf_nasc = linhas(painel.naturalidade_uf(e))
        conferir('UF de nascimento: SP 6, MG 1, sem estrangeiro', uf_nasc == {'SP': 6, 'MG': 1}, str(uf_nasc))
        _, csv_nat = painel.linhas_csv(e, 'naturalidade')
        conferir('o CSV da naturalidade soma a carteira', sum(l['pacientes'] for l in csv_nat) == 16, str(csv_nat))
        resp = c.get('/app/reporting/dashboard/?periodo=12m')
        html = resp.content.decode()
        conferir('o Dashboard mostra os dois cartões', 'Naturalidade (país de nascimento)' in html
                 and 'UF de nascimento' in html and 'baixar=naturalidade_uf' in html, str(resp.status_code))
        resp = c.get('/app/reporting/dashboard/?periodo=12m&baixar=naturalidade')
        conferir('o CSV baixa', resp.status_code == 200 and 'Portugal' in resp.content.decode('utf-8-sig'))

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'{len(falhas)} FALHA(S):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('check_indicadores_por_tipo: tudo certo.')
