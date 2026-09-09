"""Isola o 404 do carry-forward: e a view, ou e o que o navegador envia?"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from clinical.models import CarryForwardItem, Encounter, ReviewAction
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
user = User.objects.get(email='doctor-a@demo.neurodoc.local')
membership = Membership.objects.get(user=user, tenant__slug=TENANT)

client = Client()
client.force_login(user)
session = client.session
session['tenant_id'] = str(membership.tenant_id)
session.save()

item = CarryForwardItem.objects.filter(
    tenant__slug=TENANT, review_action=ReviewAction.PENDING,
).select_related('target_encounter').first()

if item is None:
    print('SEM ITEM PENDENTE — criando um a partir do atendimento mais recente')
    from clinical import carry_forward as cf
    encounters = list(
        Encounter.objects.filter(tenant__slug=TENANT).order_by('-occurred_at')[:2]
    )
    print('atendimentos disponiveis:', len(encounters))
    raise SystemExit(0)

url = f'/app/clinical/{item.target_encounter_id}/carry-forward/{item.id}/review/'
print('url:', url)

# 1. Como o navegador envia HOJE: sem `action`, porque o botao que o carrega
#    e desabilitado antes de o formulario ser serializado.
r = client.post(url, {})
print('sem action  ->', r.status_code)

# 2. Como deveria ser.
r = client.post(url, {'action': 'accepted'})
print('com action  ->', r.status_code, r.get('Location', ''))

item.refresh_from_db()
print('estado do item apos o POST valido:', item.review_action)
