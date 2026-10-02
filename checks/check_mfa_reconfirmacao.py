"""Reconfirmar o segundo fator sem derrubar a sessao.

Dois defeitos encontrados pelo medico no mesmo uso, e os dois eram becos
sem saida -- tela que nao oferece a acao seguinte.

**O primeiro: a pagina em branco.** Abrir sessao de assinatura exige MFA
confirmada nos ultimos trinta minutos. A do login envelhece. Quando
envelhecia, a view devolvia `403` com a frase solta em fundo branco:
"Confirme o codigo do seu aplicativo de autenticacao para liberar a
assinatura." -- dizendo o que fazer e sem lugar nenhum para faze-lo,
porque **a tela de reconfirmacao nao existia**. No envio de certificado a
saida era ainda pior: uma mensagem pedindo para sair e entrar de novo,
derrubando a sessao inteira por seis digitos.

**O segundo: o botao que gira para sempre.** `data-nd-confirm` cancela o
envio com `preventDefault()`, mas `preventDefault` nao impede que os
outros ouvintes de `submit` rodem -- e `initBusyButtons` rodava, punha o
spinner e desabilitava o botao. Quem respondia "cancelar" ficava com um
botao morto numa tela que nao ia a lugar nenhum; a unica saida era
recarregar.

O que este roteiro cobra:

- a tela de reconfirmacao existe, pede login, e aceita TOTP;
- codigo errado nao carimba a hora;
- o `next` volta para onde se estava, e **so dentro do proprio host** --
  destino externo aqui transformaria a confirmacao em trampolim de
  phishing;
- quem nao tem segundo fator e mandado configurar, nao recusado;
- abrir sessao de assinatura sem MFA recente **redireciona**, nao devolve
  403 em branco;
- a tela de certificados pede o codigo **antes** da senha, que e o que
  evita o retrabalho de redigita-la;
- e, estrutural, que o botao nao trave quando o envio e cancelado.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from pathlib import Path

from django.test import Client
from django.urls import reverse

from accounts import mfa
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:62} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


CHR = chr(10)
tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()

# O roteiro monta o proprio segundo fator em vez de contar com o do seed:
# sem TOTP confirmada a tela redireciona para a configuracao, e as secoes
# que importam -- o codigo errado, o destino do `next` -- nao chegariam a
# rodar. O dispositivo e removido no fim.
from django_otp.plugins.otp_totp.models import TOTPDevice

ja_tinha = mfa.get_confirmed_device(vinculo.user)
device = ja_tinha or TOTPDevice.objects.create(
    user=vinculo.user, confirmed=True, name='roteiro-mfa',
)

url_confirmar = reverse('accounts:mfa-confirm')
url_credenciais = reverse('documents:credential-list')

print(CHR + '1. A tela de reconfirmacao existe e exige login')
anonimo = Client()
resposta = anonimo.get(url_confirmar)
conferir('visitante sem sessao e mandado ao login', resposta.status_code, 302)
conferir('  para o login, e nao para outro lugar',
         reverse('accounts:login') in resposta['Location'], True)

cliente = Client()
cliente.force_login(vinculo.user)
sessao = cliente.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()

print(CHR + '2. Quem nao tem segundo fator e mandado configurar')
# Recusar quem ainda nao configurou seria o mesmo beco de antes: a tela
# diria "confirme o codigo" para quem nao tem codigo nenhum.
conferir('o usuario do roteiro tem segundo fator',
         mfa.user_has_confirmed_totp(vinculo.user), True)
resposta = cliente.get(f'{url_confirmar}?next={url_credenciais}')
conferir('com MFA configurada, a tela abre', resposta.status_code, 200)
conferir('  e diz por quantos minutos vale',
         str(mfa.RECENT_MFA_MAX_AGE_SECONDS // 60) in resposta.content.decode(), True)
conferir('  e leva o destino num campo oculto',
         f'value="{url_credenciais}"' in resposta.content.decode(), True)

print(CHR + '3. O destino do `next` nao sai do proprio host')
# Um destino solto aqui transformaria a confirmacao de MFA em trampolim
# para fora do dominio, que e o formato classico do phishing de
# redirecionamento.
for externo in ('https://exemplo-malicioso.invalid/', '//exemplo-malicioso.invalid/',
                'http://exemplo-malicioso.invalid/x'):
    resposta = cliente.get(f'{url_confirmar}?next={externo}')
    corpo = resposta.content.decode() if resposta.status_code == 200 else resposta.get('Location', '')
    conferir(f'  {externo[:34]:34} nao e aceito',
             'exemplo-malicioso' in corpo, False)

resposta = cliente.get(f'{url_confirmar}?next={url_credenciais}')
conferir('mas um caminho interno e aceito',
         url_credenciais in resposta.content.decode(), True)

print(CHR + '4. Codigo errado nao carimba a hora')
sessao = cliente.session
sessao.pop(mfa.RECENT_MFA_SESSION_KEY, None)
sessao.save()
resposta = cliente.post(url_confirmar, {'code': '000000', 'next': url_credenciais})
conferir('a tela volta com erro, e nao redireciona', resposta.status_code, 200)
conferir('e a MFA continua nao sendo recente',
         mfa.RECENT_MFA_SESSION_KEY in cliente.session, False)

print(CHR + '4-B. Codigo certo carimba a hora e volta para onde estava')
from django_otp.oath import totp as _totp

# O django-otp atrasa a tentativa seguinte a uma falha, e a secao acima
# acabou de falhar de proposito. Zerar o contador aqui e o que separa
# "codigo certo e aceito" de "codigo certo chegou cedo demais" -- sem
# isto, o roteiro acusaria o produto por uma protecao que funcionou.
device.throttle_reset()

valido = f'{_totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):0{device.digits}d}'
resposta = cliente.post(url_confirmar, {'code': valido, 'next': url_credenciais})
conferir('redireciona', resposta.status_code, 302)
conferir('  de volta para onde se estava', resposta['Location'], url_credenciais)
conferir('e a MFA passa a ser recente', mfa.RECENT_MFA_SESSION_KEY in cliente.session, True)

print(CHR + '5. Abrir sessao de assinatura sem MFA recente redireciona')
sessao = cliente.session
sessao.pop(mfa.RECENT_MFA_SESSION_KEY, None)
sessao.save()
# O defeito original: 403 com a frase solta em fundo branco.
resposta = cliente.post(reverse('documents:session-start'), {
    'credential_id': '00000000-0000-0000-0000-000000000000',
    'password': 'qualquer', 'duration_hours': '2',
})
conferir('nao devolve 403 em branco', resposta.status_code == 403, False)
if resposta.status_code == 302:
    conferir('  e manda reconfirmar o codigo',
             url_confirmar in resposta['Location'], True)
    conferir('  levando de volta aos certificados',
             'credential' in resposta['Location'] or 'next=' in resposta['Location'], True)

print(CHR + '6. A tela de certificados pede o codigo antes da senha')
resposta = cliente.get(url_credenciais)
conferir('a tela abre', resposta.status_code, 200)
html = resposta.content.decode()
conferir('sem MFA recente, nao oferece o campo de senha do certificado',
         'name="password"' in html, False)
conferir('e oferece o caminho para confirmar o codigo',
         url_confirmar in html, True)

print(CHR + '7. Envio cancelado nao deixa o botao girando')
# Assercao estrutural: `preventDefault()` do `data-nd-confirm` nao impede
# que os outros ouvintes de `submit` rodem. Sem a guarda, o botao ganha o
# spinner e fica desabilitado numa tela que nao vai a lugar nenhum.
app_js = Path(dj_settings.BASE_DIR, 'static', 'duralux', 'app.js').read_text(encoding='utf-8')
conferir('o travamento do botao respeita o cancelamento',
         'event.defaultPrevented' in app_js, True)
corpo_busy = app_js[app_js.index('function initBusyButtons'):]
corpo_busy = corpo_busy[:corpo_busy.index('/* ------------------------------------------------ campos que crescem')]
conferir('a guarda esta dentro do proprio initBusyButtons',
         'defaultPrevented' in corpo_busy, True)
conferir('e vem antes de desabilitar o botao',
         corpo_busy.index('defaultPrevented') < corpo_busy.index('disabled = true'), True)

inline_js = Path(dj_settings.BASE_DIR, 'static', 'duralux', 'nd-inline.js').read_text(encoding='utf-8')
conferir('a confirmacao continua cancelando o envio',
         'preventDefault' in inline_js and 'data-nd-confirm' in inline_js, True)

print(CHR + '8. O decorador de operacao privilegiada tambem leva ao MFA')
origem = Path(dj_settings.BASE_DIR, 'accounts', 'mfa.py').read_text(encoding='utf-8')
conferir('require_recent_mfa nao devolve mais 403 cru',
         'HttpResponseForbidden' in origem, False)
conferir('e usa o redirecionamento para a reconfirmacao',
         'redirect_to_mfa_confirm' in origem, True)

print(CHR + '9. E ninguem manda mais o medico sair e entrar de novo')
docs = Path(dj_settings.BASE_DIR, 'documents', 'views.py').read_text(encoding='utf-8')
conferir('a saida "saia e entre novamente" nao existe mais',
         'Saia e entre novamente' in docs, False)

if ja_tinha is None:
    TOTPDevice.objects.filter(id=device.id).delete()
    print(CHR + '  limpeza: dispositivo TOTP do roteiro removido')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print(CHR + 'OK: reconfirmar o segundo fator tem tela, o destino nao sai do host,')
print('    e envio cancelado nao deixa botao girando.')
