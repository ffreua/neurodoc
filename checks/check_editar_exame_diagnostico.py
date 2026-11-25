"""Alterar exame e hipótese já incluídos, sem excluir e cadastrar de novo.

Tenta quebrar. As perguntas são:

- o lápis aparece no exame e na hipótese, e abre o formulário já preenchido?
- mudar a **certeza** da hipótese (suspeita -> confirmada) muda só a certeza,
  e a trilha guarda quais campos mudaram, nunca o conteúdo?
- mudar a data do exame muda só a data; enviar sem mudança não deixa rastro?
- hipótese em branco é recusada sem gravar?
- atendimento finalizado não se altera (correção por adendo)?
- a secretária, outra clínica e o item de outro atendimento recebem 404?
"""
import datetime

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import (
    DiagnosisCertainty, Encounter, EncounterDiagnosis, EncounterStatus,
    ExamResult,
)
from patients.models import Patient, PatientStatus, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


clinica = Tenant.objects.get(slug='demo-clinica-a')
clinica_b = Tenant.objects.get(slug='demo-clinica-b')
medico = Membership.objects.filter(
    tenant=clinica, roles__contains=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
).first()
email_medico = medico.user.email
sec = Membership.objects.filter(
    tenant=clinica, roles__contains=[Role.SECRETARY], status=MembershipStatus.ACTIVE,
).first()
medico_b = Membership.objects.filter(
    tenant=clinica_b, roles__contains=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
).first()


def logado(email, tenant):
    c = Client()
    c.force_login(User.objects.get(email=email))
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


paciente = Patient.objects.create(
    tenant=clinica, full_name='PACIENTE DO ROTEIRO DE EDICAO',
    registration_stage=RegistrationStage.COMPLETE, status=PatientStatus.ACTIVE,
    birth_date_unknown_reason='Roteiro de verificacao.',
)

