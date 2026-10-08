"""Comunicacao em massa: em qualquer plano, e so pelo servidor da clinica.

A regra, em uma frase: **campanha sai pelo servidor SMTP da propria
clinica, ou nao sai** -- no Gratuito como no Personalizado. Ate 2026-10-08
bastava o remetente da clinica estar ativo, e remetente sem servidor sai
pelo SMTP da instalacao: uma clinica podia mandar mil mensagens de
divulgacao pelo servidor que entrega a confirmacao de conta e a
recuperacao de senha de todas as outras.

O que este roteiro tenta quebrar:

1. a definicao de "servidor proprio" (ativo nao basta; host e o que conta);
2. que o plano nao entra na conta -- nem para dar, nem para tirar;
3. as portas da tela: lista, criar (GET e POST), teste e disparo;
4. o envio que perde o servidor no meio: pausa, nao recua para a instalacao;
5. que o e-mail do dia a dia **nao** foi afetado -- e o "nao quebrar" do
   pedido;
6. que a vitrine diz isso, a partir do catalogo.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
# A caixa em memoria, independentemente do ambiente: o roteiro confere o
# que saiu em `mail.outbox`.
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail
from django.core.mail import get_connection
from django.test import Client
from django.utils import timezone

from accounts.models import User
from communications import email as email_mod
from communications import marketing
from communications.models import (
    CampaignStatus, MarketingCampaign, MarketingRecipient, MessagingSettings, RecipientStatus,
)
from patients.models import Patient, PatientContact
from tenancy.models import Tenant
from tenancy.plans import PLANS, PlanCode

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
plano_original = tenant.plan
ms, _ = MessagingSettings.objects.get_or_create(tenant_id=tenant.id)
CAMPOS = ('email_enabled', 'email_from_name', 'email_from_address', 'smtp_host')
guardado = {f: getattr(ms, f) for f in CAMPOS}

# O host e ficticio: a conexao que ele abriria vira a caixa em memoria.
_conexao_original = email_mod._connection_for
email_mod._connection_for = lambda sender: (
    get_connection('django.core.mail.backends.locmem.EmailBackend')
    if sender is not None and sender.uses_own_server else None
)


def configura(enabled, host):
    ms.email_enabled = enabled
    ms.email_from_name = 'Clinica Demo A'
    ms.email_from_address = 'contato@clinica-demo.example.com'
    ms.smtp_host = host
    ms.save()


def cliente():
    c = Client()
    c.force_login(User.objects.get(email='doctor-a@demo.neurodoc.local'))
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


campanhas = []
contato = None
try:
    print('=== 1. "servidor proprio" e host, e nao so remetente ativo ===')
    for enabled, host, esperado, rotulo in [
        (False, '', False, 'desligado, sem host'),
        (True, '', False, 'ATIVO e sem host (sai pela instalacao)'),
        (False, 'smtp.x.example.com', False, 'com host, mas desligado'),
        (True, '   ', False, 'host so com espacos'),
        (True, 'smtp.x.example.com', True, 'ativo e com host'),
    ]:
        configura(enabled, host)
        confere(marketing.has_own_server(tenant.id) is esperado, rotulo)

    print('=== 2. o plano nao entra na conta ===')
    for plano in (PlanCode.FREE, PlanCode.BASIC, PlanCode.COMPLETE, PlanCode.CUSTOM):
        tenant.plan = plano
        tenant.save(update_fields=['plan'])
        configura(True, 'smtp.x.example.com')
        com = marketing.has_own_server(tenant.id)
        configura(True, '')
        sem = marketing.has_own_server(tenant.id)
        confere(com and not sem, f'{plano}: com servidor pode, sem servidor nao')
    tenant.plan = plano_original
    tenant.save(update_fields=['plan'])

    # Um contato que consentiu, para a fila nao ficar vazia: sem ele, as
    # assercoes de "nada saiu" passariam sobre uma lista que nunca teria
    # enviado coisa nenhuma.
    paciente = Patient.objects.filter(tenant=tenant).first()
    contato = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name='Contato servidor proprio',
        relationship='self', email='servidor-proprio@example.com', phone='',
        marketing_opt_in_at=timezone.now(),
        marketing_opt_in_evidence='roteiro check_campanha_servidor_proprio',
    )

    print('=== 3. sem servidor proprio: a area abre, explica, e nao envia ===')
    configura(True, '')
    c = cliente()
    r = c.get('/app/org/campanhas/')
    corpo = r.content.decode()
    confere(r.status_code == 200, 'a lista abre (200), em vez de esconder a funcionalidade',
            str(r.status_code))
    confere('Falta o servidor de e-mail da clínica' in corpo, 'a lista explica o que falta')
    confere('/app/org/campanhas/nova/' not in corpo, 'o botao "Nova campanha" some')

    r = c.get('/app/org/campanhas/nova/')
    confere(r.status_code == 302, 'GET de nova campanha e recusado', str(r.status_code))
    antes = MarketingCampaign.objects.filter(tenant=tenant).count()
    c.post('/app/org/campanhas/nova/', {
        'subject': 'Furando a tela', 'body_text': 'x', 'per_minute': '5'})
    confere(MarketingCampaign.objects.filter(tenant=tenant).count() == antes,
            'POST direto de nova campanha nao cria nada')

    # Campanha antiga, criada quando a regra era outra: continua legivel.
    antiga = MarketingCampaign.objects.create(
        tenant=tenant, subject='Rascunho anterior a regra', body_text='x', per_minute=5)
    campanhas.append(antiga)
    marketing.build_recipients(antiga)
    r = c.get(f'/app/org/campanhas/{antiga.id}/')
    corpo = r.content.decode()
    confere(r.status_code == 200, 'o rascunho antigo continua abrindo', str(r.status_code))
    confere(f'/app/org/campanhas/{antiga.id}/disparar/' not in corpo,
            'o botao de disparar some do rascunho')
    confere(f'/app/org/campanhas/{antiga.id}/testar/' not in corpo,
            'o envio de teste some do rascunho')

    mail.outbox = []
    c.post(f'/app/org/campanhas/{antiga.id}/testar/', {'to_email': 'teste@example.com'})
    confere(len(mail.outbox) == 0, 'POST direto do teste nao envia', f'{len(mail.outbox)} saiu')
    c.post(f'/app/org/campanhas/{antiga.id}/disparar/')
    antiga.refresh_from_db()
    confere(antiga.status == CampaignStatus.DRAFT, 'POST direto de disparar nao dispara',
            antiga.status)

    print('=== 4. pausar nunca depende de servidor ===')
    antiga.status = CampaignStatus.SENDING
    antiga.save(update_fields=['status'])
    c.post(f'/app/org/campanhas/{antiga.id}/pausar/')
    antiga.refresh_from_db()
    confere(antiga.status == CampaignStatus.PAUSED, 'pausar funciona sem servidor', antiga.status)

    print('=== 5. o servidor some no meio do envio: pausa, e nada vai pela instalacao ===')
    antiga.status = CampaignStatus.SENDING
    antiga.save(update_fields=['status'])
    mail.outbox = []
    resultado = marketing.send_batch(antiga)
    antiga.refresh_from_db()
    pendentes = antiga.recipients.filter(status=RecipientStatus.PENDING).count()
    confere(len(mail.outbox) == 0, 'nenhuma mensagem saiu', f'{len(mail.outbox)} saiu')
    confere(antiga.status == CampaignStatus.PAUSED, 'a campanha ficou pausada', antiga.status)
    confere(pendentes >= 1 and resultado.get('restantes') == pendentes,
            'os destinatarios continuam pendentes, e nao falhados', str(resultado))
    confere(not antiga.recipients.filter(status=RecipientStatus.FAILED).exists(),
            'ninguem foi marcado como falha')

    try:
        email_mod.send_email('x@example.com', 'a', 'b', tenant_id=tenant.id,
                             require_own_server=True)
        confere(False, 'send_email(require_own_server) recusa sem servidor')
    except email_mod.OwnServerRequired:
        confere(True, 'send_email(require_own_server) recusa sem servidor')

    print('=== 6. o e-mail do dia a dia nao mudou ===')
    for enabled, host, rotulo in [(False, '', 'sem configuracao (remetente do NeuroDoc)'),
                                  (True, '', 'remetente da clinica pelo servidor do NeuroDoc')]:
        configura(enabled, host)
        mail.outbox = []
        email_mod.send_email('paciente@example.com', 'Seu horario', 'texto', tenant_id=tenant.id)
        confere(len(mail.outbox) == 1, f'e-mail transacional sai: {rotulo}')

    print('=== 7. com servidor proprio, tudo volta ===')
    configura(True, 'smtp.x.example.com')
    r = c.get('/app/org/campanhas/')
    corpo = r.content.decode()
    confere('/app/org/campanhas/nova/' in corpo, 'o botao "Nova campanha" aparece')
    confere('Falta o servidor de e-mail da clínica' not in corpo, 'o aviso some')
    c.post('/app/org/campanhas/nova/', {
        'subject': 'Com servidor proprio', 'body_text': 'x', 'per_minute': '5'})
    nova = MarketingCampaign.objects.filter(tenant=tenant, subject='Com servidor proprio').first()
    campanhas.append(nova)
    confere(nova is not None, 'a campanha e criada')
    mail.outbox = []
    c.post(f'/app/org/campanhas/{nova.id}/testar/', {'to_email': 'teste@example.com'})
    confere(len(mail.outbox) == 1, 'o envio de teste sai', f'{len(mail.outbox)} saiu')
    antiga.status = CampaignStatus.SENDING
    antiga.save(update_fields=['status'])
    mail.outbox = []
    marketing.send_batch(antiga)
    confere(antiga.recipients.filter(status=RecipientStatus.SENT).exists() and mail.outbox,
            'a campanha pausada, retomada com servidor, envia')

    print('=== 8. a vitrine diz isso, a partir do catalogo ===')
    gratis = ' | '.join(PLANS[PlanCode.FREE]['features']).lower()
    confere('campanhas' in gratis and 'servidor' in gratis,
            'o Gratuito anuncia campanhas com o servidor da clinica')
    confere('e-mail' in gratis, 'o Gratuito anuncia os avisos por e-mail')
    completo = ' | '.join(PLANS[PlanCode.COMPLETE]['features']).lower()
    confere('massa' not in completo and 'campanha' not in completo,
            'o Completo deixou de vender campanha como exclusividade dele')
    pagina = Client().get('/').content.decode()
    for trecho, oquee in [
        ('NeuroDoc ou o seu', 'a linha de e-mail no cartao'),
        ('e-mail do NeuroDoc', 'que o Gratuito usa o e-mail do NeuroDoc'),
        ('servidor de e-mail da sua clínica', 'que o Gratuito pode usar o servidor da clinica'),
        ('todos os planos', 'que campanha esta em todos os planos'),
        ('servidor de e-mail da própria clínica', 'que campanha exige o servidor da clinica'),
    ]:
        confere(trecho in pagina, f'a pagina de vendas diz {oquee}', trecho)
    confere(pagina.count('NeuroDoc ou o seu') == len(PLANS),
            'a linha de e-mail aparece em todos os cartoes',
            f'{pagina.count("NeuroDoc ou o seu")} de {len(PLANS)}')
finally:
    for camp in campanhas:
        if camp is None:
            continue
        MarketingRecipient.objects.filter(campaign=camp).delete()
        MarketingCampaign.objects.filter(id=camp.id).delete()
    if contato is not None:
        MarketingRecipient.objects.filter(contact=contato).delete()
        PatientContact.objects.filter(id=contato.id).delete()
    for f, v in guardado.items():
        setattr(ms, f, v)
    ms.save()
    tenant.plan = plano_original
    tenant.save(update_fields=['plan'])
    email_mod._connection_for = _conexao_original

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: campanha so pelo servidor da clinica, em qualquer plano.')
