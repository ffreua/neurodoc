"""Particular ou convênio é escolha do atendimento, não da ficha (1.30).

Até a 1.29 a cobrança do check-in pegava "a primeira cobertura vigente que
o banco devolvesse", sem ordem, e ignorava que a consulta fosse
particular: paciente com convênio na ficha que pagava do bolso era cobrado
pela tabela do convênio. Tenta quebrar:

- sem escolha (todo horário antigo): a regra de sempre — cobertura vigente
  é convênio —, agora com a cobertura ativa da ficha primeiro;
- particular escolhido com convênio vigente na ficha: preço particular;
- convênio escolhido: o plano **daquela** cobertura, não o de outra;
- o mesmo paciente, particular num dia e convênio no outro;
- escolher depois do check-in: recusado, nada muda;
- cobertura de outro paciente, ou inexistente: recusada; e o banco recusa
  convênio sem cobertura e cobertura sem convênio;
- a escolha não mexe em `row_version` (os lembretes continuam valendo);
- o painel em JSON só traz convênio, plano, final da carteira e vigência;
  outra clínica recebe 404;
- trilha da troca.

Tudo numa transação desfeita no fim.

    docker compose exec -T app python manage.py shell < checks/check_forma_de_cobranca.py
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as dj_settings
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from audit.models import AuditEvent
from finance.models import FeeSchedule, PaymentCategory, Receivable
from patients.models import HealthPlan, Insurer, Patient, PatientCoverage
from scheduling import services
from scheduling.models import Appointment, AppointmentType, BillingMode
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


clinica = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=clinica.id).order_by('created_at').first()
medico = (Membership.objects.filter(tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR])
          .select_related('user').first())
paciente = Patient.objects.filter(tenant=clinica).order_by('created_at').first()
paciente2 = Patient.objects.filter(tenant=clinica).exclude(id=getattr(paciente, 'id', None)).order_by('created_at').first()
if None in (medico, paciente, paciente2, outra):
    print('  (demonstração incompleta; roteiro pulado)')
    raise SystemExit(0)

contexto = AccessContext(
    user_id=medico.user_id, tenant_id=clinica.id, membership_id=medico.id,
    permissions=frozenset(medico.roles), request_id=uuid.uuid4(),
)
TIPO = AppointmentType.OTHER
ontem = timezone.localdate() - timedelta(days=1)


def marcar(pac, dias):
    inicio = timezone.now().replace(microsecond=0) + timedelta(days=dias, hours=3)
    return services.reserve_appointment(
        contexto, pac, medico, inicio, inicio + timedelta(minutes=30), TIPO,
        is_overbook=True, override_reason='roteiro forma de cobrança', override_by=medico,
    )


def cobranca(appt):
    services.check_in(appt, medico.user_id)
    return Receivable.objects.filter(appointment=appt).first()


try:
    with transaction.atomic():
        operadora = Insurer.objects.create(tenant=clinica, name='OPERADORA ROTEIRO COBRANCA', ans_registration='368253')
        plano_a = HealthPlan.objects.create(tenant=clinica, insurer=operadora, name='PLANO A ROTEIRO')
        plano_b = HealthPlan.objects.create(tenant=clinica, insurer=operadora, name='PLANO B ROTEIRO')
        cob_a = PatientCoverage.objects.create(tenant=clinica, patient=paciente, plan=plano_a,
                                               member_number='000123456', starts_on=date(2020, 1, 1))
        cob_b = PatientCoverage.objects.create(tenant=clinica, patient=paciente, plan=plano_b,
                                               member_number='000987654', starts_on=date(2021, 1, 1))
        cob_outro = PatientCoverage.objects.create(tenant=clinica, patient=paciente2, plan=plano_a,
                                                   member_number='111', starts_on=date(2020, 1, 1))
        Patient.objects.filter(id=paciente.id).update(active_coverage=cob_a)
        paciente.refresh_from_db()
        for categoria, plano, valor in ((PaymentCategory.PRIVATE, None, '300.00'),
                                        (PaymentCategory.INSURANCE, plano_a, '120.00'),
                                        (PaymentCategory.INSURANCE, plano_b, '95.00')):
            FeeSchedule.objects.create(
                tenant=clinica, physician=medico, plan=plano, payment_category=categoria,
                appointment_type=TIPO, gross_amount=Decimal(valor),
                doctor_share_amount=Decimal('0.00'), effective_from=ontem,
            )

        print('=== 1. Sem escolha: a regra de sempre, determinística ===')
        a = marcar(paciente, 1)
        conferir('nasce "não informado"', a.billing_mode == '' and a.coverage_id is None)
        r = cobranca(a)
        conferir('cobertura vigente → convênio', r and r.fee_snapshot.get('payment_category') == 'insurance',
                 str(r and r.fee_snapshot))
        conferir('a ativa da ficha primeiro (plano A, R$ 120)', r and r.charged_amount == Decimal('120.00'),
                 str(r and r.charged_amount))

        print('=== 2. Particular escolhido, com convênio vigente na ficha ===')
        b = marcar(paciente, 2)
        versao = b.row_version
        services.set_billing_mode(contexto, b, BillingMode.PRIVATE, None, medico.user_id)
        b.refresh_from_db()
        conferir('gravado particular', b.billing_mode == 'private' and b.coverage_id is None)
        conferir('row_version intacto (lembretes valem)', b.row_version == versao)
        r = cobranca(b)
        conferir('cobrado como particular (R$ 300)',
                 r and r.fee_snapshot.get('payment_category') == 'private' and r.charged_amount == Decimal('300.00'),
                 str(r and (r.fee_snapshot, r.charged_amount)))

        print('=== 3. Convênio escolhido: o plano daquela cobertura ===')
        c = marcar(paciente, 3)
        services.set_billing_mode(contexto, c, BillingMode.INSURANCE, cob_b.id, medico.user_id)
        r = cobranca(c)
        conferir('plano B, e não o A da ficha (R$ 95)', r and r.charged_amount == Decimal('95.00'),
                 str(r and r.charged_amount))

        print('=== 4. Depois da chegada, não muda ===')
        try:
            services.set_billing_mode(contexto, c, BillingMode.PRIVATE, None, medico.user_id)
            conferir('recusado depois do check-in', False, 'aceitou')
        except services.SchedulingError:
            c.refresh_from_db()
            conferir('recusado depois do check-in', c.billing_mode == 'insurance')

        print('=== 5. Cobertura que não é deste paciente ===')
        d = marcar(paciente, 4)
        for rotulo, cobertura in (('de outro paciente', cob_outro.id), ('inexistente', uuid.uuid4()),
                                  ('sem cobertura', None)):
            try:
                services.set_billing_mode(contexto, d, BillingMode.INSURANCE, cobertura, medico.user_id)
                conferir(f'convênio {rotulo}: recusado', False, 'aceitou')
            except services.SchedulingError:
                conferir(f'convênio {rotulo}: recusado', True)
        for rotulo, campos in (('convênio sem cobertura', {'billing_mode': 'insurance', 'coverage': None}),
                               ('cobertura sem convênio', {'billing_mode': 'private', 'coverage': cob_a})):
            try:
                with transaction.atomic():
                    Appointment.objects.filter(id=d.id).update(**campos)
                conferir(f'o banco recusa {rotulo}', False, 'gravou')
            except IntegrityError:
                conferir(f'o banco recusa {rotulo}', True)

        print('=== 6. O painel da agenda ===')
        cli = Client(SERVER_NAME='localhost')
        cli.force_login(medico.user)
        s = cli.session
        s['tenant_id'] = str(clinica.id)
        s.save()
        resp = cli.get(f'/app/scheduling/{d.id}/cobranca/')
        dados = resp.json() if resp.status_code == 200 else {}
        ids = {o['id'] for o in dados.get('opcoes', [])}
        conferir('lista as coberturas deste paciente', {str(cob_a.id), str(cob_b.id)} <= ids, str(dados))
        conferir('e não as de outro', str(cob_outro.id) not in ids)
        conferir('mostra só o final da carteira', all('000123456' not in o['rotulo'] for o in dados.get('opcoes', [])))
        chaves = set().union(*(o.keys() for o in dados.get('opcoes', [{}])))
        conferir('nada além de convênio, vigência e marca da ficha',
                 chaves <= {'id', 'rotulo', 'vigente', 'ativa_na_ficha'}, str(chaves))
        resp = cli.post(f'/app/scheduling/{d.id}/cobranca/', {'billing': f'coverage:{cob_b.id}'})
        d.refresh_from_db()
        conferir('POST grava pela tela', resp.status_code == 302 and d.coverage_id == cob_b.id)
        resp = cli.post(f'/app/scheduling/{d.id}/cobranca/', {'billing': 'coverage:nao-e-uuid'})
        d.refresh_from_db()
        conferir('lixo no POST não grava nem quebra', resp.status_code == 302 and d.coverage_id == cob_b.id)
        conferir('trilha da troca', AuditEvent.objects.filter(
            action='scheduling.appointment_billing_changed', object_id=d.id).exists())

        estranho = Membership.objects.filter(tenant=outra, status=MembershipStatus.ACTIVE).select_related('user').first()
        if estranho:
            c2 = Client(SERVER_NAME='localhost')
            c2.force_login(estranho.user)
            s2 = c2.session
            s2['tenant_id'] = str(outra.id)
            s2.save()
            conferir('outra clínica: 404 no painel', c2.get(f'/app/scheduling/{d.id}/cobranca/').status_code == 404)
            c2.post(f'/app/scheduling/{d.id}/cobranca/', {'billing': 'private'})
            d.refresh_from_db()
            conferir('e o POST não grava', d.billing_mode == 'insurance')

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Tudo certo.')
