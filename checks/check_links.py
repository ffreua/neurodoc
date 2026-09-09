"""Nenhum perfil pode ver um link que nao consegue abrir.

Varre as telas de entrada de cada perfil, colhe todo href para /app/ e
abre cada um. Link visivel que devolve 404 e defeito de navegacao: o
sistema esta oferecendo uma porta trancada.
"""
import re

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from patients.models import Patient
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
PROFILES = ['doctor-a', 'doctor-b', 'secretary-a', 'manager-a']
patient = Patient.objects.filter(tenant__slug=TENANT).first()

# Telas por onde cada perfil de fato passa.
ENTRY_POINTS = [
    '/app/scheduling/',
    '/app/scheduling/balcao/',
    '/app/patients/',
    f'/app/patients/{patient.id}/' if patient else None,
]
ENTRY_POINTS = [u for u in ENTRY_POINTS if u]

HREF_RE = re.compile(r'href="(/app/[^"#?]*)[^"]*"')

failures = []
for name in PROFILES:
    user = User.objects.get(email=f'{name}@demo.neurodoc.local')
    membership = Membership.objects.get(user=user, tenant__slug=TENANT)
    client = Client()
    client.force_login(user)
    session = client.session
    session['tenant_id'] = str(membership.tenant_id)
    session.save()

    seen = set()
    broken = []
    for entry in ENTRY_POINTS:
        page = client.get(entry)
        if page.status_code != 200:
            # A entrada em si ja foi conferida pela matriz; aqui so interessa
            # o que a pagina oferece quando ela abre.
            continue
        for href in HREF_RE.findall(page.content.decode()):
            if href in seen:
                continue
            seen.add(href)
            target = client.get(href)
            if target.status_code == 404:
                broken.append(f'{entry} -> {href}')
    print(f'{name}: {len(seen)} link(s) de /app/ visiveis, {len(broken)} quebrado(s)')
    for line in broken:
        print('   404:', line)
        failures.append(f'{name}: {line}')

print('---')
if failures:
    print('FALHA: link visivel que devolve 404.')
    raise SystemExit(1)
print('OK: nenhum perfil ve link que nao consegue abrir.')
