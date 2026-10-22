"""Telas cujo número de consultas não pode crescer com o volume (auditoria da 1.24, D1).

Duas telas faziam uma consulta por linha:
- **documentos do paciente** perguntava `replaced_by.exists()` por documento,
  para o selo "retificado" (18 consultas com 2 documentos, 24 com 8);
- **agenda do mês** buscava os contatos do paciente por horário marcado, na
  célula ocupada (`nd_confirmation_contacts`). A semana e o dia já tinham o
  prefetch; o mês tinha ficado de fora.

O roteiro cria o volume **dentro de uma transação desfeita** e mede a mesma
tela com N=2 e N=8. A regra é uma só: o número de consultas não muda com N.
Quem reabrir um N+1 nessas duas telas reprova aqui.

    docker compose exec -T app python manage.py shell < checks/check_consultas_fixas.py
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from documents.models import MedicalDocument
from patients.models import Patient
from scheduling.models import Appointment
from tenancy.models import Membership

settings.ALLOWED_HOSTS += ['testserver']
settings.SECURE_SSL_REDIRECT = False

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


user = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = (Membership.objects
           .filter(user=user, status='active', roles__contains=['doctor'])
           .order_by('created_at').first())
paciente = Patient.objects.filter(tenant_id=vinculo.tenant_id).order_by('created_at').first()
cliente = Client()
cliente.force_login(user)
sessao = cliente.session
sessao['tenant_id'] = str(vinculo.tenant_id)
sessao.save()

hoje = timezone.localdate()
alvo = (hoje.replace(day=1) + timedelta(days=40)).replace(day=1)
dias_uteis = [alvo + timedelta(days=i) for i in range(28) if (alvo + timedelta(days=i)).weekday() < 5]
fuso = timezone.get_current_timezone()
url_mes = f"{reverse('scheduling:month')}?physician={vinculo.id}&date={alvo:%Y-%m-%d}"
url_docs = reverse('documents:patient-documents', args=[paciente.id])


def consultas(url):
    with CaptureQueriesContext(connection) as q:
        resposta = cliente.get(url)
    return resposta.status_code, len(q)


antes_docs = MedicalDocument.objects.count()
antes_horarios = Appointment.objects.count()
medidas = {}
for n in (2, 8):
    with transaction.atomic():
        for dia in dias_uteis[:n]:
            inicio = datetime.combine(dia, time(10, 0), fuso)
            fim = inicio + timedelta(minutes=40)
            Appointment.objects.create(
                tenant_id=vinculo.tenant_id, patient=paciente, physician_membership=vinculo,
                starts_at=inicio, ends_at=fim, occupied_range=DateTimeTZRange(inicio, fim),
            )
        for _ in range(n):
            MedicalDocument.objects.create(
                tenant_id=vinculo.tenant_id, patient=paciente, physician=vinculo, kind='prescription',
            )
        consultas(url_mes)  # aquece o que é carregado uma vez por processo
        medidas[n] = {'mes': consultas(url_mes), 'docs': consultas(url_docs)}
        transaction.set_rollback(True)

print('=== 1. As telas abrem ===')
for n, m in medidas.items():
    conferir(f'agenda do mês abre (N={n})', m['mes'][0] == 200, m['mes'])
    conferir(f'documentos do paciente abre (N={n})', m['docs'][0] == 200, m['docs'])

print('=== 2. O número de consultas não cresce com o volume ===')
conferir('agenda do mês: mesmas consultas com 2 e 8 horários',
         medidas[2]['mes'][1] == medidas[8]['mes'][1], medidas)
conferir('documentos do paciente: mesmas consultas com 2 e 8 documentos',
         medidas[2]['docs'][1] == medidas[8]['docs'][1], medidas)
print(f"  (mês: {medidas[2]['mes'][1]} consultas; documentos: {medidas[2]['docs'][1]} consultas)")

print('=== 3. Nada ficou gravado ===')
conferir('documentos voltaram à contagem inicial',
         MedicalDocument.objects.count() == antes_docs, (antes_docs, MedicalDocument.objects.count()))
conferir('horários voltaram à contagem inicial',
         Appointment.objects.count() == antes_horarios, (antes_horarios, Appointment.objects.count()))

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: as duas telas fazem o mesmo número de consultas com qualquer volume.')
