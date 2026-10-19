"""Alterar uma medicacao do atendimento, sem excluir e cadastrar de novo.

Tenta quebrar. As perguntas sao:

- o lapis aparece ao lado da lixeira, e abre o formulario ja preenchido?
- com varias linhas, cada formulario tem os seus campos (sem `id_dose`
  repetido) e o autocomplete preenche a dose **daquela** linha?
- mudar a dose muda so a dose -- "em uso desde", indicacao e observacao
  ficam --, e a trilha guarda quais campos mudaram e nao os valores?
- enviar sem mudar nada nao grava nem deixa rastro?
- nome em branco e recusado sem gravar?
- atendimento finalizado nao se altera (a correcao e por adendo)?
- a secretaria, outra clinica e a medicacao de outro atendimento recebem
  404?
"""
import datetime

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP; sem isto o SSL_REDIRECT de producao
# devolve 301 para tudo e o roteiro mede o redirecionamento.
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import Encounter, EncounterStatus, Medication, MedicationStatus
from patients.models import Patient, PatientStatus, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


clinica = Tenant.objects.get(slug='demo-clinica-a')
clinica_b = Tenant.objects.get(slug='demo-clinica-b')
medico = Membership.objects.get(
    tenant=clinica, user__email='doctor-a@demo.neurodoc.local', status=MembershipStatus.ACTIVE,
)


def logado(email, tenant):
    c = Client()
    c.force_login(User.objects.get(email=email))
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


paciente = Patient.objects.create(
    tenant=clinica, full_name='PACIENTE DO ROTEIRO DE MEDICACAO',
    registration_stage=RegistrationStage.COMPLETE, status=PatientStatus.ACTIVE,
    birth_date_unknown_reason='Roteiro de verificacao.',
)
encontros = []


def atendimento():
    e = Encounter.objects.create(
        tenant=clinica, patient=paciente, physician_membership=medico, occurred_at=timezone.now(),
    )
    encontros.append(e.id)
    return e