try:
    enc = Encounter.objects.create(
        tenant=clinica, patient=paciente, physician_membership=medico, occurred_at=timezone.now(),
    )
    outro = Encounter.objects.create(
        tenant=clinica, patient=paciente, physician_membership=medico, occurred_at=timezone.now(),
    )
    exame = ExamResult.objects.create(
        tenant=clinica, encounter=enc, patient=paciente, name='RM de cranio',
        performed_on=datetime.date(2025, 5, 16), report_text='sem alteracoes',
    )
    exame_alheio = ExamResult.objects.create(
        tenant=clinica, encounter=outro, patient=paciente, name='EEG',
    )
    diag = EncounterDiagnosis.objects.create(
        tenant=clinica, encounter=enc, code_snapshot='I64',
        description_snapshot='AVC nao especificado', certainty=DiagnosisCertainty.SUSPECTED,
        rank=1, physician_note='a definir',
    )
    doc = logado(email_medico, clinica)

    print('=== 1. o lapis e os formularios preenchidos ===')
    corpo = doc.get(f'/app/clinical/{enc.id}/').content.decode()
    confere(f'id="examres-edit-{exame.id}"' in corpo, 'o exame tem o formulario de edicao')
    confere(f'id="diag-edit-{diag.id}"' in corpo, 'a hipotese tem o formulario de edicao')
    confere(f'/app/clinical/{enc.id}/exames/{exame.id}/editar/' in corpo, 'a rota de editar exame esta na tela')
    confere(f'/app/clinical/{enc.id}/diagnoses/{diag.id}/editar/' in corpo, 'a rota de editar hipotese esta na tela')

    print('=== 2. mudar a certeza muda so a certeza ===')
    url_d = f'/app/clinical/{enc.id}/diagnoses/{diag.id}/editar/'
    pd = f'diag-{diag.id}'
    base_d = {f'{pd}-certainty': DiagnosisCertainty.CONFIRMED, f'{pd}-rank': 1,
              f'{pd}-code_snapshot': 'I64', f'{pd}-description_snapshot': 'AVC nao especificado',
              f'{pd}-physician_note': 'a definir'}
    r = doc.post(url_d, base_d)
    diag.refresh_from_db()
    confere(r.status_code == 302, f'volta com 302 ({r.status_code})')
    confere(diag.certainty == DiagnosisCertainty.CONFIRMED, 'a certeza virou confirmada')
    confere(diag.description_snapshot == 'AVC nao especificado' and diag.physician_note == 'a definir',
            'descricao e nota ficaram')
    ev = AuditEvent.objects.filter(action='clinical.diagnosis_updated', object_id=enc.id).order_by('-created_at').first()
    confere(ev is not None and ev.integrity_metadata.get('campos') == ['certainty'],
            f'a trilha guarda so o campo certainty ({ev.integrity_metadata if ev else None})')
    confere(ev is not None and 'confirmed' not in str(ev.integrity_metadata) and 'AVC' not in str(ev.integrity_metadata),
            'a trilha nao guarda o valor nem o conteudo clinico')

    print('=== 3. enviar sem mudar nada nao deixa rastro ===')
    n_antes = AuditEvent.objects.filter(action='clinical.diagnosis_updated', object_id=enc.id).count()
    doc.post(url_d, base_d)
    n_depois = AuditEvent.objects.filter(action='clinical.diagnosis_updated', object_id=enc.id).count()
    confere(n_antes == n_depois, 'sem mudanca, nada de novo na trilha')

    print('=== 4. hipotese em branco e recusada ===')
    doc.post(url_d, {**base_d, f'{pd}-description_snapshot': '   '})
    diag.refresh_from_db()
    confere(diag.description_snapshot == 'AVC nao especificado', 'a descricao em branco foi recusada')

    print('=== 5. mudar a data do exame muda so a data ===')
    url_e = f'/app/clinical/{enc.id}/exames/{exame.id}/editar/'
    pe = f'examres-{exame.id}'
    base_e = {f'{pe}-category': exame.category, f'{pe}-name': exame.name,
              f'{pe}-performed_on': '2025-06-01', f'{pe}-service_name': exame.service_name,
              f'{pe}-report_text': exame.report_text, f'{pe}-conclusion': exame.conclusion}
    doc.post(url_e, base_e)
    exame.refresh_from_db()
    confere(exame.performed_on == datetime.date(2025, 6, 1), 'a data do exame mudou')
    confere(exame.report_text == 'sem alteracoes', 'o laudo ficou')
    eve = AuditEvent.objects.filter(action='clinical.exam_result_updated', object_id=enc.id).order_by('-created_at').first()
    confere(eve is not None and eve.integrity_metadata.get('campos') == ['performed_on'],
            f'a trilha do exame guarda so performed_on ({eve.integrity_metadata if eve else None})')

    print('=== 6. finalizado nao se altera ===')
    enc.status = EncounterStatus.FINALIZED
    enc.save(update_fields=['status'])
    doc.post(url_d, {**base_d, f'{pd}-certainty': DiagnosisCertainty.SUSPECTED})
    diag.refresh_from_db()
    confere(diag.certainty == DiagnosisCertainty.CONFIRMED, 'hipotese de atendimento finalizado nao muda')
    doc.post(url_e, {**base_e, f'{pe}-name': 'MUDOU'})
    exame.refresh_from_db()
    confere(exame.name == 'RM de cranio', 'exame de atendimento finalizado nao muda')
    enc.status = EncounterStatus.DRAFT
    enc.save(update_fields=['status'])

    print('=== 7. secretaria, outra clinica e item alheio ===')
    if sec:
        cs = logado(sec.user.email, clinica)
        confere(cs.post(url_d, base_d).status_code == 404, 'a secretaria nao edita hipotese')
    if medico_b:
        cb = logado(medico_b.user.email, clinica_b)
        confere(cb.post(url_d, base_d).status_code == 404, 'outra clinica recebe 404')
    url_alheio = f'/app/clinical/{enc.id}/exames/{exame_alheio.id}/editar/'
    confere(doc.post(url_alheio, base_e).status_code == 404, 'exame de outro atendimento recebe 404')

finally:
    EncounterDiagnosis.objects.filter(encounter=enc).delete()
    ExamResult.objects.filter(patient=paciente).delete()
    Encounter.objects.filter(patient=paciente).delete()
    paciente.delete()

print()
print('check_editar_exame_diagnostico: ' + ('tudo certo.' if not falhas else f'{len(falhas)} FALHA(S): ' + '; '.join(falhas)))
import sys
sys.exit(1 if falhas else 0)
