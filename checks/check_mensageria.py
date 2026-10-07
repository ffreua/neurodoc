"""As duas mensagerias se tocam em algum lugar?

O NeuroDoc tem **duas** camadas de envio, e elas nao podem se misturar:

- a da **instalacao**: o SMTP do proprio NeuroDoc, em segredo do servidor,
  que manda verificacao de conta, recuperacao de senha e aviso de lead --
  assuntos do sistema, nao de nenhuma clinica;
- a de **cada clinica**: SMTP proprio, informado pelo gestor, guardado
  cifrado no banco -- e, dentro dela, o remetente proprio de cada medico,
  que vence o da clinica.

Misturar as duas tem consequencias concretas: um e-mail de recuperacao de
senha saindo assinado por uma clinica; a clinica B mandando pelo servidor
da clinica A e queimando a reputacao de um dominio que nao e dela; a
senha de SMTP de uma clinica visivel para outra.

As perguntas sao:

- o remetente de uma clinica aparece na outra?
- a senha de cada uma e so dela, e esta cifrada no banco?
- o remetente do medico vence o da clinica, e so para ele?
- desligar o canal na clinica devolve o envio a instalacao?
- o e-mail da instalacao sai por remetente de clinica?
- clinica suspensa continua falando com paciente?
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# A caixa em memoria, independentemente do que o ambiente diga: este
# roteiro afirma sobre o **remetente**, e nao sobre entrega.
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail

from accounts.models import User
from base.crypto import encrypt_secret
from communications.email import _clinic_settings, _doctor_settings, resolve_sender
from communications.models import DoctorEmailSettings, MessagingSettings
from tenancy.models import Membership, Tenant

falhas = []

tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
medico_a = User.objects.get(email='doctor-a@demo.neurodoc.local')
medico_b = User.objects.get(email='doctor-b@demo.neurodoc.local')
vinculo_a = Membership.objects.get(user=medico_a, tenant=tenant_a)
vinculo_b = Membership.objects.get(user=medico_b, tenant=tenant_a)


def vinculo_fresco(vinculo):
    """Relacao reversa vem em cache no objeto; uma requisicao busca de novo.

    `_doctor_settings` le `membership.email_settings`, que o Django guarda
    no objeto depois do primeiro acesso. Reaproveitar o mesmo objeto depois
    de mudar a configuracao leria o estado antigo -- e o roteiro acusaria
    um defeito que so existe dentro dele.
    """
    return Membership.objects.get(pk=vinculo.pk)


def configurar_clinica(tenant, endereco, servidor):
    linha, _ = MessagingSettings.objects.get_or_create(tenant=tenant)
    linha.email_enabled = True
    linha.email_from_address = endereco
    linha.email_from_name = f'Clinica {tenant.slug}'
    linha.smtp_host = servidor
    linha.smtp_port = 587
    linha.smtp_user = f'usuario@{servidor}'
    cifra, meta = encrypt_secret(f'senha-de-{tenant.slug}')
    linha.smtp_password_ciphertext = cifra
    linha.smtp_password_metadata = meta
    linha.smtp_use_tls = True
    linha.save()
    return linha


print('=== 1. o remetente de uma clinica nao aparece na outra ===')
linha_a = configurar_clinica(tenant_a, 'contato@clinica-a.example', 'smtp.clinica-a.example')
configurar_clinica(tenant_b, 'contato@clinica-b.example', 'smtp.clinica-b.example')

rem_a = resolve_sender(tenant_id=tenant_a.id)
rem_b = resolve_sender(tenant_id=tenant_b.id)
print(f'  A -> {rem_a.header} via {rem_a.host}')
print(f'  B -> {rem_b.header} via {rem_b.host}')
if 'clinica-a' in rem_b.header or 'clinica-b' in rem_a.header:
    falhas.append('VAZAMENTO: o remetente de uma clinica apareceu na outra')
if rem_a.host == rem_b.host:
    falhas.append('as duas clinicas resolveram para o mesmo servidor SMTP')

print('=== 2. a senha de cada clinica e so dela, e esta cifrada ===')
senha_a = rem_a.password()
senha_b = rem_b.password()
print(f'  senhas iguais={senha_a == senha_b}  '
      f'cada uma e a sua={"demo-clinica-a" in senha_a and "demo-clinica-b" in senha_b}')
if senha_a == senha_b:
    falhas.append('VAZAMENTO: as duas clinicas devolveram a mesma senha de SMTP')
if 'demo-clinica-a' not in senha_a or 'demo-clinica-b' not in senha_b:
    falhas.append('a senha decifrada nao e a que foi gravada para aquela clinica')

guardado = MessagingSettings.objects.get(tenant=tenant_a).smtp_password_ciphertext
em_claro = 'senha-de-demo-clinica-a' in str(guardado)
print(f'  texto claro no banco={em_claro} (False esperado)')
if em_claro:
    falhas.append('GRAVE: a senha de SMTP da clinica esta em texto claro no banco')

print('=== 3. o remetente do medico vence o da clinica, e so para ele ===')
cifra, meta = encrypt_secret('senha-do-medico')
DoctorEmailSettings.objects.update_or_create(
    physician_membership=vinculo_a,
    defaults=dict(
        tenant=tenant_a, enabled=True, from_email='dra.ana@medico.example',
        from_name='Dra. Ana', smtp_host='smtp.medico.example', smtp_port=587,
        smtp_user='ana', smtp_password_ciphertext=cifra,
        smtp_password_metadata=meta, use_tls=True,
    ),
)
com = resolve_sender(physician_membership=vinculo_fresco(vinculo_a), tenant_id=tenant_a.id)
sem = resolve_sender(physician_membership=vinculo_fresco(vinculo_b), tenant_id=tenant_a.id)
print(f'  medico que configurou -> {com.header}')
print(f'  colega que nao        -> {sem.header}')
if 'medico.example' not in com.header:
    falhas.append('a configuracao do proprio medico nao venceu a da clinica')
if 'medico.example' in sem.header:
    falhas.append('VAZAMENTO: o remetente de um medico foi usado por um colega')
if 'clinica-a' not in sem.header:
    falhas.append('o colega sem configuracao nao caiu no remetente da clinica')

print('=== 4. desligar na clinica devolve o envio a instalacao ===')
DoctorEmailSettings.objects.filter(physician_membership=vinculo_a).update(enabled=False)
MessagingSettings.objects.filter(tenant=tenant_a).update(email_enabled=False)
devolvido = resolve_sender(physician_membership=vinculo_fresco(vinculo_a), tenant_id=tenant_a.id)
print(f'  com os dois desligados -> {devolvido} (None = usa a instalacao)')
if devolvido is not None:
    falhas.append('desligar o canal na clinica nao devolveu o envio a instalacao')
if _doctor_settings(vinculo_fresco(vinculo_a)) is not None:
    falhas.append('a configuracao desligada do medico continuou valendo')
if _clinic_settings(tenant_a.id) is not None:
    falhas.append('a configuracao desligada da clinica continuou valendo')

print('=== 5. o e-mail da instalacao nao sai assinado por clinica ===')
# Verificacao de conta, recuperacao de senha e aviso de lead sao assuntos
# do sistema. Se um deles pegasse o remetente de uma clinica, o paciente
# receberia "redefina sua senha" assinado por um consultorio qualquer.
MessagingSettings.objects.filter(tenant=tenant_a).update(email_enabled=True)
from accounts.services import send_email_verification

mail.outbox = []
pedido = type('R', (), {'build_absolute_uri': lambda self, caminho: 'http://x' + caminho})()
send_email_verification(medico_a, pedido)
remetente = mail.outbox[0].from_email if mail.outbox else ''
print(f'  verificacao de conta -> {remetente!r}')
if remetente != dj_settings.DEFAULT_FROM_EMAIL:
    falhas.append('o e-mail de conta nao usa o remetente da instalacao')
if 'clinica-a' in remetente or 'medico.example' in remetente:
    falhas.append('GRAVE: e-mail da instalacao saiu assinado por uma clinica')

from tenancy.leads import notify
from tenancy.models import Lead

mail.outbox = []
lead = Lead.objects.create(name='Roteiro', email='roteiro@check.invalid', plan='basic')
notify(lead)
rem_lead = mail.outbox[0].from_email if mail.outbox else ''
destino = mail.outbox[0].to if mail.outbox else []
print(f'  aviso de lead -> {rem_lead!r} para {destino}')
if rem_lead != dj_settings.DEFAULT_FROM_EMAIL:
    falhas.append('o aviso de lead nao usa o remetente da instalacao')
if destino != [dj_settings.LEADS_EMAIL]:
    falhas.append('o aviso de lead nao foi para LEADS_EMAIL: destinatario nao e do servidor')
lead.delete()

print('=== 6. clinica suspensa nao fala com paciente por canal nenhum ===')
from communications.models import (
    Delivery, DeliveryChannel, DeliveryStatus,
)
from communications.services import _send
from patients.models import PatientContact
from scheduling.models import Appointment
from tenancy.models import TenantStatus

consulta = Appointment.objects.filter(tenant=tenant_a).first()
contato = PatientContact.objects.filter(tenant=tenant_a).first()
if consulta is None or contato is None:
    falhas.append('sem consulta ou contato no banco: a secao 6 nao afirma nada')
else:
    original = tenant_a.status
    for canal in [DeliveryChannel.EMAIL, DeliveryChannel.SMS]:
        Tenant.objects.filter(pk=tenant_a.pk).update(status=TenantStatus.SUSPENDED)
        entrega = Delivery.objects.create(
            tenant=tenant_a, appointment=consulta, contact=contato,
            channel=canal, event_version=1, status=DeliveryStatus.PENDING,
            idempotency_key=f'check-mensageria-{canal}',
        )
        _send(entrega, 'nao deve sair')
        entrega.refresh_from_db()
        tentativa = entrega.attempts.order_by('-created_at').first()
        motivo = getattr(tentativa, 'sanitized_error', '')
        # `CHANNEL_UNAVAILABLE` e nao `NO_CONTACT`: quem nao pode
        # enviar e o sistema, nao o paciente que nao tem telefone.
        barrou = (entrega.status == DeliveryStatus.CHANNEL_UNAVAILABLE
                  and motivo == 'tenant_inactive')
        print(f'  canal {canal:6} suspensa -> barrado={barrou} motivo={motivo!r}')
        if not barrou:
            falhas.append(f'clinica suspensa continuou enviando por {canal}')
        entrega.attempts.all().delete()
        entrega.delete()
    Tenant.objects.filter(pk=tenant_a.pk).update(status=original)

# ---------------------------------------------------------------- limpeza
DoctorEmailSettings.objects.filter(physician_membership=vinculo_a).delete()
for tenant in [tenant_a, tenant_b]:
    MessagingSettings.objects.filter(tenant=tenant).update(
        email_enabled=False, email_from_address='', email_from_name='',
        smtp_host='', smtp_user='', smtp_password_ciphertext='',
        smtp_password_metadata={},
    )

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: a mensageria da instalacao e a de cada clinica nao se tocam.')
