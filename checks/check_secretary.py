"""A secretaria continua fazendo o trabalho dela, e so o dela.

A matriz de leitura mostra o que ela nao ve. Falta o outro lado: proteger
demais quebraria a recepcao, e isso so aparece exercitando as acoes.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from django.contrib.messages import get_messages
from django.utils import timezone

from accounts.models import User
from clinical.models import Encounter
from patients.models import Patient, PatientContact
from scheduling.availability import available_slots
from scheduling.models import Appointment
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
doctor = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant__slug=TENANT)

user = User.objects.get(email='secretary-a@demo.neurodoc.local')
membership = Membership.objects.get(user=user, tenant__slug=TENANT)
client = Client()
client.force_login(user)
session = client.session
session['tenant_id'] = str(membership.tenant_id)
session.save()

failures = []

# --- 1. marcar um paciente novo, que e o trabalho principal do balcao ---
#
# Tenta varios horarios em vez de so o primeiro livre: a primeira consulta
# ocupa 70 minutos, e o ultimo vago do dia costuma nao comportar isso. Pegar
# `slots[0]` fazia o teste passar ou falhar conforme quanto a agenda de
# demonstracao ja tivesse enchido — falha de fixture disfarcada de regressao.
marcado = None
day = timezone.now().date()
for offset in range(1, 40):
    probe = day + timezone.timedelta(days=offset)
    for slot, *_ in available_slots(doctor.id, probe):
        before = Appointment.objects.count()
        response = client.post(f'/app/scheduling/{doctor.id}/marcar/', {
            'starts_at': slot.isoformat(),
            'appointment_type': 'first_visit',
            'new_name': 'Teste Permissao Secretaria',
            'new_phone': '11988887777',
        }, follow=True)
        notes = [str(m) for m in get_messages(response.wsgi_request)]
        if Appointment.objects.count() - before == 1:
            novo = Appointment.objects.filter(
                starts_at=slot, physician_membership=doctor,
            ).first()
            marcado = (slot, notes[-1] if notes else '(sem aviso)',
                       novo.patient_id if novo else None)
            break
    if marcado:
        break

if marcado is None:
    failures.append('a secretaria nao conseguiu marcar em nenhum horario livre')
    print('marcar atendimento -> NENHUM horario aceito')
else:
    print('marcar atendimento ->', marcado[1])

# --- 2. cadastrar paciente ---
response = client.get('/app/patients/new/')
print('abrir cadastro de paciente ->', response.status_code)
if response.status_code != 200:
    failures.append(f'cadastro de paciente devolveu {response.status_code}')

# --- 3. o que ela NAO pode: escrever no prontuario ---
encounter = Encounter.objects.filter(tenant__slug=TENANT).first()
if encounter is not None:
    response = client.post(f'/app/clinical/{encounter.id}/autosave/', {'chief_complaint': 'invasao'})
    print('gravar no prontuario ->', response.status_code)
    if response.status_code != 404:
        failures.append(f'a secretaria gravou no prontuario (HTTP {response.status_code})')
    encounter.refresh_from_db()
    if encounter.chief_complaint == 'invasao':
        failures.append('o prontuario foi alterado pela secretaria')

# --- 4. o que ela NAO pode: assinar documento ---
response = client.get('/app/documents/signing/credentials/')
print('certificados de assinatura ->', response.status_code)
if response.status_code != 404:
    failures.append(f'a secretaria alcancou os certificados (HTTP {response.status_code})')

# Devolve o horario a agenda **e o paciente que o pre-cadastro criou**.
#
# Sem devolver o horario, cada rodada come um espaco da agenda de
# demonstracao, ate o dia em que nao cabe mais uma primeira consulta — e o
# teste passa a falhar por esgotamento, nao por regressao.
#
# O paciente ficava: marcar pela agenda com `new_name` faz um pre-cadastro,
# e so o agendamento era apagado. Sete rodadas deixavam sete "Teste
# Permissao Secretaria" identicos na lista de pacientes de quem abrisse o
# sistema — e paciente ativo conta para o limite do plano
# (`tenancy/limits.py`), de modo que o acumulo terminaria no mesmo
# esgotamento que o paragrafo acima existe para evitar.
if marcado:
    Appointment.objects.filter(starts_at=marcado[0], physician_membership=doctor).delete()
    print('horario devolvido a agenda:', marcado[0])
    if marcado[2]:
        # O telefone informado vira um `PatientContact`, que e `PROTECT`:
        # sai antes, ou o paciente nao sai.
        PatientContact.objects.filter(patient_id=marcado[2]).delete()
        apagados, _ = Patient.objects.filter(id=marcado[2]).delete()
        print('paciente do pre-cadastro removido:', bool(apagados))

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: a secretaria trabalha, e nao passa do que lhe compete.')
