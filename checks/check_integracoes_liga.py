"""SMS e e-mail da clinica: liga e desliga, e apagar de verdade (2026-11-26).

O mesmo defeito da IA propria (`check_ia_propria_liga`): o campo da senha
em branco **mantem** a guardada, de proposito, e nao havia como apaga-la.
Agora cada um dos tres -- SMS, servidor de e-mail da clinica, remetente de
e-mail do medico -- tem o liga/desliga com os campos so quando ligado, e um
botao de remover que apaga a credencial.

O que se cobra:

- a tela tem os tres liga/desliga (`role="switch"`, `data-nd-revela`), com
  um bloco por medico de id proprio, e os blocos escondidos quando
  desligados;
- **SMS**: remover apaga a chave e desliga, guarda o nome da mensagem, nao
  toca o servidor de e-mail nem o texto do WhatsApp; desligar sem remover
  guarda a chave (a regra de sempre: desligado com chave e recusa);
- **e-mail da clinica**: remover devolve remetente, servidor e senha ao
  padrao, sem tocar a chave do SMS;
- **e-mail do medico**: remover apaga a linha dele, e so a dele; medico de
  outra clinica e 404;
- so por POST, so para quem configura integracoes, na trilha sem segredo,
  e a outra clinica intacta.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.forms.models import model_to_dict
from django.test import Client

from audit.models import AuditEvent
from communications.models import DoctorEmailSettings, MessagingSettings
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []
URL = '/app/org/mensageria/'


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


clinica = Tenant.objects.get(slug='demo-clinica-a')
clinica_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo(tenant, papel):
    return Membership.objects.filter(
        tenant=tenant, roles__contains=[papel], status=MembershipStatus.ACTIVE,
    ).select_related('user').first()


def logado(m, tenant):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


dono = vinculo(clinica, Role.OWNER)
medico = vinculo(clinica, Role.DOCTOR)
medico_b = vinculo(clinica_b, Role.DOCTOR)
secretaria = vinculo(clinica, Role.SECRETARY)
cli = logado(dono, clinica)


def guardar(modelo, tenants):
    return [model_to_dict(r) | {'id': r.id} for r in modelo.objects.filter(tenant__in=tenants)]


guarda_msg = guardar(MessagingSettings, [clinica, clinica_b])
guarda_doc = guardar(DoctorEmailSettings, [clinica, clinica_b])


def com_tudo(tenant):
    MessagingSettings.objects.filter(tenant=tenant).delete()
    return MessagingSettings.objects.create(
        tenant=tenant, sms_enabled=True, sms_api_key_ciphertext='cifra-sms', sms_api_key_hint='****9999',
        sms_sender_name='Clinica Roteiro', email_enabled=True, email_from_name='Roteiro',
        email_from_address='roteiro@example.com', smtp_host='smtp.example.com', smtp_port=587,
        smtp_user='roteiro@example.com', smtp_password_ciphertext='cifra-smtp', smtp_password_hint='****8888',
        whatsapp_texto='Texto do roteiro {data}',
    )


def remetente(tenant, membro):
    DoctorEmailSettings.objects.filter(tenant=tenant, physician_membership=membro).delete()
    return DoctorEmailSettings.objects.create(
        tenant=tenant, physician_membership=membro, enabled=True, from_name='Dr Roteiro',
        from_email='dr@example.com', smtp_host='smtp.example.com', smtp_port=587, smtp_user='dr@example.com',
        smtp_password_ciphertext='cifra-dr', smtp_password_hint='****7777',
    )


try:
    print('=== 1. os tres liga/desliga ===')
    com_tudo(clinica)
    remetente(clinica, medico)
    corpo = cli.get(URL).content.decode()
    confere(corpo.count('role="switch"') >= 3, f'tres ou mais liga/desliga ({corpo.count(chr(34) + "switch")})')
    confere('data-nd-revela="sms-campos"' in corpo and 'data-nd-revela="email-clinica-campos"' in corpo,
            'SMS e e-mail da clinica com o bloco proprio')
    confere(f'data-nd-revela="email-medico-campos-{medico.id}"' in corpo
            and f'id="id_enabled_{medico.id}"' in corpo, 'um bloco e um id por medico')
    confere('Remover chave' in corpo and 'Remover servidor e senha' in corpo
            and 'Remover remetente e senha' in corpo, 'os tres botoes de remover aparecem')
    MessagingSettings.objects.filter(tenant=clinica).update(sms_enabled=False, email_enabled=False)
    corpo = cli.get(URL).content.decode()
    confere('<div id="sms-campos" hidden>' in corpo and '<div id="email-clinica-campos" hidden>' in corpo,
            'desligados, os blocos ficam escondidos')

    print('=== 2. SMS ===')
    remover = URL + 'sms/remover/'
    confere(cli.get(remover).status_code in (404, 405), 'GET nao remove')
    if secretaria:
        confere(logado(secretaria, clinica).post(remover).status_code in (403, 404), 'a secretaria nao remove')
    com_tudo(clinica_b)
    r = cli.post(remover)
    linha = MessagingSettings.objects.get(tenant=clinica)
    confere(r.status_code == 302 and not linha.has_api_key and not linha.sms_enabled,
            'remover apaga a chave e desliga')
    confere(linha.sms_sender_name == 'Clinica Roteiro', 'o nome da mensagem fica')
    confere(linha.has_smtp_password and linha.smtp_host == 'smtp.example.com'
            and linha.whatsapp_texto == 'Texto do roteiro {data}',
            'o servidor de e-mail e o texto do WhatsApp ficam intactos')
    confere(MessagingSettings.objects.get(tenant=clinica_b).has_api_key, 'a clinica B fica com a chave')
    confere(AuditEvent.objects.filter(action='communications.sms_settings_removed').exists(),
            'a remocao entrou na trilha')

    print('=== 3. e-mail da clinica ===')
    com_tudo(clinica)
    r = cli.post(URL + 'email-da-clinica/remover/')
    linha = MessagingSettings.objects.get(tenant=clinica)
    confere(r.status_code == 302 and not linha.has_smtp_password and not linha.smtp_host
            and not linha.email_from_address and not linha.email_enabled,
            'remover apaga remetente, servidor e senha')
    confere(linha.smtp_use_tls is True and linha.smtp_use_ssl is False, 'TLS e SSL voltam ao padrao')
    confere(linha.has_api_key and linha.sms_enabled, 'a chave do SMS fica intacta')
    confere(MessagingSettings.objects.get(tenant=clinica_b).has_smtp_password, 'a clinica B fica com a senha')
    evento = AuditEvent.objects.filter(action='communications.clinic_email_settings_removed').order_by('-created_at').first()
    confere(evento is not None and 'cifra' not in str(evento.integrity_metadata), 'trilha sem segredo')

    print('=== 4. e-mail do medico ===')
    remetente(clinica, medico)
    if medico_b:
        remetente(clinica_b, medico_b)
        confere(cli.post(URL + f'email/{medico_b.id}/remover/').status_code == 404,
                'medico de outra clinica e 404')
        confere(DoctorEmailSettings.objects.filter(physician_membership=medico_b).exists(),
                'e o remetente dele fica')
    r = cli.post(URL + f'email/{medico.id}/remover/')
    confere(r.status_code == 302 and not DoctorEmailSettings.objects.filter(physician_membership=medico).exists(),
            'remover apaga o remetente e a senha do medico')
    corpo = cli.get(URL).content.decode()
    confere(f'action="/app/org/mensageria/email/{medico.id}/remover/"' not in corpo,
            'sem remetente, o botao some')

    print('=== 5. desligar sem remover guarda a chave ===')
    com_tudo(clinica)
    from tenancy.plans import has_sms

    if has_sms(clinica.plan):
        r = cli.post(URL + 'sms/', {'api_key': '', 'sms_sender_name': 'Clinica Roteiro'})
        linha = MessagingSettings.objects.get(tenant=clinica)
        confere(r.status_code == 302 and not linha.sms_enabled and linha.has_api_key,
                'salvar desligado desliga e guarda a chave')
    else:
        print('  (plano sem SMS: secao pulada)')
finally:
    MessagingSettings.objects.filter(tenant__in=[clinica, clinica_b]).delete()
    DoctorEmailSettings.objects.filter(tenant__in=[clinica, clinica_b]).delete()
    for dados in guarda_msg:
        dados = dict(dados)
        dados['tenant_id'] = dados.pop('tenant')
        dados['updated_by_id'] = dados.pop('updated_by', None)
        MessagingSettings.objects.create(**dados)
    for dados in guarda_doc:
        dados = dict(dados)
        dados['tenant_id'] = dados.pop('tenant')
        dados['physician_membership_id'] = dados.pop('physician_membership')
        dados['updated_by_id'] = dados.pop('updated_by', None)
        DoctorEmailSettings.objects.create(**dados)
    print('  limpeza: configuracoes de mensageria da demonstracao devolvidas')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: SMS e e-mail ligam e desligam, guardam a senha ao desligar e apagam de verdade ao remover.')
