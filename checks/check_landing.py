"""A pagina de vendas anuncia o que o sistema cumpre, e o contato nao se perde?

Tenta quebrar. As perguntas sao:

- os limites anunciados sao os do catalogo, ou numeros escritos no template?
- o lead e gravado antes do e-mail, e sobrevive ao SMTP fora?
- o campo-armadilha barra robo sem gravar nada?
- o destinatario e fixo no servidor, ou vem do formulario?
- a pagina promete alguma coisa que nao existe?
- a tela de leads do console abre so com MFA?
"""
import re
from unittest import mock

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# A caixa em memoria, independentemente do que o ambiente diga.
#
# Este roteiro afirma sobre `mail.outbox`, que so existe no backend
# `locmem`. Com o envio ligado (Mailpit no ambiente local), o backend
# padrao passa a ser o que enfileira, a caixa fica vazia e o roteiro
# falharia por configuracao do ambiente -- nao por regressao.
#
# `send_mail` le `EMAIL_BACKEND` a cada chamada, entao fixar aqui basta.
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'


from django.core import mail
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from base.content import FAQ, RECURSOS
from tenancy import leads as leads_service
from tenancy.models import Lead
from tenancy.plans import PLANS, PUBLIC_ORDER

falhas = []
Lead.objects.filter(email__endswith='@check.invalid').delete()


def zerar_limite():
    """Limpa o contador por IP deste roteiro.

    O limite vive no Redis por 15 minutos, e o cliente de teste sempre sai
    do mesmo IP. Sem zerar, a segunda execucao dentro da janela comeca ja
    no teto: a secao da armadilha responderia 429 em vez de 400, e o
    roteiro acusaria um defeito que nao existe -- o pior tipo de falha num
    roteiro de regressao, porque manda procurar no lugar errado.
    """
    from django.core.cache import cache

    for ip in ['127.0.0.1', 'testserver', 'desconhecido']:
        cache.delete(f'leads:{ip}')


zerar_limite()

print('=== 1. os limites anunciados sao os do catalogo ===')
publica = Client().get('/')
corpo = publica.content.decode()
print(f'  GET / -> {publica.status_code}')
if publica.status_code != 200:
    falhas.append('a pagina de vendas nao abriu')
for code in PUBLIC_ORDER:
    cfg = PLANS[code]
    if cfg['max_patients'] is None:
        presente = 'ilimitado' in corpo
        print(f'  {cfg["label"]:14} ilimitado presente={presente}')
    else:
        presente = f'até {cfg["max_patients"]}' in corpo
        print(f'  {cfg["label"]:14} "ate {cfg["max_patients"]}" presente={presente}')
    if not presente:
        falhas.append(f'{code}: o limite do catalogo nao aparece na pagina')

print('=== 2. numero de plano escrito a mao no template? ===')
# Se alguem escrever um limite no HTML, ele sobrevive a mudanca do catalogo.
with mock.patch.dict(PLANS[PUBLIC_ORDER[0]], {'max_patients': 7}):
    outra = Client().get('/').content.decode()
mudou = 'até 7' in outra
print(f'  catalogo alterado para 7 -> pagina mostra "ate 7"={mudou}')
if not mudou:
    falhas.append('a pagina nao segue o catalogo: o numero esta escrito no template')

print('=== 3. o lead e gravado, e o destinatario e do servidor ===')
mail.outbox = []
antes = Lead.objects.count()
c = Client()
c.get('/')
r = c.post('/', {
    'action': 'lead', 'name': 'Dra Check', 'email': 'lead@check.invalid',
    'phone': '(11) 98888-7777', 'clinic_name': 'Clinica Check',
    'plan': 'complete', 'message': 'Tres medicos',
})
lead = Lead.objects.order_by('-created_at').first()
print(f'  POST -> {r.status_code}  leads {antes} -> {Lead.objects.count()}')
print(f'  telefone normalizado={lead.phone!r}  plano={lead.plan}  ip={lead.source_ip}')
print(f'  versao do aviso de privacidade={lead.privacy_notice_version!r}')
if Lead.objects.count() != antes + 1:
    falhas.append('o pedido de contato nao foi gravado')
if lead.phone != '11988887777':
    falhas.append(f'telefone nao normalizado: {lead.phone!r}')
if not lead.privacy_notice_version:
    falhas.append('o lead nao guardou a versao do aviso de privacidade')
if mail.outbox:
    destinos = mail.outbox[-1].to
    print(f'  e-mail enviado para={destinos}')
    if destinos != [dj_settings.LEADS_EMAIL]:
        falhas.append(f'o aviso foi para {destinos}, nao para LEADS_EMAIL')
