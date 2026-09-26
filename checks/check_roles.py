"""Matriz de acesso: o que cada perfil alcanca hoje."""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from tenancy.models import Membership

ROUTES = [
    ('agenda semana', '/app/scheduling/'),
    ('agenda dia', '/app/scheduling/dia/'),
    ('balcao', '/app/scheduling/balcao/'),
    ('config agenda', '/app/scheduling/configurar/'),
    ('pacientes', '/app/patients/'),
    ('mensageria (gestor)', '/app/org/mensageria/'),
    ('entregas (gestor)', '/app/org/mensageria/entregas/'),
    ('colaboradores (owner)', '/app/org/collaborators/'),
    ('dashboard', '/app/reporting/'),
]

USERS = [
    'doctor-a@demo.neurodoc.local',
    'doctor-b@demo.neurodoc.local',
    'secretary-a@demo.neurodoc.local',
    'manager-a@demo.neurodoc.local',
]

header = f'{"rota":24}' + ''.join(f'{e.split("@")[0]:16}' for e in USERS)
print(header)
print('-' * len(header))

results = {}
for email in USERS:
    user = User.objects.get(email=email)
    membership = Membership.objects.get(user=user, tenant__slug='demo-clinica-a')
    client = Client()
    client.force_login(user)
    session = client.session
    session['tenant_id'] = str(membership.tenant_id)
    session.save()
    for label, url in ROUTES:
        try:
            response = client.get(url, follow=False)
            results[(label, email)] = response.status_code
        except Exception as exc:                      # noqa: BLE001
            results[(label, email)] = type(exc).__name__

for label, _url in ROUTES:
    row = f'{label:24}'
    for email in USERS:
        row += f'{str(results[(label, email)]):16}'
    print(row)
