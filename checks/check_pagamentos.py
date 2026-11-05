"""Pagamento: apagar o lançado errado, várias formas num registro, e a lista de formas.

Pedidos de 2026-11-05, do uso real: um pagamento de R$ 12.000,00 digitado
no lugar de R$ 1.200,00 não tinha como sair — o saldo ficava em
R$ -10.800,00 e o caixa do dia mentia; o paciente que paga parte no
crédito e parte no débito exigia dois envios; e a forma era texto livre
("Credito", "other").

O que este roteiro cobra:

- **apagar** o pagamento refaz o saldo e o status, entra na trilha com
  valor e forma (sem nome), e é recusado em cobrança fora do financeiro,
  em pagamento com estorno ligado, por `GET`, e com id de outra cobrança;
- **várias formas** num envio viram vários pagamentos, e uma linha
  inválida não deixa as outras gravadas (tudo ou nada); linha sem valor é
  ignorada;
- a **lista**: o código vira o rótulo gravado, "Outro" com texto vira
  "Outro: …", sem texto fica "Outro", texto grande demais é recusado, o
  `other` antigo aparece como "Outro" na tela e na exportação, e o texto
  livre de antes continua aceito.

Tudo dentro de uma transação desfeita no fim.
"""
import datetime
import uuid
from decimal import Decimal

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from clinical.models import Encounter, EncounterKind, EncounterStatus
from finance.adjustments import apply_adjustment
from finance.exports import cash_rows
from finance.forms import PaymentForm
from finance.models import AdjustmentType, Payment, Receivable, ReceivableStatus
from finance.payments import MAX_OUTRO, balance, record_payment
from patients.models import Patient, PatientStatus, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


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

        def cobranca(valor='1200.00'):
            paciente = Patient.objects.create(
                tenant=tenant, full_name=f'ROTEIRO PAGAMENTO {uuid.uuid4().hex[:6]}',
                birth_date=datetime.date(1980, 1, 1),
                registration_stage=RegistrationStage.COMPLETE, status=PatientStatus.ACTIVE,
            )
            encontro = Encounter.objects.create(
                tenant=tenant, patient=paciente, physician_membership=medico,
                occurred_at=timezone.now(), kind=EncounterKind.FREE_TEXT,
                status=EncounterStatus.FINALIZED, finalized_at=timezone.now(),
                finalized_by=medico,
            )
            return Receivable.objects.create(
                tenant=tenant, patient=paciente, encounter=encontro,
                fee_snapshot={'payment_category': 'private'},
                expected_amount=Decimal(valor), charged_amount=Decimal(valor),
                due_date=hoje, competence_date=hoje, status=ReceivableStatus.PENDING,
            )

        cli = Client()
        cli.force_login(secretaria.user)
        sessao = cli.session
        sessao['tenant_id'] = str(tenant.id)
        sessao.save()

        print('\n1. A lista de formas vira o rótulo gravado')
        for dados, esperado in [
            ({'amount': '10', 'method': 'credito_vista'}, 'Crédito à vista'),
            ({'amount': '10', 'method': 'credito_parcelado'}, 'Crédito parcelado'),
            ({'amount': '10', 'method': 'debito'}, 'Débito'),
            ({'amount': '10', 'method': 'pix'}, 'PIX'),
            ({'amount': '10', 'method': 'dinheiro'}, 'Dinheiro'),
            ({'amount': '10', 'method': 'outro'}, 'Outro'),
            ({'amount': '10', 'method': 'outro', 'method_other': '  Boleto  '}, 'Outro: Boleto'),
            ({'amount': '10', 'method': 'Credito'}, 'Credito'),
            ({'amount': '10'}, 'other'),
        ]:
            f = PaymentForm(dados)
            conferir(f'{dados.get("method")!s:18} {dados.get("method_other", "")!s:10}',
                     f.cleaned_data['method'] if f.is_valid() else 'RECUSADO', esperado)
        grande = PaymentForm({'amount': '10', 'method': 'outro', 'method_other': 'x' * (MAX_OUTRO + 1)})
        conferir('"Outro" maior que a coluna é recusado', grande.is_valid(), False)
        cabe = PaymentForm({'amount': '10', 'method': 'outro', 'method_other': 'x' * MAX_OUTRO})
        conferir('  e no limite cabe nos 40 da coluna',
                 cabe.is_valid() and len(cabe.cleaned_data['method']) <= 40, True)

        print('\n2. Várias formas num registro: tudo ou nada')
        rec = cobranca('1480.00')
        url = reverse('finance:record-payment', args=[rec.id])
        cli.post(url, {
            'amount': '1000,00', 'method': 'credito_vista',
            'p1-amount': '480,00', 'p1-method': 'debito',
            'p2-amount': '', 'p2-method': 'pix',
        })
        rec.refresh_from_db()
        metodos = sorted(rec.payments.values_list('method', flat=True))
        conferir('duas linhas viram dois pagamentos', metodos, ['Crédito à vista', 'Débito'])
        conferir('  e a cobrança fica paga', rec.status, ReceivableStatus.PAID)
        rec2 = cobranca()
        cli.post(reverse('finance:record-payment', args=[rec2.id]), {
            'amount': '600', 'method': 'pix', 'p1-amount': 'abc', 'p1-method': 'dinheiro',
        })
        conferir('linha inválida não deixa a outra gravada', rec2.payments.count(), 0)
        cli.post(reverse('finance:record-payment', args=[rec2.id]), {'amount': '600', 'method': 'pix'})
        conferir('o envio de uma linha continua igual', rec2.payments.count(), 1)

        print('\n3. Apagar o pagamento digitado errado')
        rec3 = cobranca()
        errado = record_payment(rec3, Decimal('12000.00'), 'Credito', secretaria.user_id)
        record_payment(rec3, Decimal('1200.00'), 'other', secretaria.user_id)
        rec3.refresh_from_db()
        conferir('com o erro, o saldo fica negativo', balance(rec3), Decimal('-12000.00'))
        apagar = reverse('finance:delete-payment', args=[rec3.id, errado.id])
        pagina = cli.get(reverse('finance:receivable-detail', args=[rec3.id])).content.decode()
        conferir('a tela oferece apagar, com a pergunta', f'action="{apagar}"' in pagina
                 and 'Apagar o pagamento de R$ 12000,00' in pagina, True)
        conferir('o "other" antigo aparece como Outro', '>Outro</span>' in pagina, True)
        conferir('a tela traz a lista de formas', 'Crédito parcelado' in pagina
                 and 'data-nd-metodo-outro' in pagina and 'p3-amount' in pagina, True)
        conferir('sem GET', cli.get(apagar).status_code, 405)
        outra = cobranca()
        conferir('id de outra cobrança dá 404',
                 cli.post(reverse('finance:delete-payment', args=[outra.id, errado.id])).status_code, 404)
        cli.post(apagar)
        rec3.refresh_from_db()
        conferir('o pagamento sai', Payment.objects.filter(id=errado.id).exists(), False)
        conferir('  o saldo é refeito', balance(rec3), Decimal('0.00'))
        conferir('  e o status também', rec3.status, ReceivableStatus.PAID)
        evento = AuditEvent.objects.filter(action='finance.payment_deleted', object_id=str(errado.id)).first()
        conferir('a trilha guarda valor e forma',
                 evento is not None and evento.integrity_metadata.get('amount') == '12000.00'
                 and evento.integrity_metadata.get('method') == 'Credito', True)
        conferir('  sem o nome do paciente',
                 evento is not None and rec3.patient.full_name not in str(evento.integrity_metadata), True)

        print('\n4. Quando não se apaga')
        com_estorno = record_payment(rec3, Decimal('50.00'), 'PIX', secretaria.user_id)
        apply_adjustment(rec3, AdjustmentType.REFUND, Decimal('50.00'), 'devolvido', secretaria, payment=com_estorno)
        cli.post(reverse('finance:delete-payment', args=[rec3.id, com_estorno.id]))
        conferir('pagamento com estorno ligado fica', Payment.objects.filter(id=com_estorno.id).exists(), True)
        restante = rec3.payments.exclude(id=com_estorno.id).first()
        Receivable.objects.filter(id=rec3.id).update(doctor_share_paid_at=timezone.now())
        cli.post(reverse('finance:delete-payment', args=[rec3.id, restante.id]))
        conferir('cobrança com repasse feito não perde pagamento',
                 Payment.objects.filter(id=restante.id).exists(), True)
        pagina = cli.get(reverse('finance:receivable-detail', args=[rec3.id])).content.decode()
        conferir('  e a tela nem oferece', 'finance/' in pagina and '/excluir/' not in pagina, True)

        print('\n5. O caixa e a exportação leem o rótulo')
        linhas = list(cash_rows(rec3.payments.all()))
        conferir('"other" sai como Outro na exportação',
                 sorted(l['method'] for l in linhas), ['Outro', 'PIX'])
        raise _Desfazer
except _Desfazer:
    pass

if falhas:
    print(f'\n{len(falhas)} falha(s):')
    for f in falhas:
        print('FALHA: ' + f)
    raise SystemExit(1)
print('\nTudo certo.')
