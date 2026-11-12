"""Corridas, tetos e travas: o terceiro lote da auditoria de 2026-11-11.

Financeiro, agenda, agenda de exames e equipe. Cada seção tenta o que o
código aceitava e não devia:

- **financeiro**: a cobrança de valor zero (o retorno sem custo) presa em
  "Em aberto"; a "Baixa" que não mudava o saldo; desconto e estorno sem
  teto; pagamento em cobrança cancelada; o caixa que não mostrava estorno;
- **agenda**: marcar no passado; remarcar mantendo "Confirmado"; o
  pré-cadastro que sobrava quando a marcação falhava;
- **exame**: "Realizar" de novo recriando a cobrança cancelada;
- **equipe**: o único responsável tirando de si o papel.

Tudo dentro de transação desfeita.

    docker compose exec -T app python manage.py shell < checks/check_lote_corridas.py
"""
import datetime
import uuid
from decimal import Decimal

from django.conf import settings as dj_settings
from django.db import transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from clinical.models import Encounter, EncounterKind, EncounterStatus
from finance.adjustments import apply_adjustment
from finance.models import AdjustmentType, Receivable, ReceivableStatus
from finance.payments import balance, record_payment
from finance.receivables import situacao_inicial
from finance.selectors import caixa
from patients.models import Patient, PatientStatus, RegistrationStage
from scheduling import services as agenda
from scheduling.availability import fits
from scheduling.models import Appointment, AppointmentStatus
from tenancy.models import Membership, MembershipStatus, Role, Tenant

# O cliente de teste fala `testserver` e HTTP.
dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe != '' else ''))
    if not ok:
        falhas.append(nome)


def recusa(funcao, *a, **k):
    try:
        funcao(*a, **k)
    except ValueError as exc:
        return str(exc)
    return None


class _Desfazer(Exception):
    pass


