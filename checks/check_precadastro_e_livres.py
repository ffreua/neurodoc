"""Nascimento no pré-cadastro, e horários livres traduzidos em consultas por tipo.

Tenta quebrar. As perguntas são:

- o pré-cadastro com data de nascimento grava a data (e a idade aparece), e
  sem data continua com o motivo "a completar na recepção"?
- as estatísticas do mês devolvem "quantas consultas de cada tipo cabem" no
  tempo livre, pela duração de cada tipo, por divisão inteira?
"""
from django.conf import settings as dj_settings

dj_settings.SECURE_SSL_REDIRECT = False

import datetime

from django.utils import timezone

from patients.models import Patient, PatientContact, RegistrationStage
from scheduling import services
from scheduling.estatisticas import do_mes
import uuid
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.permissions import capabilities_for

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


clinica = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(
    tenant=clinica, roles__contains=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
).first()
sec = Membership.objects.filter(
    tenant=clinica, roles__contains=[Role.SECRETARY], status=MembershipStatus.ACTIVE,
).first() or medico

ctx = AccessContext(
    user_id=sec.user_id, tenant_id=clinica.id, membership_id=sec.id,
    permissions=frozenset(sec.roles), request_id=uuid.uuid4(),
    capabilities=capabilities_for(sec.roles, clinically_enabled=True, ai_contracted=True),
)

criados = []
try:
    print('=== 1. pre-cadastro com data de nascimento ===')
    nasc = datetime.date(1960, 3, 15)
    p = services.quick_register_patient(ctx, 'PACIENTE COM NASCIMENTO', '11988887777',
                                        birth_date=nasc)
    criados.append(p.id)
    p.refresh_from_db()
    confere(p.birth_date == nasc, 'a data de nascimento foi gravada')
    confere(p.birth_date_unknown_reason == '', 'sem o motivo de "a completar" quando ha data')
    confere(p.registration_stage == RegistrationStage.PRELIMINARY, 'continua pre-cadastro')

    print('=== 2. pre-cadastro sem data mantem o motivo ===')
    p2 = services.quick_register_patient(ctx, 'PACIENTE SEM NASCIMENTO', '11977776666')
    criados.append(p2.id)
    p2.refresh_from_db()
    confere(p2.birth_date is None, 'sem data de nascimento')
    confere('recep' in p2.birth_date_unknown_reason.lower(), 'o motivo "a completar na recepcao" fica')

    print('=== 3. horarios livres por tipo nas estatisticas ===')
    hoje = timezone.localdate()
    medicos = list(Membership.objects.filter(
        tenant=clinica, roles__contains=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
    ))
    dados = do_mes(clinica.id, hoje.year, hoje.month, medicos)
    confere('cabem_por_tipo' in dados, 'as estatisticas trazem "cabem_por_tipo"')
    cabem = dados.get('cabem_por_tipo', [])
    confere(isinstance(cabem, list), 'e uma lista de {tipo, rotulo, cabem}')
    confere(all(set(item) == {'tipo', 'rotulo', 'cabem'} and item['cabem'] > 0 for item in cabem),
            f'cada item tem tipo/rotulo/cabem > 0 ({cabem})')
    # Coerência: quem tem horário livre deve oferecer pelo menos um tipo; quem
    # não tem, nenhum. (Não cravamos o número, que depende da grade de demonstração.)
    confere((dados['ocupacao']['livres'] > 0) == (len(cabem) > 0),
            f'ha tipo oferecido exatamente quando ha horario livre (livres={dados["ocupacao"]["livres"]}, tipos={len(cabem)})')

finally:
    PatientContact.objects.filter(patient_id__in=criados).delete()
    Patient.objects.filter(id__in=criados).delete()

print()
print('check_precadastro_e_livres: ' + ('tudo certo.' if not falhas else f'{len(falhas)} FALHA(S): ' + '; '.join(falhas)))
import sys
sys.exit(1 if falhas else 0)
