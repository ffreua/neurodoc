"""O SMS segue o plano contratado, como a IA ja seguia.

SMS custa dinheiro por mensagem, e a clinica que nao configurou chave
propria gasta a **da instalacao** -- quem hospeda o sistema paga a conta de
quem usa. A IA ja era recurso de plano; o SMS nao era, e uma clinica no
Gratuito, que nao paga nada, consumia os creditos de quem hospeda. O
sintoma chega como "os lembretes pararam de sair", sem dizer por que.

O corte mora em **dois lugares**, e os dois sao necessarios:

1. `smsdev.resolve_api_key` -- o ponto por onde passa todo SMS: lembrete de
   consulta, codigo de acesso a documento e consulta de saldo. Os dois
   primeiros nascem de evento e de tarefa do worker, sem tela nenhuma;
2. a tela de mensageria, para a clinica nao cadastrar chave, apertar
   "testar" e ficar procurando defeito no proprio celular.

O que este roteiro cobra, e que e onde da errado:

- o Gratuito e recusado **antes** da leitura da chave da clinica -- o corte
  e por plano e vale inclusive para quem trouxe a propria chave;
- do Basico para cima passa;
- a recusa e `SmsChannelDisabled`, e nao um erro generico: e o que o
  chamador ja sabe tratar sem derrubar a tarefa;
- a linha de venda do Basico anuncia o SMS, porque o que se anuncia e o que
  o servidor cumpre moram no mesmo arquivo;
- a tela recusa gravar e diz em que plano o recurso entra.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from communications.models import MessagingSettings
from communications.smsdev import SmsChannelDisabled, resolve_api_key
from tenancy.models import Membership, Tenant
from tenancy.plans import PlanCode, has_sms, plan_config

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


print('\n1. O catalogo de planos')
conferir('Gratuito NAO tem SMS', has_sms(PlanCode.FREE), False)
conferir('Basico tem', has_sms(PlanCode.BASIC), True)
conferir('Completo tem', has_sms(PlanCode.COMPLETE), True)
conferir('Personalizado tem', has_sms(PlanCode.CUSTOM), True)
conferir('plano desconhecido fica SEM (erra para o menor direito)',
         has_sms('plano-que-nao-existe'), False)

print('\n2. A linha de venda diz o mesmo que o servidor cumpre')
vitrine_basico = ' | '.join(plan_config(PlanCode.BASIC)['features']).lower()
vitrine_free = ' | '.join(plan_config(PlanCode.FREE)['features']).lower()
conferir('o Basico anuncia SMS', 'sms' in vitrine_basico, True)
conferir('o Gratuito nao anuncia SMS', 'sms' in vitrine_free, False)

print('\n3. O gate por onde passa TODO envio')
tenant = Tenant.objects.get(slug='demo-clinica-a')
plano_original = tenant.plan
linha = MessagingSettings.objects.filter(tenant=tenant).first()
chave_original = linha.sms_api_key_ciphertext if linha else None

try:
    tenant.plan = PlanCode.FREE
    tenant.save(update_fields=['plan'])
    try:
        resolve_api_key(tenant.id)
        conferir('Gratuito e recusado', 'passou', 'SmsChannelDisabled')
    except SmsChannelDisabled as exc:
        conferir('Gratuito e recusado', type(exc).__name__, 'SmsChannelDisabled')
        conferir('a recusa explica o motivo', 'plano' in str(exc).lower(), True)

    # A parte que a leitura de codigo nao pega: o corte tem de vir ANTES de
    # olhar a chave da clinica. Depois dela, a clinica do Gratuito que
    # cadastrou chave propria passaria -- e o recurso apareceria ou sumiria
    # conforme a credencial, o que e impossivel de explicar na pagina de
    # precos.
    if linha is None:
        linha = MessagingSettings.objects.create(tenant=tenant)
    linha.sms_api_key_ciphertext = 'fingindo-uma-chave-cifrada'
    linha.sms_enabled = True
    linha.save(update_fields=['sms_api_key_ciphertext', 'sms_enabled'])
    try:
        resolve_api_key(tenant.id)
        conferir('Gratuito COM chave propria tambem e recusado', 'passou', 'SmsChannelDisabled')
    except SmsChannelDisabled:
        conferir('Gratuito COM chave propria tambem e recusado', 'recusado', 'recusado')
    except Exception as exc:
        conferir('Gratuito COM chave propria tambem e recusado',
                 f'{type(exc).__name__} (errado)', 'recusado')

    print('\n4. Do Basico para cima, passa')
    linha.sms_api_key_ciphertext = ''
    linha.save(update_fields=['sms_api_key_ciphertext'])
    for codigo in [PlanCode.BASIC, PlanCode.COMPLETE, PlanCode.CUSTOM]:
        tenant.plan = codigo
        tenant.save(update_fields=['plan'])
        try:
            resolve_api_key(tenant.id)
            conferir(f'{codigo} chega na chave da instalacao', 'passou', 'passou')
        except SmsChannelDisabled as exc:
            # Sem chave nenhuma configurada a recusa e outra, e ela nao
            # pode falar em plano -- senao a mensagem manda a clinica
            # contratar o que ela ja contratou.
            ok = 'plano' not in str(exc).lower()
            conferir(f'{codigo} nao e barrado pelo plano', ok, True)

    print('\n5. A tela recusa gravar, e diz em que plano o recurso entra')
    tenant.plan = PlanCode.FREE
    tenant.save(update_fields=['plan'])
    vinculo = Membership.objects.filter(
        tenant=tenant, roles__contains=['owner'],
    ).first() or Membership.objects.filter(tenant=tenant).first()
    c = Client()
    c.force_login(vinculo.user)
    sessao = c.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()
    resposta = c.get('/app/org/mensageria/')
    corpo = resposta.content.decode('utf-8', 'replace')
    conferir('a tela abre', resposta.status_code, 200)
    conferir('diz que o plano nao inclui', 'nao inclui envio de SMS' in corpo, True)
    conferir('diz a partir de qual plano entra', 'Basico' in corpo, True)
    conferir('nao oferece o formulario', 'messaging:save-sms' in corpo or 'save-sms' in corpo, False)

    antes = MessagingSettings.objects.filter(tenant=tenant).first()
    marca = antes.sms_api_key_hint if antes else ''
    resposta = c.post('/app/org/mensageria/sms/', {
        'api_key': 'CHAVE-QUE-NAO-DEVE-SER-GRAVADA', 'sms_enabled': 'on',
    })
    depois = MessagingSettings.objects.filter(tenant=tenant).first()
    conferir('o POST direto nao grava', depois.sms_api_key_hint if depois else '', marca)

finally:
    tenant.plan = plano_original
    tenant.save(update_fields=['plan'])
    if linha is not None and chave_original is not None:
        linha.sms_api_key_ciphertext = chave_original
        linha.save(update_fields=['sms_api_key_ciphertext'])
    print(f'\n  plano da clinica de demonstracao restaurado para {plano_original}')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o SMS segue o plano, o corte vem antes da chave da clinica,')
print('    e a tela explica em vez de aceitar uma chave que nunca enviaria nada.')
