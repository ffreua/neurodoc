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
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e este roteiro passaria a
# medir o redirecionamento em vez do que veio conferir -- com todas as
# assercoes falhando por 301, o que parece defeito na pagina. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False
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
codigo_aberto = all(trecho in corpo for trecho in [
    'Open Source', 'licença MIT', 'fernando.freua@hc.fm.usp.br',
    'mailto:fernando.freua@hc.fm.usp.br',
])
print(f'  Open Source, MIT e contato para GitHub presentes={codigo_aberto}')
if not codigo_aberto:
    falhas.append('a landing nao explica o acesso Open Source sob MIT e como solicitar o GitHub')
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

print('=== 11. o plano Gratuito comeca sozinho, e so ele ===')
#
# O cartao do Gratuito posta e leva direto a criacao da clinica; os pagos
# continuam rolando ate o formulario. A diferenca importa nos dois
# sentidos: um caminho automatico nos planos pagos pularia a conversa
# comercial, e o formulario no Gratuito e a porta onde as pessoas
# desistem sem nunca aparecer como contato.
from tenancy.models import Invitation, InvitationPurpose
from tenancy.plans import PlanCode

zerar_limite()


def _zerar_gratis():
    """O limite do botao vive no Redis, como o do formulario -- e pelo mesmo
    motivo precisa ser zerado aqui: o cliente de teste sai sempre do mesmo
    IP, e a segunda execucao dentro da hora comecaria no teto."""
    from django.core.cache import cache

    for ip in ('127.0.0.1', 'testserver', 'desconhecido'):
        cache.delete(f'plano-gratis:{ip}')


_zerar_gratis()
_c = Client()
_c.get('/')
# Marco de tempo para a limpeza do fim: apagar "todo convite gratuito sem
# emissor" varreria tambem os que este roteiro emitiu em rodadas
# anteriores -- e, num banco que nao fosse o de demonstracao, os que
# visitantes de verdade emitiram pelo botao.
from django.utils import timezone as _tz

_marco = _tz.now()
_antes = Invitation.objects.count()
_r = _c.post('/comecar-gratis/', {})
_destino = _r.get('Location', '')
print(f'  POST /comecar-gratis/ -> HTTP {_r.status_code} {_destino[:38]}')
if _r.status_code != 302 or '/signup/' not in _destino:
    falhas.append('o botao do plano Gratuito nao levou a criacao da clinica')

_convite = Invitation.objects.order_by('-created_at').first()
_horas = round((_convite.expires_at - _convite.created_at).total_seconds() / 3600)
print(f'  convite: plano={_convite.plan} proposito={_convite.purpose} '
      f'validade={_horas}h emitido_por={_convite.issued_by}')
if _convite.plan != PlanCode.FREE or _convite.purpose != InvitationPurpose.PLATFORM:
    falhas.append('o convite automatico saiu com plano ou proposito errado')

# A tela de destino precisa dizer o que esta sendo criado: quem clicou
# escolheu um plano na tela anterior e tem de reconhece-lo aqui.
_corpo_signup = _c.get(_destino).content.decode(errors='replace')
_diz_o_plano = 'Gratuito' in _corpo_signup
print(f'  a tela de cadastro diz o plano: {_diz_o_plano}')
if not _diz_o_plano:
    falhas.append('a tela de criacao da clinica nao diz em que plano ela nasce')

# GET nao emite: um `<img src>` numa pagina de terceiro faria cada
# visitante dela gerar um convite.
_n = Invitation.objects.count()
_rg = _c.get('/comecar-gratis/')
print(f'  GET nao emite: {Invitation.objects.count() == _n} (HTTP {_rg.status_code})')
if Invitation.objects.count() != _n:
    falhas.append('um GET em /comecar-gratis/ emitiu convite')

# Campo-armadilha.
_n = Invitation.objects.count()
_c.post('/comecar-gratis/', {'website': 'http://robo.invalid'})
print(f'  campo-armadilha nao emite: {Invitation.objects.count() == _n}')
if Invitation.objects.count() != _n:
    falhas.append('o campo-armadilha nao barrou a emissao automatica')

# Limite por IP, e o excedente com caminho -- e nao um erro.
_zerar_gratis()
_emitidos = 0
for _ in range(6):
    _rr = _c.post('/comecar-gratis/', {})
    if '/signup/' in _rr.get('Location', ''):
        _emitidos += 1
