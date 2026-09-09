"""Matriz de acesso conferida contra o PRD secao 4.

Cada linha declara o que se espera de cada perfil. Falha quando o sistema
concede algo que a matriz nega, ou nega algo que ela concede.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from clinical.models import Encounter
from documents.models import Attachment, AttachmentClassification
from patients.models import Patient
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
OK, NO = 'permitido', 'negado'

doctor_a = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant__slug=TENANT)
doctor_b = Membership.objects.get(user__email='doctor-b@demo.neurodoc.local', tenant__slug=TENANT)
patient = Patient.objects.filter(tenant__slug=TENANT).first()
encounter = Encounter.objects.filter(tenant__slug=TENANT).first()
clinical_att = Attachment.objects.filter(
    tenant__slug=TENANT, classification=AttachmentClassification.CLINICAL, deleted_at=None,
).first()

# (rotulo, url, {perfil: esperado})
CASES = [
    ('agenda da semana', '/app/scheduling/',
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': OK, 'manager-a': OK}),
    ('balcao do dia', '/app/scheduling/balcao/',
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': OK, 'manager-a': OK}),
    ('cadastro de pacientes', '/app/patients/',
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': OK, 'manager-a': OK}),
    ('PRONTUARIO (linha do tempo)', f'/app/clinical/patients/{patient.id}/timeline/' if patient else None,
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': NO, 'manager-a': NO}),
    ('PRONTUARIO (atendimento)', f'/app/clinical/{encounter.id}/' if encounter else None,
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': NO, 'manager-a': NO}),
    ('documento medico', f'/app/documents/encounters/{encounter.id}/medical/' if encounter else None,
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': NO, 'manager-a': NO}),
    ('certificado de assinatura', '/app/documents/signing/credentials/',
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': NO, 'manager-a': NO}),
    ('ANEXO CLINICO (download)',
     f'/app/documents/{clinical_att.id}/download/' if clinical_att else None,
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': NO, 'manager-a': NO}),
    ('chat clinico de IA', '/app/ai/chat/',
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': NO, 'manager-a': NO}),
    ('dashboard gerencial', '/app/reporting/',
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': NO, 'manager-a': OK}),
    ('financeiro', '/app/finance/',
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': OK, 'manager-a': OK}),
    ('config. agenda PROPRIA (doctor-b)', f'/app/scheduling/configurar/?physician={doctor_b.id}',
     {'doctor-a': OK, 'doctor-b': OK, 'secretary-a': OK, 'manager-a': OK}),
    ('config. agenda ALHEIA (doctor-a)', f'/app/scheduling/configurar/?physician={doctor_a.id}',
     {'doctor-a': OK, 'doctor-b': NO, 'secretary-a': OK, 'manager-a': OK}),
    ('mensageria', '/app/org/mensageria/',
     {'doctor-a': OK, 'doctor-b': NO, 'secretary-a': NO, 'manager-a': OK}),
    ('colaboradores', '/app/org/collaborators/',
     {'doctor-a': OK, 'doctor-b': NO, 'secretary-a': NO, 'manager-a': NO}),
]

PROFILES = ['doctor-a', 'doctor-b', 'secretary-a', 'manager-a']

clients = {}
for name in PROFILES:
    user = User.objects.get(email=f'{name}@demo.neurodoc.local')
    membership = Membership.objects.get(user=user, tenant__slug=TENANT)
    client = Client()
    client.force_login(user)
    session = client.session
    session['tenant_id'] = str(membership.tenant_id)
    session.save()
    clients[name] = client

failures = []
skipped = []
width = 36
print(f'{"acao":{width}}' + ''.join(f'{p:14}' for p in PROFILES))
print('-' * (width + 14 * len(PROFILES)))

for label, url, expected in CASES:
    if url is None:
        skipped.append(label)
        continue
    row = f'{label:{width}}'
    for name in PROFILES:
        response = clients[name].get(url, follow=False)
        code = response.status_code
        # 302 para o balcao conta como negado ao dashboard: o conteudo nao saiu.
        got = OK if code in (200, 201) else NO
        want = expected[name]
        mark = '' if got == want else f'  <<ESPERAVA {want}>>'
        row += f'{got}({code}){mark:{0}}' .ljust(14)
        if got != want:
            failures.append(f'{label} / {name}: esperava {want}, veio {got} (HTTP {code})')
    print(row)

print('---')
for label in skipped:
    print('SEM DADO PARA TESTAR:', label)
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: a matriz de acesso confere com o PRD secao 4.')
