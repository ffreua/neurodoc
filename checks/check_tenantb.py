"""O que o MESMO usuario alcanca em cada organizacao."""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from scheduling.models import AvailabilityRule
from patients.models import Patient
from tenancy.models import ClinicProfile, Membership, Tenant

user = User.objects.get(email='doctor-a@demo.neurodoc.local')

ROUTES = [
    ('agenda semana', '/app/scheduling/'),
    ('config agenda', '/app/scheduling/configurar/'),
    ('pacientes', '/app/patients/'),
    ('indicadores', '/app/reporting/'),
    ('financeiro', '/app/finance/'),
    ('chat de IA', '/app/ai/chat/'),
    ('assinatura', '/app/documents/signing/credentials/'),
    ('ORG equipe', '/app/org/equipe/'),
    ('ORG identidade', '/app/org/clinica/'),
    ('mensageria', '/app/org/mensageria/'),
]

memberships = list(
    Membership.objects.filter(user=user).select_related('tenant').order_by('tenant__slug')
)

print('=== dados por organizacao ===')
for m in memberships:
    print(f'{m.tenant.slug:18} papeis={m.roles}')
    print(f'{"":18} pacientes={Patient.objects.filter(tenant=m.tenant).count()}'
          f' regras_agenda={AvailabilityRule.objects.filter(tenant=m.tenant).count()}'
          f' medicos={Membership.objects.filter(tenant=m.tenant, roles__contains=["doctor"]).count()}'
          f' identidade={"sim" if ClinicProfile.objects.filter(tenant=m.tenant).exists() else "nao"}')

print()
header = f'{"rota":22}' + ''.join(f'{m.tenant.slug:20}' for m in memberships)
print(header)
print('-' * len(header))

for label, url in ROUTES:
    row = f'{label:22}'
    for m in memberships:
        c = Client()
        c.force_login(user)
        s = c.session
        s['tenant_id'] = str(m.tenant_id)
        s.save()
        code = c.get(url).status_code
        row += f'{code:<20}'
    print(row)