_excedente = _c.post('/comecar-gratis/', {}).get('Location', '')
print(f'  seis cliques -> {_emitidos} convite(s); excedente vai para {_excedente[:24]}')
if _emitidos > 3:
    falhas.append(f'o limite por IP deixou passar {_emitidos} convites')
if '#contato' not in _excedente:
    falhas.append('quem estourou o limite nao foi levado ao formulario')

# E os pagos continuam como eram.
_corpo = Client().get('/').content.decode(errors='replace')
_pagos = _corpo.count('href="#contato" data-nd-plan')
print(f'  planos que continuam indo ao formulario: {_pagos} (esperado 3)')
if _pagos != 3:
    falhas.append(f'{_pagos} planos apontam para o formulario, e deveriam ser 3')
if 'onboarding:start-free' in _corpo or _corpo.count('/comecar-gratis/') != 1:
    falhas.append('o botao do plano gratuito aparece mais de uma vez na pagina')

_meus = Invitation.objects.filter(
    created_at__gte=_marco, issued_by__isnull=True,
    consumed_at__isnull=True, plan=PlanCode.FREE,
)
print(f'  convites emitidos por este roteiro, removidos: {_meus.count()}')
_meus.delete()
if Invitation.objects.count() != _antes:
    falhas.append('a limpeza do roteiro nao devolveu a contagem de convites')

print('=== 12. o texto da pagina esta acentuado ===')
# A lista e curta de proposito: sao as palavras que aparecem em quase todo
# texto clinico do produto, e que denunciam um arquivo escrito sem
# acentuacao. Uma so delas sem acento significa um bloco inteiro copiado
# de onde nao havia.
from base.content import FAQ as _FAQ, RECURSOS as _REC

_sem_acento = [
    'neurologico', 'prontuario', 'medico', 'assinatura digital automatica',
    'pontuacao', 'arvore', 'verificacao', 'inteligencia', 'privacidade nao',
    'nao ', 'sao ', 'voce', 'ja esta', 'vinculo', 'codigo', 'orgao',
]
_texto = ' '.join(
    [r['titulo'] + ' ' + r['texto'] for r in _REC]
    + [f['pergunta'] + ' ' + f['resposta'] for f in _FAQ]
).lower()
_achados = sorted({p.strip() for p in _sem_acento if p in _texto})
print(f'  palavras sem acento em RECURSOS/FAQ: {_achados or "nenhuma"}')
if _achados:
    falhas.append(f'texto sem acentuacao em base/content.py: {_achados}')

_defensivo = [t for t in ['O que está pronto', 'Nada aqui é promessa'] if t in _corpo]
print(f'  titulo defensivo na pagina: {_defensivo or "nenhum"}')
if _defensivo:
    falhas.append(f'a pagina voltou ao tom defensivo: {_defensivo}')

Lead.objects.filter(email__endswith='@check.invalid').delete()

print('=== 13. a senha do cadastro e digitada duas vezes ===')
#
# E a unica senha do sistema que nao tem recuperacao no minuto seguinte:
# quem a cria esta criando **junto** a conta e a clinica, e um erro de
# digitacao tranca a pessoa fora de uma organizacao que acabou de nascer,
# com o e-mail de recuperacao indo para o endereco que ela tambem acabou
# de digitar.
from tenancy.models import Tenant as _Tenant

_zerar_gratis()
_cs = Client()
_cs.get('/')
_destino = _cs.post('/comecar-gratis/', {})['Location']
_corpo_cad = _cs.get(_destino).content.decode(errors='replace')
_tem_confirmacao = 'password_confirm' in _corpo_cad and 'Confirme a senha' in _corpo_cad
print(f'  o formulario pede confirmacao: {_tem_confirmacao}')
if not _tem_confirmacao:
    falhas.append('o cadastro da clinica nao pede confirmacao de senha')