try:
    enc = atendimento()
    outro = atendimento()
    rosu = Medication.objects.create(
        tenant=clinica, encounter=enc, name='ROSUVASTATINA CÁLCICA', dose='20 mg',
        frequency='1x/dia', indication='dislipidemia', started_on=datetime.date(2025, 2, 25),
        notes='Boa tolerancia.', status=MedicationStatus.IN_USE,
    )
    zider = Medication.objects.create(
        tenant=clinica, encounter=enc, name='ZIDER', dose='10 mg', frequency='1cp VO x/dia',
    )
    alheia = Medication.objects.create(tenant=clinica, encounter=outro, name='ALHEIA', dose='1 mg')
    prefixo = f'med{rosu.id.hex}'
    url = f'/app/clinical/{enc.id}/medicacoes/{rosu.id}/editar/'
    doc = logado('doctor-a@demo.neurodoc.local', clinica)

    def dados(**mudanca):
        base = {
            'name': rosu.name, 'dose': rosu.dose, 'route': rosu.route, 'frequency': rosu.frequency,
            'started_on': rosu.started_on.isoformat() if rosu.started_on else '',
            'indication': rosu.indication, 'status': rosu.status, 'prescriber': rosu.prescriber,
            'notes': rosu.notes,
        }
        base.update(mudanca)
        return {f'{prefixo}-{k}': v for k, v in base.items()}

    print('=== 1. o lapis e o formulario preenchido ===')
    corpo = doc.get(f'/app/clinical/{enc.id}/').content.decode()
    confere(f'aria-label="Alterar {rosu.name}"' in corpo, 'o botao de alterar esta na linha')
    confere(f'data-bs-target="#med-edit-{rosu.id}"' in corpo and f'id="med-edit-{rosu.id}"' in corpo,
            'o botao abre o formulario daquela linha')
    confere(url in corpo, 'o formulario envia para a rota de editar')
    confere(f'name="{prefixo}-dose"' in corpo and 'value="20 mg"' in corpo,
            'o formulario vem preenchido com a dose atual')
    confere(corpo.count('id="id_dose"') <= 1, f'id_dose nao se repete ({corpo.count("id=\"id_dose\"")})')
    # O Django escapa a aspa simples do atributo; o navegador a desfaz.
    confere(f"[name=&#x27;{prefixo}-dose&#x27;]" in corpo,
            'o autocomplete aponta para a dose da propria linha')
    confere('class="collapse"' in corpo, 'o formulario nasce fechado')

    print('=== 2. mudar a dose muda so a dose ===')
    antes_trilha = AuditEvent.objects.filter(action='clinical.medication_updated', object_id=enc.id).count()
    r = doc.post(url, dados(dose='40 mg'))
    confere(r.status_code == 302 and r['Location'].endswith('#tab-medicacoes'),
            f'volta para a aba de medicacoes ({r.status_code})')
    rosu.refresh_from_db()
    confere(rosu.dose == '40 mg', f'a dose mudou ({rosu.dose})')
    confere(rosu.started_on == datetime.date(2025, 2, 25) and rosu.indication == 'dislipidemia'
            and rosu.notes == 'Boa tolerancia.' and rosu.frequency == '1x/dia',
            'em uso desde, indicacao, posologia e observacao ficaram')
    confere(Medication.objects.filter(encounter=enc).count() == 2, 'nenhuma linha nova nem removida')
    ev = AuditEvent.objects.filter(action='clinical.medication_updated', object_id=enc.id).order_by('-created_at').first()
    confere(ev is not None and ev.integrity_metadata.get('campos') == ['dose'],
            f'a trilha diz que mudou a dose ({ev.integrity_metadata if ev else None})')
    confere(ev is not None and '40 mg' not in str(ev.integrity_metadata) and '20 mg' not in str(ev.integrity_metadata),
            'e nao guarda os valores')
    zider.refresh_from_db()
    confere(zider.dose == '10 mg', 'a outra medicacao nao foi tocada')

    print('=== 3. sem mudanca, sem rastro ===')
    n = AuditEvent.objects.filter(action='clinical.medication_updated', object_id=enc.id).count()
    r = doc.post(url, dados())
    confere(r.status_code == 302, f'envio sem mudanca volta ({r.status_code})')
    confere(AuditEvent.objects.filter(action='clinical.medication_updated', object_id=enc.id).count() == n,
            'nao deixou rastro')

    print('=== 4. recusas ===')
    r = doc.post(url, dados(name=''))
    rosu.refresh_from_db()
    confere(r.status_code == 302 and rosu.name == 'ROSUVASTATINA CÁLCICA', 'nome em branco recusado sem gravar')
    r = doc.post(f'/app/clinical/{enc.id}/medicacoes/{alheia.id}/editar/', dados(dose='99 mg'))
    alheia.refresh_from_db()
    confere(r.status_code == 404 and alheia.dose == '1 mg',
            f'medicacao de outro atendimento pela rota deste -> 404 ({r.status_code})')
    sec = logado('secretary-a@demo.neurodoc.local', clinica)
    r = sec.post(url, dados(dose='99 mg'))
    rosu.refresh_from_db()
    confere(r.status_code == 404 and rosu.dose == '40 mg', f'secretaria -> 404 ({r.status_code})')
    doc_b = logado('doctor-a@demo.neurodoc.local', clinica_b)
    r = doc_b.post(url, dados(dose='99 mg'))
    rosu.refresh_from_db()
    confere(r.status_code == 404 and rosu.dose == '40 mg', f'outra clinica -> 404 ({r.status_code})')
    r = doc.get(url)
    confere(r.status_code == 405, f'GET nao altera ({r.status_code})')

    print('=== 5. finalizado nao se altera ===')
    Encounter.objects.filter(id=enc.id).update(
        status=EncounterStatus.FINALIZED, finalized_at=timezone.now(),
    )
    r = doc.post(url, dados(dose='80 mg'))
    rosu.refresh_from_db()
    confere(rosu.dose == '40 mg', f'atendimento finalizado manteve a dose ({rosu.dose})')
    corpo = doc.get(f'/app/clinical/{enc.id}/').content.decode()
    confere(f'aria-label="Alterar {rosu.name}"' not in corpo and url not in corpo,
            'finalizado nao mostra o lapis nem o formulario')
finally:
    Medication.objects.filter(encounter_id__in=encontros).delete()
    Encounter.objects.filter(id__in=encontros).delete()
    Patient.objects.filter(id=paciente.id).delete()

if falhas:
    print(f'\nFALHA: {len(falhas)} problema(s):')
    for f in falhas:
        print(f'  - {f}')
    raise SystemExit(1)
print('\nOK: a medicacao se altera no lugar, so o que mudou, e so enquanto o atendimento esta aberto.')
