"""QR da MFA, percurso ate o certificado e dono da credencial.

Tres defeitos aparecem juntos na mesma jornada:

- a configuracao entregava apenas a URL ``otpauth://`` em texto, que um
  celular nao consegue escanear da propria tela;
- a pagina oferecia o envio do PFX mesmo sem MFA e o POST terminava num
  403 cru; alem disso, confirmar a MFA nao marcava a verificacao como
  recente, entao o envio continuava fechado logo depois da configuracao;
- certificado e chave privada nunca podem atravessar de um medico para
  outro, nem quando os dois pertencem a mesma clinica.

O usuario deste roteiro e descartavel. A unica trilha que a confirmacao da
MFA geraria e substituida porque ela protegeria o usuario contra exclusao
no fim; o objeto testado continua sendo a view real, inclusive sessao,
template, TOTP e middleware.
"""
import base64
import re
import time
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings as dj_settings
from django.test import Client
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts import mfa
from accounts.models import PhysicianProfile, User
from documents.models import SigningCredential, SigningCredentialStatus
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:64} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
outro_medico = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
).first()
if outro_medico is None:
    raise SystemExit('A clinica de demonstracao nao tem outro medico para a prova de isolamento.')

sufixo = uuid.uuid4().hex[:8]
usuario = User.objects.create_user(
    f'roteiro-mfa-{sufixo}@example.invalid', 'Senha-descartavel-123!',
    first_name='Medica', last_name='Do Roteiro', email_verified_at=timezone.now(),
)
perfil = PhysicianProfile.objects.create(
    user=usuario, professional_name='Medica Do Roteiro',
    crm_number=f'9{sufixo}', crm_state='SP',
    verification_status=PhysicianProfile.VerificationStatus.VERIFIED,
)
vinculo = Membership.objects.create(
    tenant=tenant, user=usuario, roles=[Role.DOCTOR],
    status=MembershipStatus.ACTIVE, activated_at=timezone.now(),
)
credencial_alheia = SigningCredential.objects.create(
    tenant=tenant, physician=outro_medico,
    ciphertext_path=f'/tmp/nao-existe-{sufixo}.pfx.enc',
    wrapped_key_metadata={'wrapped_key': 'nao-usada'},
    certificate_serial=f'ALHEIO-{sufixo}', certificate_fingerprint='a' * 64,
    issuer='Roteiro', not_before=timezone.now() - timedelta(days=1),
    not_after=timezone.now() + timedelta(days=1), status=SigningCredentialStatus.ACTIVE,
)

cliente = Client()
cliente.force_login(usuario)
sessao = cliente.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()