else:
    falhas.append('nenhum e-mail de aviso foi gerado')

print('=== 4. o destinatario nao vem do formulario ===')
zerar_limite()
mail.outbox = []
c2 = Client()
c2.get('/')
c2.post('/', {
    'action': 'lead', 'name': 'Relay Check', 'email': 'relay@check.invalid',
    'to': 'vitima@exemplo.invalid', 'to_email': 'vitima@exemplo.invalid',
    'recipient': 'vitima@exemplo.invalid',
})
destinos = mail.outbox[-1].to if mail.outbox else []
print(f'  campos "to"/"recipient" enviados -> e-mail foi para {destinos}')
if any('vitima' in d for d in destinos):
    falhas.append('o formulario publico aceitou destinatario do cliente: relay aberto')

print('=== 5. o campo-armadilha barra robo sem gravar ===')
zerar_limite()
antes = Lead.objects.count()
c3 = Client()
c3.get('/')
r = c3.post('/', {
    'action': 'lead', 'name': 'Robo', 'email': 'robo@check.invalid',
    'website': 'http://spam.example',
})
print(f'  POST com armadilha -> {r.status_code}  leads criados={Lead.objects.count() - antes}')
# A mensagem e generica de proposito: dizer "isto parece um robo" ensina o
# robo qual campo evitar na proxima tentativa. Confere o texto exato, e nao
# a ausencia da palavra na pagina -- o nome enviado volta ecoado no campo.
generica = 'Nao foi possivel enviar o formulario' in r.content.decode().replace('ã', 'a').replace('í', 'i').replace('á', 'a').replace('é', 'e')
print(f'  mensagem generica, sem entregar o truque={generica}')
if not generica:
    falhas.append('a recusa da armadilha nao usou a mensagem generica')
if Lead.objects.count() != antes:
    falhas.append('o robo conseguiu gravar um lead')
if r.status_code != 400:
    falhas.append(f'a armadilha respondeu {r.status_code}, esperado 400')

print('=== 6. SMTP fora nao perde o lead ===')
zerar_limite()
antes = Lead.objects.count()
with mock.patch('communications.email.send_email', side_effect=RuntimeError('SMTP fora')):
    c4 = Client()
    c4.get('/')
    r = c4.post('/', {
        'action': 'lead', 'name': 'Falha Check', 'email': 'falha@check.invalid',
    })
perdido = Lead.objects.count() == antes
lead_falho = Lead.objects.filter(email='falha@check.invalid').first()
sucesso_na_tela = 'Recebemos' in r.content.decode()
print(f'  POST -> {r.status_code}  lead gravado={not perdido}  erro registrado={bool(lead_falho.notify_error)}')
print(f'  a tela ainda diz sucesso={sucesso_na_tela}')
print(f'  erro guardado: {lead_falho.notify_error[:60]}')
if perdido:
    falhas.append('SMTP fora perdeu o lead')
if not sucesso_na_tela:
    falhas.append('a tela mandou a pessoa reenviar um pedido que ja chegou')
if not lead_falho.notify_error:
    falhas.append('a falha de envio nao ficou registrada em lugar nenhum')

print('=== 7. plano adulterado nao derruba o envio ===')
zerar_limite()
c5 = Client()
c5.get('/')
r = c5.post('/', {
    'action': 'lead', 'name': 'Plano Check', 'email': 'plano@check.invalid',
    'plan': 'ouro-premium-inexistente',
})
gravado = Lead.objects.filter(email='plano@check.invalid').first()
print(f'  POST -> {r.status_code}  gravado={gravado is not None}  plano={gravado.plan!r} (vazio esperado)')
if gravado is None or gravado.plan != '':
    falhas.append('plano adulterado nao virou vazio')

print('=== 8. limite por IP ===')
zerar_limite()
c6 = Client()
c6.get('/')
bloqueou = False
for i in range(leads_service.RATE_LIMIT + 2):
    r = c6.post('/', {'action': 'lead', 'name': f'Flood {i}', 'email': f'flood{i}@check.invalid'})
    if r.status_code == 429:
        bloqueou = True
        break
print(f'  apos {leads_service.RATE_LIMIT} pedidos -> bloqueou={bloqueou}')
if not bloqueou:
    falhas.append('o limite por IP nao barrou o excesso')

print('=== 9. a pagina nao promete o que nao existe ===')
proibidos = ['teleconsulta', 'TISS', 'DICOM', 'PACS']
achados = [p for p in proibidos if p.lower() in ' '.join(
    r['titulo'] + ' ' + r['texto'] for r in RECURSOS).lower()]