try:
    with transaction.atomic():
        tenant = Tenant.objects.get(slug='demo-clinica-a')
        medico = Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
        ).order_by('user__email').first()
        secretaria = Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['secretary'],
        ).select_related('user').order_by('user__email').first()
        hoje = timezone.localdate()

        def paciente():
            return Patient.objects.create(
                tenant=tenant, full_name=f'ROTEIRO LOTE {uuid.uuid4().hex[:6]}',
                birth_date=datetime.date(1980, 1, 1),
                registration_stage=RegistrationStage.COMPLETE, status=PatientStatus.ACTIVE,
            )

        def cobranca(valor):
            p = paciente()
            encontro = Encounter.objects.create(
                tenant=tenant, patient=p, physician_membership=medico,
                occurred_at=timezone.now(), kind=EncounterKind.FREE_TEXT,
                status=EncounterStatus.FINALIZED, finalized_at=timezone.now(), finalized_by=medico,
            )
            return Receivable.objects.create(
                tenant=tenant, patient=p, encounter=encontro,
                fee_snapshot={'payment_category': 'private', 'doctor_share_amount': '0.00'},
                expected_amount=Decimal(valor), charged_amount=Decimal(valor),
                due_date=hoje, competence_date=hoje, status=situacao_inicial(Decimal(valor)),
            )

        print('=== 1. Financeiro: o retorno sem custo não fica pendurado ===')
        zero = cobranca('0.00')
        conferir('a cobrança de R$ 0,00 nasce quitada', zero.status == ReceivableStatus.PAID, zero.status)
        conferir('e a de valor nasce em aberto', cobranca('150.00').status == ReceivableStatus.PENDING)
        from finance.lifecycle import mark_doctor_share_paid

        mark_doctor_share_paid(zero, medico)
        zero.refresh_from_db()
        conferir('o repasse da cobrança zero é marcado', zero.doctor_share_paid_at is not None)

        print('=== 2. Financeiro: a baixa muda o saldo ===')
        rec = cobranca('200.00')
        record_payment(rec, Decimal('150.00'), 'pix', secretaria.user_id)
        apply_adjustment(rec, AdjustmentType.WRITEOFF, Decimal('50.00'), 'perdido', secretaria)
        rec.refresh_from_db()
        conferir('o saldo vai a zero', balance(rec) == Decimal('0.00'), balance(rec))
        conferir('e a cobrança fica quitada', rec.status == ReceivableStatus.PAID, rec.status)

        print('=== 3. Financeiro: tetos ===')
        rec = cobranca('200.00')
        conferir('desconto maior que o cobrado é recusado',
                 recusa(apply_adjustment, rec, AdjustmentType.DISCOUNT, Decimal('2000.00'), 'x', secretaria))
        rec.refresh_from_db()
        conferir('  e o valor cobrado não mudou', rec.charged_amount == Decimal('200.00'), rec.charged_amount)
        pago = record_payment(rec, Decimal('100.00'), 'pix', secretaria.user_id)
        conferir('estorno maior que o recebido é recusado',
                 recusa(apply_adjustment, rec, AdjustmentType.REFUND, Decimal('150.00'), 'x', secretaria, payment=pago))
        conferir('baixa maior que o saldo é recusada',
                 recusa(apply_adjustment, rec, AdjustmentType.WRITEOFF, Decimal('150.00'), 'x', secretaria))
        conferir('o desconto que cabe passa',
                 recusa(apply_adjustment, rec, AdjustmentType.DISCOUNT, Decimal('20.00'), 'x', secretaria) is None)

        print('=== 4. Financeiro: cobrança cancelada não recebe ===')
        rec = cobranca('80.00')
        Receivable.objects.filter(id=rec.id).update(status=ReceivableStatus.CANCELLED)
        conferir('o pagamento é recusado', recusa(record_payment, rec, Decimal('80.00'), 'pix', secretaria.user_id))

        print('=== 5. Financeiro: o estorno aparece no caixa ===')
        rec = cobranca('300.00')
        p = record_payment(rec, Decimal('300.00'), 'pix', secretaria.user_id)
        apply_adjustment(rec, AdjustmentType.REFUND, Decimal('300.00'), 'devolvido', secretaria, payment=p)
        do_paciente = [m for m in caixa(tenant, hoje, hoje) if m['paciente'] == rec.patient.full_name]
        soma = sum(m['valor'] for m in do_paciente)
        conferir('entrada e saída no caixa do dia', len(do_paciente) == 2, len(do_paciente))
        conferir('  e o caixa do paciente fecha em zero', soma == Decimal('0.00'), soma)

        print('=== 6. Agenda: não marca no passado ===')
        agora = timezone.localtime()
        ontem = (agora - datetime.timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        ok, motivo = fits(medico.id, ontem, ontem + datetime.timedelta(minutes=30))
        conferir('o horário de ontem é recusado', not ok, motivo)

        print('=== 7. Agenda: remarcar volta "Confirmado" a "Agendado" ===')
        inicio = (agora + datetime.timedelta(days=9)).replace(hour=2, minute=0, second=0, microsecond=0)
        fim = inicio + datetime.timedelta(minutes=30)
        consulta = Appointment.objects.create(
            tenant=tenant, patient=paciente(), physician_membership=medico,
            starts_at=inicio, ends_at=fim, occupied_range=DateTimeTZRange(inicio, fim),
            status=AppointmentStatus.CONFIRMED,
        )
        from tenancy.context import AccessContext

        ctx = AccessContext(user_id=medico.user_id, tenant_id=tenant.id, membership_id=medico.id,
                            permissions=frozenset(medico.roles), request_id=uuid.uuid4())
        novo = inicio + datetime.timedelta(days=1)
        remarcada = agenda.reschedule_appointment(ctx, consulta, novo, novo + datetime.timedelta(minutes=30),
                                                  medico.user_id)
        conferir('a remarcada volta a "agendado"', remarcada.status == AppointmentStatus.SCHEDULED,
                 remarcada.status)

        print('=== 8. Agenda: pré-cadastro não sobra quando a marcação falha ===')
        cli = Client()
        cli.force_login(secretaria.user)
        sessao = cli.session
        sessao['tenant_id'] = str(tenant.id)
        sessao.save()
        # Fora da grade (madrugada, daqui a cinco dias): a reserva é recusada
        # depois do pré-cadastro, dentro da mesma transação.
        madrugada = (agora + datetime.timedelta(days=5)).replace(hour=3, minute=0, second=0, microsecond=0)

        def marcar(nome, **extra):
            return cli.post(reverse('scheduling:quick-book', args=[medico.id]), {
                'starts_at': madrugada.strftime('%Y-%m-%d %H:%M'), 'appointment_type': 'return_visit',
                'new_name': nome, 'new_phone': '11999990000', 'date': madrugada.date().isoformat(),
                **extra,
            })

        nome = f'ROTEIRO SOBRA {uuid.uuid4().hex[:6].upper()}'
        marcar(nome)
        conferir('a marcação recusada não deixa o paciente pré-cadastrado',
                 not Patient.objects.filter(tenant=tenant, full_name=nome).exists())
        controle = f'ROTEIRO CONTROLE {uuid.uuid4().hex[:6].upper()}'
        marcar(controle, is_overbook='on', override_reason='roteiro')
        conferir('  e o mesmo envio como encaixe cria (o caminho é o mesmo)',
                 Patient.objects.filter(tenant=tenant, full_name=controle).exists())

        print('=== 9. Equipe: o único responsável não tira o próprio papel ===')
        dono = Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.OWNER],
        ).select_related('user').first()
        Membership.objects.filter(tenant=tenant, roles__contains=[Role.OWNER]).exclude(id=dono.id).update(
            status=MembershipStatus.SUSPENDED,
        )
        cli_dono = Client()
        cli_dono.force_login(dono.user)
        sessao = cli_dono.session
        sessao['tenant_id'] = str(tenant.id)
        sessao.save()
        r = cli_dono.post(reverse('tenancy:membership-roles', args=[dono.id]), {'roles': [Role.DOCTOR]},
                          follow=True)
        dono.refresh_from_db()
        conferir('o papel de responsável fica', Role.OWNER in dono.roles, dono.roles)
        conferir('  e a tela diz por quê', 'pelo menos um responsável ativo' in r.content.decode(),
                 r.status_code)

        raise _Desfazer
except _Desfazer:
    pass

print()
if falhas:
    print(f'FALHA: {len(falhas)} item(ns): ' + '; '.join(falhas))
    raise SystemExit(1)
print('OK: tetos, travas e o retorno sem custo no financeiro.')
