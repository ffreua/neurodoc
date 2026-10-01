"""Confere o modal e os horários explícitos das agendas semana e mês.

Renderiza as agendas como o navegador as receberia. A regressão que isto
pega é uma tela incluir o modal sem tipos de atendimento, o horário livre
da semana voltar a ser um quadrado sem hora ou o mês voltar a mostrar apenas
contadores, sem permitir escolher diretamente uma vaga.
"""
from datetime import date, timedelta
from django.utils import timezone
import re

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
from scheduling.availability import month_summary, type_durations
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

print('=== mes permite marcar diretamente numa vaga ===')
# Procura um mês futuro que a grade publicada realmente cubra. Assim o
# roteiro não depende de setembro/2026 nem confunde "sem vaga" com defeito
# visual.
month = timezone.localdate().replace(day=1)
for _ in range(12):
    next_month = (month + timedelta(days=32)).replace(day=1)
    days = []
    cursor = month
    while cursor < next_month:
        days.append(cursor)
        cursor += timedelta(days=1)
    summary = month_summary(membership.id, days)
    if sum(row['free'] for row in summary.values()):
        break
    month = next_month
else:
    raise SystemExit('FALHA: a grade demonstrativa não tem vaga nos próximos 12 meses')

free_day = next(day for day, row in summary.items() if row['free'])
print('=== horarios visiveis na semana ===')
week_url = f'/app/scheduling/?physician={membership.id}&date={free_day.isoformat()}'
week_html = client.get(week_url).content.decode()
free_week = re.findall(r'data-nd-book[\s\S]*?</button>', week_html)
explicit_week = [slot for slot in free_week if 'Livre' in slot and re.search(r'\d{2}:\d{2}h', slot)]
print(f'  livres={len(free_week)}  com rotulo e hora={len(explicit_week)}')
if not free_week:
    failures.append('a semana com grade não mostrou nenhum horário livre')
elif len(explicit_week) != len(free_week):
    failures.append('a semana tem horário livre sem o rótulo Livre e sua hora')

month_url = (
    f'/app/scheduling/mes/?physician={membership.id}&date={month.isoformat()}'
)
month_response = client.get(month_url)
month_html = month_response.content.decode()
month_free = re.findall(r'data-nd-book[\s\S]*?</button>', month_html)
month_busy = re.findall(r'nd-month-slot-busy', month_html)
has_modal = SELECT_RE.search(month_html) is not None
print(f'  mes={month:%Y-%m}  HTTP={month_response.status_code}')
print(f'  vagas clicaveis={len(month_free)}  ocupados vermelhos={len(month_busy)}  modal={has_modal}')
if month_response.status_code != 200:
    failures.append(f'mes: HTTP {month_response.status_code}')
if not month_free:
    failures.append('o mes nao oferece nenhuma vaga clicavel para marcar')
if not all('Livre' in slot and re.search(r'\d{2}:\d{2}h', slot) for slot in month_free):
    failures.append('o mes tem vaga sem o rotulo Livre e sua hora')
if not has_modal:
    failures.append('o mes oferece vaga sem o modal de marcacao')
if sum(row['booked'] for row in summary.values()) and not month_busy:
    failures.append('o mes tem agendamento mas não o mostra como ocupado em vermelho')

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: agendas mostram horários e permitem marcar diretamente no mês.')