print(f'  recursos anunciados={len(RECURSOS)}  promessas fora de escopo={achados or "nenhuma"}')
if achados:
    falhas.append(f'a lista de recursos anuncia o que esta fora de escopo: {achados}')
diagnostico = [r for r in RECURSOS if 'diagn' in r['texto'].lower() and 'revis' not in r['texto'].lower()]
if diagnostico:
    falhas.append('a pagina descreve a IA como diagnostico sem mencionar revisao medica')
print(f'  perguntas no FAQ={len(FAQ)}')
if len(FAQ) < 5:
    falhas.append('o FAQ ficou curto demais para servir')

print('=== 9b. o preco da pagina fecha com a conta ===')
# A pagina mostra o anual e diz a quanto equivale por mes. Sao dois
# numeros que precisam concordar -- e a forma de eles divergirem e alguem
# escrever o anual a mao depois de mudar o mensal.
from tenancy.plans import (
    DESCONTO_PROMOCIONAL, MESES_NO_ANO, PLANS, PUBLIC_ORDER, brl, pricing,
    plan_choices, sem_desconto,
)

corpo_landing = Client().get('/').content.decode()
for code in PUBLIC_ORDER:
    preco = pricing(code)
    centavos = PLANS[code].get('price_monthly')
    if not preco['quoted'] or preco['free']:
        continue
    esperado_anual = brl(centavos * MESES_NO_ANO)
    confere = preco['annual'] == esperado_anual
    na_pagina = preco['annual'] in corpo_landing and preco['monthly'] in corpo_landing
    print(f'  {str(code):10} {preco["monthly"]}/mes -> {preco["annual"]}/ano  '
          f'conta_fecha={confere}  na_pagina={na_pagina}')
    if not confere:
        falhas.append(f'{code}: o anual anunciado nao e o mensal vezes {MESES_NO_ANO}')
    if not na_pagina:
        falhas.append(f'{code}: o preco nao aparece na pagina de vendas')

print('=== 9b-bis. o desconto anunciado e o desconto de verdade ===')
# Anunciar "20% de desconto" com um preco de tabela que da outra conta e
# propaganda enganosa, nao erro de arredondamento: quem le tem os dois
# numeros na tela e consegue fazer a subtracao. Este bloco faz a mesma
# subtracao antes do cliente.
print(f'  desconto declarado no catalogo: {DESCONTO_PROMOCIONAL}%')
if DESCONTO_PROMOCIONAL:
    if f'{DESCONTO_PROMOCIONAL}% de desconto' not in corpo_landing:
        falhas.append('a pagina nao diz de quanto e o desconto')
    for code in PUBLIC_ORDER:
        preco = pricing(code)
        centavos = PLANS[code].get('price_monthly')
        if not preco.get('promo'):
            continue
        tabela_mensal = sem_desconto(centavos)
        # A conta pela qual o leitor julga o anuncio: tirar o percentual do
        # preco de tabela tem de devolver exatamente o que se cobra.
        cobrado_esperado = round(tabela_mensal * (100 - DESCONTO_PROMOCIONAL) / 100)
        fecha = cobrado_esperado == centavos
        anual_coerente = preco['list_annual'] == brl(tabela_mensal * MESES_NO_ANO)
        economia_certa = preco['saving_annual'] == brl(
            tabela_mensal * MESES_NO_ANO - centavos * MESES_NO_ANO)
        riscado_na_pagina = (preco['list_annual'] in corpo_landing
                             and preco['list_monthly'] in corpo_landing)
        print(f'  {str(code):10} de {preco["list_monthly"]}/mes por {preco["monthly"]}/mes  '
              f'-{DESCONTO_PROMOCIONAL}% fecha={fecha}  anual_coerente={anual_coerente}  '
              f'economia={preco["saving_annual"]} ok={economia_certa}  '
              f'riscado_na_pagina={riscado_na_pagina}')
        if not fecha:
            falhas.append(
                f'{code}: {DESCONTO_PROMOCIONAL}% sobre o preco de tabela dao '
                f'{brl(cobrado_esperado)}, e a pagina cobra {preco["monthly"]}')
        if not anual_coerente:
            falhas.append(f'{code}: o anual riscado nao e o mensal riscado vezes {MESES_NO_ANO}')
        if not economia_certa:
            falhas.append(f'{code}: a economia anunciada nao e a diferenca dos dois anuais')
        if not riscado_na_pagina:
            falhas.append(f'{code}: o preco de tabela nao aparece na pagina')
        # O riscado precisa ser MAIOR que o cobrado. Um desconto negativo
        # passaria em toda a aritmetica acima e anunciaria um aumento.
        if tabela_mensal <= centavos:
            falhas.append(f'{code}: o preco "de" nao e maior que o "por"')
