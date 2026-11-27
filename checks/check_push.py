"""Os avisos no celular — o aplicativo instalado, Etapa 2 (2026-11-27,
`notifications/push.py`, `notifications/webpush.py`).

O que se cobra, e o que tentaria quebrar:

- a **cifra** é a da RFC 8291, byte a byte contra o exemplo do Apêndice A, e
  o aparelho consegue abrir o que o servidor cifrou com sal e chave novos;
- a **assinatura VAPID** confere com a chave pública, para a origem do
  serviço, com prazo dentro do que a Apple aceita;
- o **par de chaves** nasce uma vez, a privada cifrada no banco;
- a **inscrição** só aceita serviço de push conhecido (`http`, porta,
  usuário, servidor interno e domínio parecido recusados) e chave válida;
  passa para quem entra no mesmo aparelho; no máximo dez por pessoa;
- as **telas**: o painel na Central, as rotas só por `POST`, com CSRF, só
  com vínculo, cada um só com os seus aparelhos, a trilha sem o endereço;
- o **disparo**: o sino, a mensagem da equipe (não para quem mandou, não
  para quem está on-line, uma por conversa a cada dois minutos) e o portal
  (só para quem lê prontuário), sempre depois do commit; quem não tem
  aparelho não gera tarefa;
- o **envio**: o corpo aberto com a chave do aparelho diz **só o tipo**,
  nunca o nome do paciente; 404/410 apagam, falha conta, cinco falhas
  apagam, endereço fora da lista não recebe `POST`;
- o **worker do aparelho** mostra e abre só endereço do próprio site; o que
  se apaga não tem push;
- **Sair** tira só aquele aparelho; os dois botões de emergência calam tudo.

Roda inteiro dentro de uma transação desfeita no fim.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

import base64
import json
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.db import transaction
from django.test import Client, TestCase

from audit.models import AuditEvent
from base.models import InstallationSettings
from notifications import push, services, tasks, webpush
from notifications.models import Notification, PushSubscription
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


def secao(titulo):
    print(f'\n{titulo}')


class _Desfazer(Exception):
    pass


def b(texto):
    return webpush.de_b64url(texto.replace(' ', '').replace('\n', ''))


# ------------------------------------------------------------------ apoio

def aparelho_novo():
    """Um "navegador": par P-256 e segredo, como o `pushManager` gera."""
    privada = ec.generate_private_key(ec.SECP256R1())
    import os

    from cryptography.hazmat.primitives import serialization
    publica = privada.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return privada, webpush.b64url(publica), webpush.b64url(os.urandom(16))


def abrir(corpo, privada_do_aparelho, p256dh, auth):
    """O lado do aparelho da RFC 8291: abre o corpo `aes128gcm`."""
    salt, idlen = corpo[:16], corpo[20]
    publica_do_servidor = corpo[21:21 + idlen]
    cifrado = corpo[21 + idlen:]
    compartilhado = privada_do_aparelho.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), publica_do_servidor))
    ua = webpush.de_b64url(p256dh)
    ikm = HKDF(hashes.SHA256(), 32, webpush.de_b64url(auth),
               b'WebPush: info\x00' + ua + publica_do_servidor).derive(compartilhado)
    chave = HKDF(hashes.SHA256(), 16, salt, b'Content-Encoding: aes128gcm\x00').derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b'Content-Encoding: nonce\x00').derive(ikm)
    claro = AESGCM(chave).decrypt(nonce, cifrado, None)
    return claro.rstrip(b'\x00')[:-1]


class Resposta:
    def __init__(self, status):
        self.status_code = status
        self.text = '' if status < 300 else 'recusado pelo servico falso'


class ServicoFalso:
    """Faz as vezes do `httpx.Client`: guarda cada POST e responde o que mandarem."""

    def __init__(self, status=201):
        self.status = status
        self.pedidos = []

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, content=None):
        self.pedidos.append((url, headers, content))
        status = self.status(url) if callable(self.status) else self.status
        return Resposta(status)


def com_servico(servico, funcao, *args, **kwargs):
    import httpx

    original = httpx.Client
    httpx.Client = servico
    try:
        return funcao(*args, **kwargs)
    finally:
        httpx.Client = original


clinica = Tenant.objects.get(slug='demo-clinica-a')


def vinculo(papel):
    return Membership.objects.filter(
        tenant=clinica, roles__contains=[papel], status=MembershipStatus.ACTIVE,
    ).select_related('user').first()


def logado(user, csrf=False):
    c = Client(enforce_csrf_checks=csrf)
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(clinica.id)
    s.save()
    return c


medico, secretaria = vinculo('doctor'), vinculo('secretary')
FCM = 'https://fcm.googleapis.com/fcm/send/'
APPLE = 'https://web.push.apple.com/'

try:
    with transaction.atomic():
        PushSubscription.objects.all().delete()

        # ---------------------------------------------------------------- 1
        secao('1. A cifra da RFC 8291, byte a byte')
        corpo = webpush.cifrar(
            b'When I grow up, I want to be a watermelon',
            'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
            'BTBZMqHH6r4Tts7J_aSIgg',
            _privada_do_servidor='yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw',
            _salt=b('DGv6ra1nlYgDCS1FRnbzlw'),
        )
        esperado = b('''DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml
            mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT
            pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN''')
        confere(corpo == esperado, 'o corpo é exatamente o do exemplo da RFC (145 bytes)')
        confere(webpush.publica_da_privada('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw')
                == 'BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8',
                'a pública derivada da privada bate com a da RFC')
        priv, p256dh, auth = aparelho_novo()
        um = webpush.cifrar('Olá, aviso'.encode(), p256dh, auth)
        dois = webpush.cifrar('Olá, aviso'.encode(), p256dh, auth)
        confere(abrir(um, priv, p256dh, auth) == 'Olá, aviso'.encode(),
                'o aparelho abre o que o servidor cifrou com sal e chave novos')
        confere(um[:16] != dois[:16] and um[21:86] != dois[21:86],
                'cada aviso sai com sal e chave do servidor novos')
        confere(not webpush.chave_do_aparelho_valida('AAAA', auth), 'chave curta recusada')
        confere(not webpush.chave_do_aparelho_valida(p256dh[:-4] + 'AAAA', auth),
                'ponto fora da curva recusado')
        confere(not webpush.chave_do_aparelho_valida(p256dh, 'AAAA'), 'segredo curto recusado')
        try:
            webpush.montar_pedido(FCM + 'x', p256dh, auth, b'x' * 5000, webpush.gerar_chaves()[0],
                                  'mailto:a@b.c')
            confere(False, 'aviso grande demais recusado antes de sair')
        except ValueError:
            confere(True, 'aviso grande demais recusado antes de sair')

        # ---------------------------------------------------------------- 2
        secao('2. A assinatura VAPID')
        privada, publica = webpush.gerar_chaves()
        agora = int(time.time())
        cab = webpush.assinatura_vapid(FCM + 'abc', privada, 'mailto:contato@exemplo.com.br',
                                       agora=agora)
        confere(cab.startswith('vapid t=') and cab.endswith(f', k={publica}'),
                'cabeçalho "vapid t=..., k=<pública>"')
        token = cab[len('vapid t='):cab.index(', k=')]
        h, c, s = token.split('.')
        claims = json.loads(webpush.de_b64url(c))
        confere(json.loads(webpush.de_b64url(h)) == {'typ': 'JWT', 'alg': 'ES256'}, 'ES256')
        confere(claims['aud'] == 'https://fcm.googleapis.com', 'aud é a origem do serviço, sem caminho')
        confere(0 < claims['exp'] - agora <= 24 * 3600, 'prazo dentro das 24 h da Apple')
        confere(claims['sub'] == 'mailto:contato@exemplo.com.br', 'sub preservado')
        assinatura = webpush.de_b64url(s)
        chave = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.de_b64url(publica))
        try:
            chave.verify(encode_dss_signature(int.from_bytes(assinatura[:32], 'big'),
                                              int.from_bytes(assinatura[32:], 'big')),
                         f'{h}.{c}'.encode(), ec.ECDSA(hashes.SHA256()))
            confere(len(assinatura) == 64, 'assinatura r||s de 64 bytes confere com a pública')
        except Exception:
            confere(False, 'assinatura r||s de 64 bytes confere com a pública')
        apple = webpush.assinatura_vapid(APPLE + 'x', privada, 'mailto:a@b.c')
        confere('"aud":"https://web.push.apple.com"'.encode() in
                webpush.de_b64url(apple[len('vapid t='):].split('.')[1]),
                'outro serviço, outra origem no aud')
        confere(push._assunto().startswith(('mailto:', 'https:', 'http:')), 'sub da instalação utilizável')

        # ---------------------------------------------------------------- 3
        secao('3. O par de chaves da instalação')
        linha = InstallationSettings.carregar()
        linha.push_vapid_publica = ''
        linha.push_vapid_privada_cifrada = ''
        linha.push_vapid_privada_meta = {}
        linha.save()
        pub1 = push.chave_publica()
        pub2 = push.chave_publica()
        linha.refresh_from_db()
        confere(pub1 and pub1 == pub2 == linha.push_vapid_publica, 'gerada uma vez e estável')
        privada_clara = push._chaves()[1]()
        confere(webpush.publica_da_privada(privada_clara) == pub1, 'a privada guardada é a da pública')
        confere(privada_clara not in linha.push_vapid_privada_cifrada
                and 'wrapped_key' in linha.push_vapid_privada_meta, 'a privada está cifrada no banco')

        # ---------------------------------------------------------------- 4
        secao('4. A inscrição')
        for endereco, aceito in [
            (FCM + 'abc', True), (APPLE + 'QWER', True),
            ('https://updates.push.services.mozilla.com/wpush/v2/x', True),
            ('https://wns2-par02p.notify.windows.com/w/?token=x', True),
            ('http://fcm.googleapis.com/fcm/send/x', False),
            ('https://fcm.googleapis.com:8443/fcm/send/x', False),
            ('https://user@fcm.googleapis.com/fcm/send/x', False),
            ('https://fcm.googleapis.com.evil.com/x', False),
            ('https://evil.com/fcm.googleapis.com/x', False),
            ('https://evilfcm.googleapis.com.evil/x', False),
            ('https://redis:6379/', False), ('https://127.0.0.1/x', False),
            ('https://db/x', False), ('javascript:alert(1)', False), ('', False),
            (FCM + 'x' * 1000, False),
        ]:
            confere(push.endereco_aceito(endereco) == aceito,
                    f'{"aceito" if aceito else "recusado"}: {endereco[:60]}')
        priv_a, p_a, a_a = aparelho_novo()
        dados = {'endpoint': FCM + 'aparelho-a', 'keys': {'p256dh': p_a, 'auth': a_a}}
        push.inscrever(medico.user, dados, 'Android · Chrome')
        for ruim, rotulo in [
            ({'endpoint': 'https://redis/x', 'keys': dados['keys']}, 'servidor interno'),
            ({'endpoint': FCM + 'y', 'keys': {'p256dh': 'AAAA', 'auth': a_a}}, 'chave torta'),
            ({'endpoint': FCM + 'y'}, 'sem chaves'), (None, 'corpo vazio'),
        ]:
            try:
                push.inscrever(medico.user, ruim)
                confere(False, f'recusado: {rotulo}')
            except push.InscricaoRecusada:
                confere(True, f'recusado: {rotulo}')
        push.inscrever(secretaria.user, dados, 'Android · Chrome')
        confere(PushSubscription.objects.get(endpoint=dados['endpoint']).user_id == secretaria.user_id
                and PushSubscription.objects.filter(endpoint=dados['endpoint']).count() == 1,
                'o mesmo aparelho passa para quem entrou nele, sem linha repetida')
        PushSubscription.objects.all().delete()
        for i in range(push.APARELHOS_POR_PESSOA + 3):
            _, p, a = aparelho_novo()
            push.inscrever(medico.user, {'endpoint': f'{FCM}n{i}', 'keys': {'p256dh': p, 'auth': a}})
        confere(medico.user.push_subscriptions.count() == push.APARELHOS_POR_PESSOA,
                f'no máximo {push.APARELHOS_POR_PESSOA} aparelhos por pessoa')
        confere(not medico.user.push_subscriptions.filter(endpoint=f'{FCM}n0').exists()
                and medico.user.push_subscriptions.filter(endpoint=f'{FCM}n12').exists(),
                'sai o mais antigo, fica o novo')
        PushSubscription.objects.all().delete()
        confere(push.aparelho_do_navegador(
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 '
            '(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1') == 'iPhone · Safari',
            'rótulo curto do aparelho, sem versão')

        # ---------------------------------------------------------------- 5
        secao('5. As telas')
        c = logado(medico.user, csrf=True)
        r = c.get('/app/notifications/')
        html = r.content.decode()
        confere(r.status_code == 200 and 'data-nd-push' in html and f'data-nd-push-chave="{pub1}"' in html,
                'a Central traz o painel com a chave pública')
        confere('nd-push.js' in html and 'nunca o nome do paciente' in html,
                'o script e o aviso do que a notificação mostra')
        import re
        estados = re.findall(r'data-nd-push-estado="[^"]+"(\s+hidden)?>', html)
        confere(len(estados) == 5 and all(estados), 'os cinco estados nascem escondidos')
        token = c.cookies['csrftoken'].value
        priv_m, p_m, a_m = aparelho_novo()
        corpo_ok = json.dumps({'endpoint': FCM + 'medico', 'keys': {'p256dh': p_m, 'auth': a_m}})
        r = c.post('/app/notifications/celular/ativar/', corpo_ok, content_type='application/json')
        confere(r.status_code == 403 and not PushSubscription.objects.exists(), 'sem CSRF, recusado')
        r = c.post('/app/notifications/celular/ativar/', corpo_ok, content_type='application/json',
                   HTTP_X_CSRFTOKEN=token,
                   HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 14) Chrome/131.0 Mobile Safari/537.36')
        confere(r.status_code == 200 and r.json().get('aparelho') == 'Android · Chrome',
                'ativar com CSRF grava o aparelho')
        evento = AuditEvent.objects.filter(action='notifications.push_ativado').order_by('-created_at').first()
        confere(evento is not None and 'fcm' not in json.dumps(evento.integrity_metadata or {}),
                'a trilha registra sem o endereço')
        r = c.post('/app/notifications/celular/ativar/', json.dumps({'endpoint': 'https://db/x',
                   'keys': {'p256dh': p_m, 'auth': a_m}}), content_type='application/json',
                   HTTP_X_CSRFTOKEN=token)
        confere(r.status_code == 400 and 'Endereço' in r.json().get('erro', ''), 'endereço interno: 400')
        confere(Client().get('/app/notifications/celular/ativar/').status_code in (302, 404)
                and c.get('/app/notifications/celular/ativar/').status_code == 405,
                'anônimo fora, GET recusado')
        _, p_s, a_s = aparelho_novo()
        PushSubscription.objects.create(user=secretaria.user, endpoint=FCM + 'secretaria',
                                        p256dh=p_s, auth=a_s)
        outra = PushSubscription.objects.get(endpoint=FCM + 'secretaria')
        c2 = logado(medico.user)
        r = c2.post('/app/notifications/celular/testar/', json.dumps({'endpoint': FCM + 'secretaria'}),
                    content_type='application/json')
        confere(r.status_code == 404, 'testar o aparelho de outra pessoa: 404')
        r = c2.post('/app/notifications/celular/desativar/', {'id': outra.pk})
        confere(PushSubscription.objects.filter(pk=outra.pk).exists(),
                'tirar o aparelho de outra pessoa não tira nada')
        enfileirados = []
        original_delay = tasks.enviar_push_teste.delay
        tasks.enviar_push_teste.delay = lambda *a, **k: enfileirados.append(a)
        try:
            r = c2.post('/app/notifications/celular/testar/', json.dumps({'endpoint': FCM + 'medico'}),
                        content_type='application/json')
        finally:
            tasks.enviar_push_teste.delay = original_delay
        confere(r.status_code == 200 and len(enfileirados) == 1, 'o teste vai pelo worker')
        r = c2.get('/app/notifications/')
        confere('Android · Chrome' in r.content.decode() and 'secretaria' not in r.content.decode(),
                'a lista mostra só os aparelhos da própria pessoa, pelo rótulo')
        r = c2.post('/app/notifications/celular/desativar/', json.dumps({'endpoint': FCM + 'medico'}),
                    content_type='application/json')
        confere(r.status_code == 200 and r.json().get('removidos') == 1
                and not PushSubscription.objects.filter(endpoint=FCM + 'medico').exists(),
                'desativar o deste navegador')

        # ---------------------------------------------------------------- 6
        secao('6. O disparo')
        enviados = []
        original_delay = tasks.enviar_push.delay
        tasks.enviar_push.delay = lambda *a, **k: enviados.append(a)
        try:
            with TestCase.captureOnCommitCallbacks(execute=True):
                services.notify_user(clinica, medico.user_id, 'ai_job_succeeded', 'Resumo de JOSÉ DA SILVA')
            confere(enviados == [], 'quem não tem aparelho não gera tarefa')
            PushSubscription.objects.create(user=medico.user, endpoint=FCM + 'disparo',
                                            p256dh=p_m, auth=a_m)
            with TestCase.captureOnCommitCallbacks(execute=False) as pendentes:
                services.notify_user(clinica, medico.user_id, 'ai_job_succeeded', 'Resumo de JOSÉ DA SILVA')
            confere(enviados == [] and len(pendentes) == 1, 'nada sai antes do commit')
            for f in pendentes:
                f()
            confere(len(enviados) == 1 and enviados[0][0] == [str(medico.user_id)]
                    and enviados[0][1] == 'ai_job_succeeded' and enviados[0][2] == '/app/notifications/',
                    'o sino vira tarefa com o tipo e a Central')
            confere('JOSÉ' not in json.dumps(enviados), 'o título com o paciente não vai à tarefa')
            enviados.clear()
            from tenancy.permissions import Capability
            with TestCase.captureOnCommitCallbacks(execute=True):
                services.notify_capability(clinica, Capability.READ_CLINICAL, 'delivery_pending_contact', 'x')
            confere(len(enviados) == 1 and str(medico.user_id) in enviados[0][0]
                    and str(secretaria.user_id) not in enviados[0][0],
                    'por capacidade: o mesmo destinatário do sino')

            enviados.clear()
            with TestCase.captureOnCommitCallbacks(execute=True):
                push.avisar_portal(clinica, 'portal_pedido')
            from django.urls import reverse
            confere(len(enviados) == 1 and enviados[0][1] == 'portal_pedido'
                    and str(medico.user_id) in enviados[0][0]
                    and str(secretaria.user_id) not in enviados[0][0]
                    and enviados[0][2] == reverse('documents:request-queue'),
                    'pedido do portal: quem lê prontuário, para a fila')
            enviados.clear()
            with TestCase.captureOnCommitCallbacks(execute=True):
                push.avisar_portal(clinica, 'portal_exame')
            confere(len(enviados) == 1 and enviados[0][2] == reverse('documents:portal-exams'),
                    'exame do portal: para Exames enviados')

            # A mensagem da equipe.
            from django.core.cache import cache

            from teamchat import presence
            from teamchat import services as chat
            enviados.clear()
            PushSubscription.objects.create(user=secretaria.user, endpoint=FCM + 'sec2',
                                            p256dh=p_s, auth=a_s)
            conversa = chat.open_direct(clinica.id, medico.user_id, secretaria.user_id)
            if isinstance(conversa, tuple):
                conversa = conversa[0]
            if conversa is not None:
                cache.delete_many([f'push:equipe:{conversa.pk}:{u}'
                                   for u in (medico.user_id, secretaria.user_id)])
                original_online = presence.online_user_ids
                presence.online_user_ids = lambda t: set()
                try:
                    with TestCase.captureOnCommitCallbacks(execute=True):
                        chat.send(clinica.id, conversa, medico.user_id, 'Paciente JOSÉ chegou')
                    primeira = list(enviados)
                    with TestCase.captureOnCommitCallbacks(execute=True):
                        chat.send(clinica.id, conversa, medico.user_id, 'de novo')
                    presence.online_user_ids = lambda t: {str(secretaria.user_id)}
                    cache.delete(f'push:equipe:{conversa.pk}:{secretaria.user_id}')
                    with TestCase.captureOnCommitCallbacks(execute=True):
                        chat.send(clinica.id, conversa, medico.user_id, 'on-line')
                finally:
                    presence.online_user_ids = original_online
                confere(len(primeira) == 1 and primeira[0][1] == 'equipe'
                        and str(medico.user_id) not in primeira[0][0],
                        'mensagem da equipe: avisa os outros, não quem mandou')
                confere('JOSÉ' not in json.dumps(primeira), 'nem o texto nem quem mandou vão ao aviso')
                confere(len(enviados) == 1, 'a segunda em dois minutos e a de quem está on-line não avisam')
            else:
                confere(False, 'há conversa de equipe na demonstração')
        finally:
            tasks.enviar_push.delay = original_delay

        # ---------------------------------------------------------------- 7
        secao('7. O envio')
        PushSubscription.objects.all().delete()
        ia = PushSubscription.objects.create(user=medico.user, endpoint=FCM + 'envio-a',
                                             p256dh=p_m, auth=a_m)
        _, p_b, a_b = aparelho_novo()
        PushSubscription.objects.create(user=medico.user, endpoint=APPLE + 'envio-b',
                                        p256dh=p_b, auth=a_b)
        servico = ServicoFalso(201)
        r = com_servico(servico, push.enviar, [medico.user_id], 'ai_job_succeeded', '/app/notifications/',
                        'sino-ai_job_succeeded')
        confere({k: r[k] for k in ('enviados', 'removidos', 'falhas')} == {'enviados': 2, 'removidos': 0, 'falhas': 0}
                and len(r['respostas']) == 2 and {x['status'] for x in r['respostas']} == {201},
                'um POST por aparelho, com a resposta de cada servico')
        url, cabecalhos, corpo = next(p for p in servico.pedidos if p[0] == FCM + 'envio-a')
        mensagem = json.loads(abrir(corpo, priv_m, p_m, a_m))
        confere(mensagem['corpo'] == push.TEXTOS['ai_job_succeeded'] and mensagem['url'] == '/app/notifications/',
                'o aparelho abre o aviso: só o tipo e a Central')
        confere(cabecalhos['Content-Encoding'] == 'aes128gcm' and cabecalhos['TTL'] == '86400'
                and cabecalhos['Authorization'].startswith('vapid t=')
                and cabecalhos['Topic'] == 'sino-ai_job_succeeded', 'cabeçalhos do protocolo')
        confere(PushSubscription.objects.get(pk=ia.pk).ultimo_envio_em is not None, 'entrega registrada')
        for tipo in list(push.TEXTOS) + ['tipo_novo_do_futuro']:
            confere(push.texto(tipo) and 'JOSÉ' not in push.texto(tipo), f'texto genérico: {tipo}')
        servico = ServicoFalso(lambda u: 410 if 'apple' in u else 500)
        r = com_servico(servico, push.enviar, [medico.user_id], 'equipe')
        confere({k: r[k] for k in ('enviados', 'removidos', 'falhas')} == {'enviados': 0, 'removidos': 1, 'falhas': 1}
                and {x['status'] for x in r['respostas']} == {410, 500},
                '410 apaga, 500 conta falha, e as duas respostas ficam no resultado')
        confere(not PushSubscription.objects.filter(endpoint=APPLE + 'envio-b').exists()
                and PushSubscription.objects.get(pk=ia.pk).falhas == 1, 'a linha certa em cada caso')
        for _ in range(push.FALHAS_PARA_DESISTIR - 1):
            com_servico(ServicoFalso(503), push.enviar, [medico.user_id], 'equipe')
        confere(not PushSubscription.objects.filter(pk=ia.pk).exists(), 'cinco falhas seguidas apagam')
        PushSubscription.objects.create(user=medico.user, endpoint='https://db:5432/x', p256dh=p_m, auth=a_m)
        servico = ServicoFalso(201)
        r = com_servico(servico, push.enviar, [medico.user_id], 'equipe')
        confere(servico.pedidos == [] and r['removidos'] == 1, 'endereço fora da lista: sem POST, apagado')
        PushSubscription.objects.create(user=medico.user, endpoint=FCM + 'url', p256dh=p_m, auth=a_m)
        servico = ServicoFalso(201)
        com_servico(servico, push.enviar, [medico.user_id], 'equipe', '//evil.com/x')
        confere(json.loads(abrir(servico.pedidos[0][2], priv_m, p_m, a_m))['url'] == '/app/',
                'url de fora do site vira /app/')

        # ---------------------------------------------------------------- 8
        secao('8. O worker do aparelho')
        sw = Client().get('/sw.js').content.decode()
        confere("addEventListener('push'" in sw and "addEventListener('notificationclick'" in sw,
                'o worker recebe e abre o aviso')
        confere("alvo.charAt(0) !== '/' || alvo.charAt(1) === '/'" in sw,
                'o toque só abre endereço do próprio site')
        confere('showNotification' in sw and 'renotify' in sw, 'mostra sempre (o navegador exige)')
        dj_settings.PWA_SERVICE_WORKER = False
        try:
            sw_off = Client().get('/sw.js').content.decode()
            confere("'push'" not in sw_off and 'unregister' in sw_off,
                    'o worker que se apaga não tem push')
        finally:
            dj_settings.PWA_SERVICE_WORKER = True

        # ---------------------------------------------------------------- 9
        secao('9. Sair e os botões de emergência')
        PushSubscription.objects.all().delete()
        PushSubscription.objects.create(user=medico.user, endpoint=FCM + 'este', p256dh=p_m, auth=a_m)
        PushSubscription.objects.create(user=medico.user, endpoint=FCM + 'outro', p256dh=p_m, auth=a_m)
        PushSubscription.objects.create(user=secretaria.user, endpoint=FCM + 'dela', p256dh=p_s, auth=a_s)
        c = logado(medico.user)
        c.post('/accounts/logout/', {'nd_push_endpoint': FCM + 'dela'})
        confere(PushSubscription.objects.filter(endpoint=FCM + 'dela').exists(),
                'sair não tira o aparelho de outra pessoa')
        c = logado(medico.user)
        c.post('/accounts/logout/', {'nd_push_endpoint': FCM + 'este'})
        confere(not PushSubscription.objects.filter(endpoint=FCM + 'este').exists()
                and PushSubscription.objects.filter(endpoint=FCM + 'outro').exists(),
                'sair tira só este aparelho')
        js = open('static/duralux/nd-pwa.js', encoding='utf-8').read() if __import__('os').path.exists(
            'static/duralux/nd-pwa.js') else ''
        confere('nd_push_endpoint' in js and 'unsubscribe' in js and 'setTimeout(sair' in js,
                'o Sair cancela no navegador, com prazo')
        pjs = open('static/duralux/nd-push.js', encoding='utf-8').read() if __import__('os').path.exists(
            'static/duralux/nd-push.js') else ''
        confere(pjs.index('requestPermission') > pjs.index("addEventListener('click'"),
                'a permissão só é pedida no toque do botão')
        for chave in ('PWA_PUSH', 'PWA_SERVICE_WORKER'):
            setattr(dj_settings, chave, False)
            try:
                servico = ServicoFalso(201)
                r = com_servico(servico, push.enviar, [medico.user_id], 'equipe')
                enfileirou = []
                tasks.enviar_push.delay = lambda *a, **k: enfileirou.append(a)
                with TestCase.captureOnCommitCallbacks(execute=True):
                    push.avisar([medico.user_id], 'equipe')
                tasks.enviar_push.delay = original_delay
                html = logado(medico.user).get('/app/notifications/').content.decode()
                rota = logado(medico.user).post('/app/notifications/celular/ativar/', '{}',
                                                content_type='application/json').status_code
                confere(servico.pedidos == [] and not enfileirou and 'data-nd-push' not in html
                        and rota == 404, f'{chave}=False: nada sai, sem painel, rotas em 404')
            finally:
                setattr(dj_settings, chave, True)
                tasks.enviar_push.delay = original_delay
        from ops import make_runtime
        confere('PWA_PUSH' in str(make_runtime.OPTIONAL_KEYS), 'PWA_PUSH chega ao contêiner')

        raise _Desfazer
except _Desfazer:
    pass

print()
if falhas:
    print(f'{len(falhas)} falha(s):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('Tudo certo.')
