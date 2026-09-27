"""Pre-cadastro: nome e um contato, telefone OU e-mail.

Ao telefone a secretaria tem nome e um jeito de chamar de volta. Ate aqui
so o telefone era aceito, e ele nao alcanca quem nao atende numero
desconhecido -- que e muita gente.

O que mudou, e o que este roteiro cobra:

- **um dos dois basta.** A regra protegida continua a mesma: pre-cadastro
  sem contato nenhum e horario que ninguem consegue confirmar depois;
- o contato nasce **autorizado para mensagem transacional**, e nao com as
  travas em `False` como antes. O `False` fixo contrariava o principio que
  o cadastro completo escreve em `patients/forms.py` -- "quem deu o
  telefone no balcao deu para ser chamado" -- e o efeito era mudo: o
  telefone ficava guardado e a confirmacao nao saia, sem nada na tela
  dizendo por que;
- **cada canal segue o proprio dado.** Autorizar SMS sem telefone grava um
  consentimento que nao se exerce, e que depois se le como recusa;
- a secretaria pode desmarcar, e ai nada e autorizado. Marcada e nao
  implicita: deduzir o aceite sem oferecer a recusa transforma
  consentimento em presuncao;
- **divulgacao continua de fora.** `marketing_opt_in_at` fica nulo. E ele
  que a LGPD (art. 11, I) exige especifico e destacado, e ninguem o deduz
  de um pre-cadastro por telefone.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from patients.models import Patient, PatientContact
from scheduling.forms import QuickBookingForm
from scheduling.services import quick_register_patient
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE,
).select_related('user').first()
ctx = AccessContext(
    user_id=vinculo.user_id, tenant_id=tenant.id, membership_id=vinculo.id,
    permissions=frozenset(vinculo.roles or []), request_id=None,
    tenant_status=tenant.status, capabilities=frozenset(),
)


def registrar(nome, telefone='', email='', aceita=True):
    p = quick_register_patient(ctx, nome, telefone, email=email, accepts_messages=aceita)
    criados.append(p.id)
    return p, PatientContact.objects.filter(patient=p).first()


try:
    print('\n1. O formulario aceita um contato, e nao dois obrigatorios')
    base = {'starts_at': '2026-12-01 10:00', 'appointment_type': 'first_visit'}

    f = QuickBookingForm({**base, 'new_name': 'So Telefone', 'new_phone': '11988887777'})
    conferir('so telefone passa', f.is_valid(), True)

    f = QuickBookingForm({**base, 'new_name': 'So Email', 'new_email': 'a@example.invalid'})
    conferir('so e-mail passa', f.is_valid(), True)

    f = QuickBookingForm({**base, 'new_name': 'Os Dois',
                          'new_phone': '11988887777', 'new_email': 'a@example.invalid'})
    conferir('os dois juntos passam', f.is_valid(), True)

    f = QuickBookingForm({**base, 'new_name': 'Sem Contato Nenhum'})
    conferir('sem contato nenhum e recusado', f.is_valid(), False)
    erro = ' '.join(f.errors.get('new_phone', []))
    conferir('e o erro diz que qualquer um dos dois serve',
             'e-mail' in erro.lower() and 'telefone' in erro.lower(), True)

    f = QuickBookingForm({**base, 'new_name': 'Email Torto', 'new_email': 'isto-nao-e-email'})
    conferir('e-mail malformado e recusado', 'new_email' in f.errors, True)

    print('\n2. O contato guarda o e-mail, e nao so o telefone')
    _, c = registrar('Paciente Com Os Dois', '11988887777', 'com.dois@example.invalid')
    conferir('telefone gravado', c.phone, '11988887777')
    conferir('e-mail gravado', c.email, 'com.dois@example.invalid')

    _, c = registrar('Paciente So Email', '', 'so.email@example.invalid')
    conferir('cria contato so com e-mail', c is not None, True)
    conferir('sem telefone', c.phone, '')
    conferir('com e-mail', c.email, 'so.email@example.invalid')

    print('\n3. Cada canal segue o proprio dado')
    _, c = registrar('Paciente So Telefone', '11977776666', '')
    conferir('so telefone -> SMS autorizado', c.sms_enabled, True)
    conferir('so telefone -> e-mail NAO autorizado', c.email_enabled, False)

    _, c = registrar('Paciente Email Apenas', '', 'canal@example.invalid')
    conferir('so e-mail -> e-mail autorizado', c.email_enabled, True)
    conferir('so e-mail -> SMS NAO autorizado', c.sms_enabled, False)

    _, c = registrar('Paciente Ambos Canais', '11966665555', 'ambos@example.invalid')
    conferir('os dois -> ambos autorizados',
             (c.sms_enabled, c.email_enabled), (True, True))

    print('\n4. Desmarcando, nada e autorizado')
    _, c = registrar('Paciente Recusou', '11955554444', 'recusou@example.invalid', aceita=False)
    conferir('SMS nao autorizado', c.sms_enabled, False)
    conferir('e-mail nao autorizado', c.email_enabled, False)
    conferir('documento nao autorizado', c.authorized_for_documents, False)
    conferir('mas o contato foi guardado', c.phone, '11955554444')

    print('\n5. Divulgacao NAO se deduz de um pre-cadastro')
    # A assercao que separa transacional de marketing. Deduzir opt-in aqui
    # seria tratar dado sensivel de saude sem o consentimento especifico e
    # destacado que o art. 11, I exige.
    for c in PatientContact.objects.filter(patient_id__in=criados):
        if c.marketing_opt_in_at is not None:
            falhas.append('um pre-cadastro gravou consentimento de divulgacao')
    conferir('nenhum opt-in de divulgacao gravado',
             PatientContact.objects.filter(
                 patient_id__in=criados, marketing_opt_in_at__isnull=False,
             ).count(), 0)

    print('\n6. A tela oferece o campo')
    from django.template.loader import render_to_string

    try:
        html = render_to_string('scheduling/_booking_modals.html', {
            'booking_form': QuickBookingForm(), 'request': None,
        })
    except Exception:
        html = pathlib_lido = open(
            'templates/scheduling/_booking_modals.html', encoding='utf-8',
        ).read()
    conferir('campo de e-mail no modal', 'name="new_email"' in html, True)
    conferir('caixa de consentimento no modal',
             'name="contact_accepts_messages"' in html, True)
    conferir('a caixa nasce marcada', 'contact_accepts_messages" checked' in html, True)

finally:
    n = PatientContact.objects.filter(patient_id__in=criados).delete()[0]
    m = Patient.objects.filter(id__in=criados).delete()[0]
    print(f'\n  limpeza: {n} contato(s) e {m} objeto(s) de paciente removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: telefone ou e-mail bastam, cada canal segue o proprio dado,')
print('    a recusa e respeitada e divulgacao nao se deduz do pre-cadastro.')