else:
    print('  promocao desligada -- a pagina nao deve mostrar valor riscado')
    if '<s>' in corpo_landing:
        falhas.append('a promocao esta desligada e a pagina ainda risca um preco')

# Gratuito e Personalizado sao os dois casos que nao sao "um preco".
gratuito = pricing('free')
personalizado = pricing('custom')
print(f'  gratuito e gratis={gratuito["free"]}  personalizado sem tabela={not personalizado["quoted"]}')
if not gratuito['free']:
    falhas.append('o plano Gratuito deixou de ser gratuito')
if personalizado['quoted']:
    falhas.append('o Personalizado ganhou preco de tabela: ele e combinado caso a caso')
if 'Sob medida' not in corpo_landing:
    falhas.append('a pagina nao diz que o Personalizado tem valores a combinar')

# A regra de cobranca precisa estar escrita onde o preco e lido.
for trecho in ['uma vez por ano', 'plano Gratuito']:
    if trecho not in corpo_landing:
        falhas.append(f'a pagina nao explica: {trecho!r}')
print(f'  explica cobranca anual={"uma vez por ano" in corpo_landing}  '
      f'convida ao gratuito={"plano Gratuito" in corpo_landing}')

print('=== 9c. o menu de plano do formulario ===')
# Todo plano publico tem de aparecer no menu: acrescentar um plano e
# esquecer o menu deixaria o lead sem como pedir o que acabou de ler.
opcoes = dict(plan_choices())
faltando = [str(c) for c in PUBLIC_ORDER if str(c) not in opcoes]
print(f'  opcoes={len(opcoes)}  planos ausentes={faltando or "nenhum"}')
if faltando:
    falhas.append(f'planos fora do menu de contato: {faltando}')
if 'id="id_plan"' not in corpo_landing:
    falhas.append('o formulario nao tem o menu de plano')
print(f'  menu renderizado na pagina={"id_plan" in corpo_landing}')

print('=== 10. a tela de leads do console exige MFA ===')
def superadmin_descartavel():
    """Um superadministrador **do roteiro**, nunca a conta de uma pessoa.

    `force_login` grava `last_login`, e `last_login` entra no hash de
    `default_token_generator`: logar numa conta invalida o link de
    definicao de senha pendente dela. Pegar "o primeiro superusuario"
    funcionava enquanto havia contas de teste no banco; num banco limpo,
    a unica conta com `is_superuser` e a de quem opera o sistema -- e o
    roteiro passava a derrubar o link dessa pessoa.
    """
    from accounts.models import User as _User
    from django.utils import timezone as _tz

    conta, criada = _User.objects.get_or_create(
        email='check-superadmin@example.invalid',
        defaults={'is_active': True, 'is_staff': True, 'is_superuser': True},
    )
    if criada:
        conta.set_password('CheckS3nha!2026')
    conta.is_staff = True
    conta.is_superuser = True
    conta.is_active = True
    conta.email_verified_at = conta.email_verified_at or _tz.now()
    conta.save()
    return conta


superadmin = superadmin_descartavel()
sem_mfa = Client()
sem_mfa.force_login(superadmin)
r = sem_mfa.get('/instalacao/leads/')
print(f'  sem MFA -> {r.status_code} (404 esperado)')
if r.status_code != 404:
    falhas.append('a tela de leads abriu sem MFA')

device = TOTPDevice.objects.filter(user=superadmin, confirmed=True).first()
criou = False
if device is None:
    device = TOTPDevice.objects.create(user=superadmin, name='check', confirmed=True)
    criou = True
com_mfa = Client()
com_mfa.force_login(superadmin)
s = com_mfa.session
s['otp_device_id'] = device.persistent_id
s.save()
r = com_mfa.get('/instalacao/leads/')
mostra = 'lead@check.invalid' in r.content.decode()
print(f'  com MFA -> {r.status_code}  lista o pedido={mostra}')
if r.status_code != 200 or not mostra:
    falhas.append('a tela de leads nao mostrou os pedidos para quem pode ve-los')
if criou:
    device.delete()

Lead.objects.filter(email__endswith='@check.invalid').delete()

print('---')
if falhas:
    for line in falhas:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: a pagina anuncia o catalogo, e o pedido de contato nao se perde.')
