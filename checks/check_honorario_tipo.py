"""Honorario por tipo de atendimento: primeira consulta, seguimento, retorno.

A agenda sempre distinguiu os tres -- tem ate duracao propria para cada um
-- e o honorario nao tinha como cobrar valores diferentes. Quem tentava
amarrava o preco a um codigo TUSS, que e a tabela da ANS: la "consulta em
consultorio" e um codigo so, e o caminho automatico da cobranca nem sequer
passava procedimento para o motor de preco. A regra ficava cadastrada na
tela, parecendo valer, e nunca era consultada.

O que este roteiro cobra, e que e onde da errado:

1. dentro da mesma combinacao de medico/plano/procedimento, a regra do
   tipo vence a que vale para qualquer tipo;
2. **o tipo e a dimensao menos significativa** -- plano vence tipo. Poe-lo
   no topo faria "primeira consulta" ganhar de "plano X" e a clinica
   cobraria o particular de um paciente com convenio;
3. atendimento sem agendamento (encaixe) cai na regra geral, como sempre;
4. uma instalacao que nunca declarou tipo nenhum se comporta exatamente
   como antes;
5. a trava de sobreposicao trata o tipo como parte da identidade da regra:
   "primeira consulta" e "retorno" na mesma vigencia nao se sobrepoem;
6. o `<select>` em branco grava NULL, e nao string vazia -- com `''` a
   coluna deixa de ser nula, a regra nao casa com tipo nenhum nem com a
   busca por nulo, e nunca cobra ninguem.
"""
from datetime import date, timedelta
from decimal import Decimal

from scheduling.models import AppointmentType
from tenancy.models import Membership, Tenant
from patients.models import HealthPlan
from finance.models import FeeSchedule, PaymentCategory
from finance.pricing import (
    NoApplicableFeeSchedule, OverlappingFeeSchedule, create_fee_schedule, resolve_price,
)

falhas = []
ONTEM = timezone.localdate() - timedelta(days=1)
HOJE = timezone.localdate()


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:52} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(tenant=tenant, roles__contains=['doctor']).first()
plano = HealthPlan.objects.filter(tenant=tenant, active=True).first()

# A tabela da clinica de demonstracao ja tem regras; elas atrapalhariam a
# leitura do que este roteiro cria. Guardamos e devolvemos no fim.
preexistentes = list(FeeSchedule.objects.filter(tenant=tenant).values_list('id', flat=True))
FeeSchedule.objects.filter(id__in=preexistentes).update(effective_to=ONTEM - timedelta(days=1))

criadas = []


def regra(valor, **kwargs):
    r = create_fee_schedule(
        tenant, payment_category=kwargs.pop('categoria', PaymentCategory.PRIVATE),
        gross_amount=Decimal(valor), doctor_share_amount=Decimal(valor),
        effective_from=ONTEM, **kwargs,
    )
    criadas.append(r.id)
    return r


def preco(**kwargs):
    try:
        return resolve_price(
            tenant, kwargs.pop('medico', None), kwargs.pop('categoria', PaymentCategory.PRIVATE),
            HOJE, **kwargs,
        ).gross_amount
    except NoApplicableFeeSchedule:
        return 'NENHUMA'


try:
    print('\n1. O tipo desempata dentro da mesma combinacao')
    regra('1480.00', appointment_type=AppointmentType.FIRST_VISIT)
    regra('1200.00', appointment_type=AppointmentType.FOLLOW_UP)
    regra('0.00', appointment_type=AppointmentType.RETURN_VISIT)
    regra('900.00')  # qualquer tipo
    conferir('primeira consulta', preco(appointment_type='first_visit'), Decimal('1480.00'))
    conferir('seguimento', preco(appointment_type='follow_up'), Decimal('1200.00'))
    conferir('retorno (zero e um preco, nao ausencia)', preco(appointment_type='return_visit'), Decimal('0.00'))

    print('\n2. Sem agendamento (encaixe) cai na regra de qualquer tipo')
    conferir('tipo nulo', preco(appointment_type=None), Decimal('900.00'))
    conferir('tipo sem regra propria (Outro)', preco(appointment_type='other'), Decimal('900.00'))

    print('\n3. O tipo NAO vence uma combinacao mais especifica')
    if plano is not None:
        regra('300.00', categoria=PaymentCategory.INSURANCE, plan=plano)
        conferir(
            'paciente com convenio em primeira consulta paga o do convenio',
            preco(categoria=PaymentCategory.INSURANCE, plan=plano, appointment_type='first_visit'),
            Decimal('300.00'),
        )
    else:
        print('  (sem plano ativo na clinica de demonstracao; item pulado)')

    if medico is not None:
        regra('2000.00', physician=medico)
        conferir(
            'regra do medico vence a regra de tipo da clinica',
            preco(medico=medico, appointment_type='first_visit'), Decimal('2000.00'),
        )

    print('\n4. A trava de sobreposicao trata o tipo como identidade')
    try:
        regra('999.00', appointment_type=AppointmentType.FIRST_VISIT)
        falhas.append('duas regras de "primeira consulta" na mesma vigencia foram aceitas')
        print('  FALHA  duas regras do MESMO tipo coexistiram')
    except OverlappingFeeSchedule:
        print('  ok     duas regras do mesmo tipo na mesma vigencia sao recusadas')
    try:
        r = regra('777.00', appointment_type=AppointmentType.PROCEDURE)
        print('  ok     tipo diferente na mesma vigencia e aceito (nao se sobrepoem)')
    except OverlappingFeeSchedule:
        falhas.append('tipos diferentes foram tratados como a mesma regra')
        print('  FALHA  tipo diferente foi recusado como sobreposicao')

    print('\n5. O <select> em branco grava NULL, nao string vazia')
    from finance.fee_forms import FeeScheduleForm
    f = FeeScheduleForm(tenant_id=tenant.id, context=None)
    f.cleaned_data = {'appointment_type': ''}
    conferir('vazio vira None', f.appointment_type_value(), None)
    f.cleaned_data = {'appointment_type': 'follow_up'}
    conferir('valor escolhido passa inteiro', f.appointment_type_value(), 'follow_up')
    vazias = FeeSchedule.objects.filter(tenant=tenant, appointment_type='').count()
    conferir('nenhuma regra gravada com string vazia', vazias, 0)

    print('\n6. O retrato guardado no recebivel registra o tipo')
    from finance.pricing import snapshot_from_fee_schedule
    alvo = FeeSchedule.objects.get(tenant=tenant, gross_amount=Decimal('1480.00'))
    conferir('snapshot traz o tipo', snapshot_from_fee_schedule(alvo)['appointment_type'], 'first_visit')

finally:
    print('\n  limpando o que este roteiro criou')
    n = FeeSchedule.objects.filter(id__in=criadas).delete()[0]
    FeeSchedule.objects.filter(id__in=preexistentes).update(effective_to=None)
    print(f'  {n} regra(s) removida(s); {len(preexistentes)} pre-existente(s) restaurada(s)')

if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('\nOK: o honorario segue o tipo de atendimento, sem vencer plano nem medico,')
print('    e o encaixe sem agendamento continua caindo na regra geral.')
