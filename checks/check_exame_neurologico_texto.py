"""O texto livre do exame neurológico é um registro clínico completo.

Exercita a gravação parcial usada pelas abas, a releitura nas telas e a
impressão digital da finalização. O defeito que este roteiro pega é uma
caixa visível que não salva, que some do resumo ou que pode mudar sem mudar
o hash do atendimento.
"""
from django.conf import settings as dj_settings
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from clinical.models import Encounter, EncounterKind
from patients.models import Patient
from tenancy.models import Membership, Tenant

tenant = Tenant.objects.get(slug='demo-clinica-a')
user = User.objects.get(email='doctor-a@demo.neurodoc.local')
membership = Membership.objects.get(user=user, tenant=tenant)
patient = Patient.objects.filter(tenant=tenant, status='active').first()
if patient is None:
    raise SystemExit('FALHA: a clínica de demonstração está sem paciente ativo')

client = Client()
client.force_login(user)
session = client.session
session['tenant_id'] = str(tenant.id)
session.save()

encounter = Encounter.objects.create(
    tenant=tenant,
    patient=patient,
    physician_membership=membership,
    occurred_at=timezone.now(),
    kind=EncounterKind.STRUCTURED,
    chief_complaint='Teste do campo livre do exame',
    plan_text='Observar.',
)
failures = []
text = 'Vigil, orientado; pupilas isocóricas e fotorreagentes.'

try:
    before_hash = encounter.compute_content_hash()
    response = client.post(
        f'/app/clinical/{encounter.id}/autosave/',
        {'row_version': str(encounter.row_version), 'neurological_exam_text': text},
        HTTP_X_REQUESTED_WITH='XMLHttpRequest',
    )
    encounter.refresh_from_db()
    saved = getattr(encounter, 'neurological_exam_text', '')
    print('autosave:', response.status_code, 'salvou:', saved == text)
    if response.status_code != 200 or saved != text:
        failures.append('o autosave não gravou o exame neurológico em texto livre')

    detail = client.get(f'/app/clinical/{encounter.id}/').content.decode()
    print('campo na tela:', 'Exame neurológico em texto livre' in detail)
    if 'Exame neurológico em texto livre' not in detail or text not in detail:
        failures.append('a tela do atendimento não mostra o campo salvo')

    summary = client.get(f'/app/clinical/{encounter.id}/resumo/').content.decode()
    print('texto no resumo:', text in summary)
    if text not in summary:
        failures.append('o resumo do caso omite o exame neurológico em texto livre')

    after_hash = encounter.compute_content_hash()
    print('campo participa do hash:', before_hash != after_hash)
    if before_hash == after_hash:
        failures.append('o texto livre do exame não participa do hash clínico')
finally:
    Encounter.objects.filter(id=encounter.id).delete()

print('---')
if failures:
    for failure in failures:
        print('FALHA:', failure)
    raise SystemExit(1)
print('OK: texto livre do exame salva, reaparece e integra o registro clínico.')
