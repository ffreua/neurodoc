"""Confere que o modal de marcação sai com o tipo de atendimento preenchido.

Renderiza a agenda da semana e a do dia como o navegador as receberia e
conta as <option> do select de tipo. A regressão que isto pega é a tela do
dia sair com o select vazio.
"""
import re

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from scheduling.availability import type_durations
from tenancy.models import Membership

user = User.objects.get(email='doctor-a@demo.neurodoc.local')
membership = Membership.objects.get(user=user, tenant__slug='demo-clinica-a')

client = Client()
client.force_login(user)
# O tenant vem do middleware; o header é como as outras telas o escolhem.
session = client.session
session['tenant_id'] = str(membership.tenant_id)
session.save()

SELECT_RE = re.compile(
    r'<select[^>]*id="book-type".*?</select>', re.S,
)

expected = len(type_durations(membership.id))
failures = []

for label, url in [
    ('semana', f'/app/scheduling/?physician={membership.id}'),
    ('dia', f'/app/scheduling/dia/?physician={membership.id}'),
]:
    response = client.get(url)
    if response.status_code != 200:
        failures.append(f'{label}: HTTP {response.status_code}')
        continue
    html = response.content.decode()
    match = SELECT_RE.search(html)
    if match is None:
        failures.append(f'{label}: select book-type ausente da página')
        continue
    options = re.findall(r'<option value="([^"]*)"', match.group(0))
    real = [o for o in options if o]
    print(f'{label}: {len(real)} opcao(oes) -> {real}')
    if len(real) != expected:
        failures.append(f'{label}: esperava {expected} opcoes, veio {len(real)}')

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o select de tipo de atendimento sai preenchido nas duas telas.')
