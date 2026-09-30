"""A captura local foi retirada sem afetar o upload manual de anexos.

O roteiro protege as tres portas que poderiam reativar a funcao por
acidente: navegacao da clinica, tela interna e receptor publico do agente.
O artigo de ajuda tambem precisa desaparecer, pois instruir um fluxo que nao
existe e uma porta quebrada do mesmo jeito.
"""

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from patients.models import Patient
from tenancy.models import Membership


failures = []
user = User.objects.get(email='secretary-a@demo.neurodoc.local')
membership = Membership.objects.get(user=user, tenant__slug='demo-clinica-a')

client = Client()
client.force_login(user)
session = client.session
session['tenant_id'] = str(membership.tenant_id)
session.save()

patient = Patient.objects.filter(tenant=membership.tenant).first()
entry = client.get(f'/app/patients/{patient.id}/')
body = entry.content.decode()
if entry.status_code != 200:
    failures.append(f'ficha do paciente respondeu HTTP {entry.status_code}')
if 'Captura local' in body or '/app/integrations/capture/' in body:
    failures.append('o menu ainda oferece a captura local')

internal = client.get('/app/integrations/capture/devices/')
if internal.status_code != 404:
    failures.append(f'a tela interna de captura ainda responde HTTP {internal.status_code}')

public = client.post('/capture/upload/token-inexistente/', data={})
if public.status_code != 404:
    failures.append(f'o receptor publico de captura ainda responde HTTP {public.status_code}')

help_article = client.get('/ajuda/scanner/')
if help_article.status_code != 404:
    failures.append(f'o manual ainda publica o artigo do scanner (HTTP {help_article.status_code})')

print('menu:', 'sem captura' if 'Captura local' not in body else 'ainda visivel')
print('tela interna:', internal.status_code)
print('receptor publico:', public.status_code)
print('artigo de ajuda:', help_article.status_code)
print('---')
if failures:
    for failure in failures:
        print('FALHA:', failure)
    raise SystemExit(1)
print('OK: captura local removida das superficies do produto.')
