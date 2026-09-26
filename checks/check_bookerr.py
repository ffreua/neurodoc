"""O aviso de campo faltando tem de dizer QUAL campo."""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from django.contrib.messages import get_messages
from django.utils import timezone

from accounts.models import User
from tenancy.models import Membership

user = User.objects.get(email='doctor-a@demo.neurodoc.local')
membership = Membership.objects.get(user=user, tenant__slug='demo-clinica-a')

client = Client()
client.force_login(user)
session = client.session
session['tenant_id'] = str(membership.tenant_id)
session.save()

when = (timezone.now() + timezone.timedelta(days=30)).replace(hour=10, minute=0, second=0, microsecond=0)

cases = {
    'sem tipo de atendimento': {
        'starts_at': when.isoformat(), 'patient_search': '', 'new_name': 'Teste Silva',
        'new_phone': '11999990000',
    },
    'sem paciente': {
        'starts_at': when.isoformat(), 'appointment_type': 'first_visit',
    },
    'encaixe sem justificativa': {
        'starts_at': when.isoformat(), 'appointment_type': 'first_visit',
        'new_name': 'Teste Silva', 'new_phone': '11999990000', 'is_overbook': 'on',
    },
}

failures = []
for label, payload in cases.items():
    # `follow=True`: sem seguir o redirect a mensagem fica na sessao e a
    # proxima requisicao a le junto com a sua, misturando os casos.
    response = client.post(
        f'/app/scheduling/{membership.id}/marcar/', payload, follow=True,
    )
    notes = [str(m) for m in get_messages(response.wsgi_request)]
    text = notes[-1] if notes else '(nenhuma mensagem)'
    print(f'{label}\n  -> {text}')
    if text == 'Este campo é obrigatório.':
        failures.append(f'{label}: aviso ainda nao diz qual campo')
    if not notes:
        failures.append(f'{label}: nao gerou aviso nenhum')

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: todo aviso nomeia o campo que falhou.')