try:
    print('\n1. O gerador produz um SVG local e depende do segredo recebido')
    gerador = getattr(mfa, 'qr_code_data_uri', None)
    conferir('o gerador existe', callable(gerador), True)
    if callable(gerador):
        uri_a = gerador('otpauth://totp/NeuroDoc:um?secret=AAAA&issuer=NeuroDoc')
        uri_b = gerador('otpauth://totp/NeuroDoc:dois?secret=BBBB&issuer=NeuroDoc')
        conferir('a imagem e uma data URI SVG', uri_a.startswith('data:image/svg+xml;base64,'), True)
        conferir('segredos diferentes geram imagens diferentes', uri_a != uri_b, True)
        bruto = base64.b64decode(uri_a.split(',', 1)[1]).decode('utf-8')
        conferir('o conteudo decodificado e SVG', bruto.startswith('<svg '), True)
        conferir('o segredo nao aparece escrito dentro do SVG', 'secret=AAAA' in bruto, False)

    print('\n2. A tela de configuracao mostra o QR e a alternativa manual')
    resposta = cliente.get(
        '/accounts/mfa/setup/',
        {'next': '/app/documents/signing/credentials/'},
    )
    corpo = resposta.content.decode('utf-8', 'replace')
    qr_na_tela = re.search(r'<img[^>]+src="data:image/svg\+xml;base64,[^"]+"[^>]*>', corpo)
    conferir('a configuracao abre', resposta.status_code, 200)
    conferir('ha uma imagem QR embutida', qr_na_tela is not None, True)
    conferir('a imagem explica o que contem', 'QR para configurar' in corpo, True)
    conferir('a URL manual continua disponivel', 'otpauth://' in corpo, True)

    print('\n3. Sem MFA, o certificado oferece a configuracao, nao um POST fadado ao 403')
    resposta = cliente.get('/app/documents/signing/credentials/')
    corpo = resposta.content.decode('utf-8', 'replace')
    conferir('a pagina de certificados abre', resposta.status_code, 200)
    conferir('o formulario de PFX fica oculto', 'action="/app/documents/signing/credentials/upload/"' in corpo, False)
    conferir('a pagina explica que e preciso configurar MFA', 'Configure a MFA' in corpo, True)
    conferir('o atalho conserva o retorno aos certificados',
             'next=/app/documents/signing/credentials/' in corpo, True)

    resposta = cliente.post('/app/documents/signing/credentials/upload/', {})
    conferir('um POST direto tambem conduz a configuracao', resposta.status_code, 302)
    conferir('o redirecionamento aponta para MFA', '/accounts/mfa/setup/' in resposta.headers.get('Location', ''), True)

    print('\n4. Confirmar o primeiro TOTP deixa a sessao pronta para o PFX')
    dispositivo = TOTPDevice.objects.filter(user=usuario, confirmed=False).first()
    conferir('a abertura criou o dispositivo pendente', dispositivo is not None, True)
    if dispositivo is not None:
        totp = TOTP(
            dispositivo.bin_key, dispositivo.step, dispositivo.t0,
            dispositivo.digits, dispositivo.drift,
        )
        totp.time = time.time()
        codigo = str(totp.token()).zfill(dispositivo.digits)
        with patch('accounts.views.record_audit_event'):
            resposta = cliente.post('/accounts/mfa/setup/', {
                'code': codigo,
                'next': '/app/documents/signing/credentials/',
            })
        conferir('o TOTP valido mostra os codigos de recuperacao', resposta.status_code, 200)
        conferir('a sessao ganha a marca de MFA recente',
                 mfa.RECENT_MFA_SESSION_KEY in cliente.session, True)
        corpo = resposta.content.decode('utf-8', 'replace')
        conferir('continuar volta para os certificados',
                 'href="/app/documents/signing/credentials/"' in corpo, True)

        resposta = cliente.get('/app/documents/signing/credentials/')
        corpo = resposta.content.decode('utf-8', 'replace')
        conferir('depois da confirmacao o formulario aparece',
                 'action="/app/documents/signing/credentials/upload/"' in corpo, True)

        marca_recente = cliente.session[mfa.RECENT_MFA_SESSION_KEY]
        sessao = cliente.session
        del sessao[mfa.RECENT_MFA_SESSION_KEY]
        sessao.save()
        resposta = cliente.get('/app/documents/signing/credentials/')
        corpo = resposta.content.decode('utf-8', 'replace')
        conferir('se a verificacao expira o formulario volta a ficar oculto',
                 'action="/app/documents/signing/credentials/upload/"' in corpo, False)
        conferir('a tela pede nova entrada quando a verificacao expirou',
                 'entre novamente' in corpo, True)
        resposta = cliente.post('/app/documents/signing/credentials/upload/', {})
        conferir('o POST expirado volta para a pagina com explicacao', resposta.status_code, 302)
        conferir('nao cai em pagina 403 quando a verificacao expirou',
                 resposta.headers.get('Location', ''), '/app/documents/signing/credentials/')
        sessao = cliente.session
        sessao[mfa.RECENT_MFA_SESSION_KEY] = marca_recente
        sessao.save()

    print('\n5. Um medico nao enxerga nem opera o certificado do outro')
    resposta = cliente.get('/app/documents/signing/credentials/')
    corpo = resposta.content.decode('utf-8', 'replace')
    conferir('o serial alheio nao aparece na lista', credencial_alheia.certificate_serial in corpo, False)
    resposta = cliente.post(
        f'/app/documents/signing/credentials/{credencial_alheia.id}/revoke/',
    )
    credencial_alheia.refresh_from_db()
    conferir('revogar certificado alheio e recusado', resposta.status_code, 403)
    conferir('o certificado alheio continua ativo',
             credencial_alheia.status, SigningCredentialStatus.ACTIVE)

finally:
    credencial_alheia.delete()
    vinculo.delete()
    perfil.delete()
    usuario.delete()

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: a MFA tem QR e percurso completo, e o certificado fica no medico dono.')