def _cnpj_para_teste(base):
    def dv(numeros, pesos):
        resto = sum(a * b for a, b in zip(numeros, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    n = [int(x) for x in base]
    d1 = dv(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(n + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(d2)


_antes_org = _Tenant.objects.count()
_r = _cs.post(_destino, {
    'email': 'check-confirmacao@example.invalid',
    'password': 'S3nhaForte!2026', 'password_confirm': 'S3nhaDiferente!2026',
    'legal_name': 'Clinica do Roteiro de Senha', 'trade_name': 'Roteiro',
    'cnpj': _cnpj_para_teste('998877665544'),
})
_criou = _Tenant.objects.count() - _antes_org
_avisou = 'As duas senhas' in _r.content.decode(errors='replace')
print(f'  senhas diferentes -> HTTP {_r.status_code}, organizacoes criadas={_criou}, avisa={_avisou}')
if _criou or not _avisou:
    falhas.append('o cadastro aceitou senha e confirmacao diferentes')

print('---')
print('IA e SMS: a pagina diz o que cada plano tem, inclusive o que NAO tem')
# A lista de itens de um plano so acrescenta linhas, e "nao tem" nao se
# anuncia acrescentando linha. Quem compara quatro cartoes lado a lado
# precisa ver o ausente na mesma posicao do presente -- senao conclui que
# tem, e descobre depois de contratar.
from tenancy.plans import PlanCode, has_clinical_ai, has_sms

_pagina = _c.get('/').content.decode(errors='replace')
for _rotulo, _quantos in [('não incluída', 1), ('não incluído', 1)]:
    _achou = _pagina.count(_rotulo)
    print(f'  "{_rotulo}" aparece {_achou}x')
    if _achou < _quantos:
        falhas.append(f'a vitrine nao marca "{_rotulo}" em plano nenhum')
if 'incluída' not in _pagina or 'incluído' not in _pagina:
    falhas.append('a vitrine nao marca o que esta incluido')

# O numero de "nao incluida/o" tem de bater com o catalogo: se um plano
# ganhar IA amanha e a pagina continuar dizendo que nao tem, a divergencia
# entre venda e produto volta -- que e o que `plans.py` existe para impedir.
_sem_ia = sum(1 for _p in [PlanCode.FREE, PlanCode.BASIC, PlanCode.COMPLETE, PlanCode.CUSTOM]
              if not has_clinical_ai(_p))
_sem_sms = sum(1 for _p in [PlanCode.FREE, PlanCode.BASIC, PlanCode.COMPLETE, PlanCode.CUSTOM]
               if not has_sms(_p))
print(f'  catalogo: {_sem_ia} plano(s) sem IA, {_sem_sms} sem SMS')
if _pagina.count('não incluída') != _sem_ia:
    falhas.append(f'a pagina marca IA ausente em {_pagina.count("não incluída")} planos, '
                  f'e o catalogo tem {_sem_ia}')
if _pagina.count('não incluído') != _sem_sms:
    falhas.append(f'a pagina marca SMS ausente em {_pagina.count("não incluído")} planos, '
                  f'e o catalogo tem {_sem_sms}')

# O bloco explicativo: os dois custam por uso, e a clinica precisa saber
# que pode apontar para o contrato proprio.
for _trecho, _oquee in [
    ('contrato próprio', 'que a clinica pode usar o provedor dela'),
    ('não estão disponíveis', 'que o Gratuito nao tem os dois'),
    ('e-mail', 'que os avisos do Gratuito seguem por e-mail'),
]:
    if _trecho not in _pagina:
        falhas.append(f'a pagina nao explica {_oquee} (faltou "{_trecho}")')
print(f'  bloco explicativo presente: {"contrato próprio" in _pagina}')

print('---')
print('Autor: a pagina diz quem escreveu o sistema')
from base.content import AUTOR

for _campo in ['nome', 'frase', 'resumo']:
    if AUTOR[_campo] not in _pagina:
        falhas.append(f'a pagina nao traz o campo "{_campo}" do autor')
for _linguagem in AUTOR['linguagens']:
    if _linguagem not in _pagina:
        falhas.append(f'a pagina nao cita a linguagem {_linguagem}')
_credenciais_na_pagina = sum(1 for _c_ in AUTOR['credenciais'] if _c_[:40] in _pagina)
print(f'  nome, frase e resumo presentes; {_credenciais_na_pagina}/{len(AUTOR["credenciais"])} credenciais')
if _credenciais_na_pagina != len(AUTOR['credenciais']):
    falhas.append('a pagina nao lista todas as credenciais de `content.AUTOR`')

# A foto e arquivo, e arquivo some. Com `ManifestStaticFilesStorage` a
# pagina inteira quebra na renderizacao se ela faltar -- este roteiro
# falha antes, dizendo qual arquivo.
from django.contrib.staticfiles import finders

if finders.find(AUTOR['foto']) is None:
    falhas.append(f'a foto do autor nao existe: static/{AUTOR["foto"]}')
print(f'  foto encontrada: {finders.find(AUTOR["foto"]) is not None}')

print('---')
if falhas:
    for line in falhas:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: a pagina anuncia o catalogo, diz o que cada plano nao tem,')
print('    apresenta quem escreveu o sistema, e o pedido de contato nao se perde.')
