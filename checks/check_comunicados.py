"""Comunicados da instalação (2026-11-27, `notifications/comunicados.py`).

O que se cobra, e o que tentaria quebrar:

- a **propaganda** fica travada enquanto o contrato vigente não a prevê, e
  liberada só vai às clínicas cujo **último aceite** é de uma redação que a
  prevê; o aviso do sistema vale já;
- a **validação**: título e texto obrigatórios e com teto, link só do
  próprio site (`https://`, `//`, espaço e barra invertida recusados), plano,
  clínica e papel conferidos;
- os **destinatários**: vínculo ativo, clínica encerrada fora, suspensa só
  no aviso; cada filtro (plano, clínica, papel) recorta certo;
- o **console**: só superadministrador com o segundo fator; a prévia conta
  antes de enviar; enviar pede o código recente; a trilha sem o texto;
- o **envio** (worker): uma linha no sino por vínculo, o celular com o
  título e o começo do texto, uma vez só mesmo com a tarefa repetida;
- a **página**: abre para quem recebeu, com o texto escapado, marca como
  lida; quem não recebeu leva 404; o "Ler comunicado" do sino chega lá.

Roda dentro de uma transação desfeita no fim.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.db import transaction
from django.test import Client, TestCase
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.mfa import mark_recent_mfa
from accounts.models import User
from audit.models import AuditEvent
from notifications import comunicados, tasks, webpush
from notifications.models import Comunicado, Notification, PushSubscription
from tenancy import contract, plans
from tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


def secao(titulo):
    print(f'\n{titulo}')


class _Desfazer(Exception):
    pass


def aparelho_novo():
    privada = ec.generate_private_key(ec.SECP256R1())
    publica = privada.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return privada, webpush.b64url(publica), webpush.b64url(os.urandom(16))


def abrir(corpo, privada, p256dh, auth):
    salt, idlen = corpo[:16], corpo[20]
    do_servidor = corpo[21:21 + idlen]
    segredo = privada.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), do_servidor))
    ikm = HKDF(hashes.SHA256(), 32, webpush.de_b64url(auth),
               b'WebPush: info\x00' + webpush.de_b64url(p256dh) + do_servidor).derive(segredo)
    chave = HKDF(hashes.SHA256(), 16, salt, b'Content-Encoding: aes128gcm\x00').derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b'Content-Encoding: nonce\x00').derive(ikm)
    return AESGCM(chave).decrypt(nonce, corpo[21 + idlen:], None)[:-1]


class ServicoFalso:
    def __init__(self):
        self.pedidos = []

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, content=None):
        self.pedidos.append((url, headers, content))
        return type('R', (), {'status_code': 201})()


clinica = Tenant.objects.get(slug='demo-clinica-a')


def vinculo(papel, tenant=clinica):
    return Membership.objects.filter(
        tenant=tenant, roles__contains=[papel], status=MembershipStatus.ACTIVE,
    ).select_related('user').first()


def logado(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(clinica.id)
    s.save()
    return c


medico, secretaria = vinculo('doctor'), vinculo('secretary')
contrato_original = contract.VERSAO
limiar_original = plans.CONTRATO_COM_PROPAGANDA

try:
    with transaction.atomic():
        # ---------------------------------------------------------------- 1
        secao('1. A trava da propaganda')
        # A redação vigente já prevê a propaganda desde 2026-11-27 (NeuroDoc 2.5,
        # ProntDoc 1.4). A trava é conferida com um limiar acima da vigente, como
        # ficaria se um dia a redação mudasse de novo.
        confere(comunicados.propaganda_liberada(),
                f'contrato vigente {contract.VERSAO} >= {plans.CONTRATO_COM_PROPAGANDA}: liberada')
        plans.CONTRATO_COM_PROPAGANDA = '99'
        confere(not comunicados.propaganda_liberada(),
                f'contrato {contract.VERSAO} < 99: travada')
        try:
            comunicados.validar({'categoria': 'propaganda', 'publico': 'todos',
                                 'titulo': 'Oferta', 'texto': 'x'})
            confere(False, 'propaganda recusada na validação')
        except comunicados.ComunicadoRecusado:
            confere(True, 'propaganda recusada na validação')
        confere(comunicados.destinatarios('propaganda', 'todos') == [],
                'propaganda sem ninguém, mesmo chamando direto')
        confere(len(comunicados.destinatarios('aviso', 'todos')) > 0, 'o aviso do sistema vale já')
        try:
            from django.utils import timezone
            from tenancy.models import ContractAcceptance
            contract.VERSAO = plans.CONTRATO_COM_PROPAGANDA = '50.0'
            agora = timezone.now()
            ContractAcceptance.objects.create(
                tenant=clinica, version='50.0', text_sha256='0' * 64, accepted_email='a@b.invalid',
                withdrawal_deadline=agora, expires_at=agora)
            pares = comunicados.destinatarios('propaganda', 'todos')
            confere(pares and {t for t, _ in pares} == {clinica.id},
                    'liberada: só a clínica que aceitou a redação nova')
            ContractAcceptance.objects.create(
                tenant=clinica, version='49.0', text_sha256='0' * 64, accepted_email='a@b.invalid',
                withdrawal_deadline=agora, expires_at=agora)
            confere(comunicados.destinatarios('propaganda', 'todos') == [],
                    'vale o último aceite (um aceite mais novo de redação anterior tira)')
            contract.VERSAO = plans.CONTRATO_COM_PROPAGANDA = '99'
            confere(comunicados.propaganda_liberada()
                    and comunicados.destinatarios('propaganda', 'todos') == [],
                    'liberada no texto, mas ninguém aceitou a redação nova: ninguém recebe')
        finally:
            contract.VERSAO, plans.CONTRATO_COM_PROPAGANDA = contrato_original, limiar_original

        # ---------------------------------------------------------------- 2
        secao('2. A validação')
        base = {'categoria': 'aviso', 'publico': 'todos', 'titulo': 'Manutenção', 'texto': 'Domingo às 2h.'}
        confere(comunicados.validar(base)['titulo'] == 'Manutenção', 'o caso simples passa')
        for extra, rotulo in [
            ({'titulo': ''}, 'sem título'), ({'titulo': 'x' * 61}, 'título longo'),
            ({'texto': ''}, 'sem texto'), ({'texto': 'x' * 1001}, 'texto longo'),
            ({'link': 'https://evil.com/'}, 'link de fora'), ({'link': '//evil.com/x'}, 'link //'),
            ({'link': '/ajuda/ x'}, 'link com espaço'), ({'link': '/\\evil.com'}, 'link com barra invertida'),
            ({'link': 'javascript:alert(1)'}, 'link javascript'),
            ({'publico': 'plano', 'plano': 'ouro'}, 'plano inexistente'),
            ({'publico': 'clinica', 'clinica': 'abc'}, 'clínica que não é UUID'),
            ({'publico': 'clinica', 'clinica': '00000000-0000-0000-0000-000000000000'}, 'clínica inexistente'),
            ({'publico': 'papel', 'papel': 'admin'}, 'papel inexistente'),
            ({'publico': 'tudo'}, 'público inexistente'), ({'categoria': 'spam'}, 'tipo inexistente'),
        ]:
            try:
                comunicados.validar({**base, **extra})
                confere(False, f'recusado: {rotulo}')
            except comunicados.ComunicadoRecusado:
                confere(True, f'recusado: {rotulo}')
        confere(comunicados.validar({**base, 'link': '/ajuda/instalar-app/'})['link'] == '/ajuda/instalar-app/',
                'link do próprio site aceito')

        # ---------------------------------------------------------------- 3
        secao('3. Os destinatários')
        todos = comunicados.destinatarios('aviso', 'todos')
        ativos = set(Membership.objects.filter(
            status=MembershipStatus.ACTIVE, user__is_active=True,
            tenant__status__in=[TenantStatus.ACTIVE, TenantStatus.SUSPENDED],
        ).values_list('tenant_id', 'user_id'))
        confere(set(todos) == ativos, 'todos = os vínculos ativos de clínicas não encerradas')
        Tenant.objects.filter(pk=clinica.pk).update(status=TenantStatus.SUSPENDED)
        confere(any(t == clinica.id for t, _ in comunicados.destinatarios('aviso', 'todos')),
                'clínica suspensa recebe o aviso')
        Tenant.objects.filter(pk=clinica.pk).update(status=TenantStatus.CLOSED)
        confere(not any(t == clinica.id for t, _ in comunicados.destinatarios('aviso', 'todos')),
                'clínica encerrada não recebe')
        Tenant.objects.filter(pk=clinica.pk).update(status=TenantStatus.ACTIVE)
        so_clinica = comunicados.destinatarios('aviso', 'clinica', str(clinica.id))
        confere(so_clinica and all(t == clinica.id for t, _ in so_clinica), 'uma clínica: só ela')
        medicos = comunicados.destinatarios('aviso', 'papel', 'doctor')
        papeis = dict(Membership.objects.filter(tenant_id__in={t for t, _ in medicos})
                      .values_list('user_id', 'roles'))
        confere(medicos and (clinica.id, medico.user_id) in medicos
                and (clinica.id, secretaria.user_id) not in medicos, 'um papel: médico sim, secretária não')
        confere(all(t in set(Tenant.objects.filter(plan=clinica.plan).values_list('id', flat=True))
                    for t, _ in comunicados.destinatarios('aviso', 'plano', clinica.plan)),
                'um plano: só clínicas dele')
        Membership.objects.filter(pk=secretaria.pk).update(status=MembershipStatus.REVOKED) \
            if hasattr(MembershipStatus, 'REVOKED') else None
        if hasattr(MembershipStatus, 'REVOKED'):
            confere((clinica.id, secretaria.user_id) not in comunicados.destinatarios('aviso', 'todos'),
                    'vínculo revogado não recebe')
            Membership.objects.filter(pk=secretaria.pk).update(status=MembershipStatus.ACTIVE)

        # ---------------------------------------------------------------- 4
        secao('4. O console')
        su, _ = User.objects.get_or_create(email='check-comunicados@example.invalid',
                                           defaults={'is_active': True, 'is_superuser': True, 'is_staff': True})
        device = TOTPDevice.objects.create(user=su, name='teste', confirmed=True)
        c = Client()
        c.force_login(su)
        confere(c.get('/instalacao/comunicados/').status_code == 404, 'sem o segundo fator: 404')
        req = type('R', (), {'session': c.session, 'user': su})()
        otp_login(req, device)
        req.session.save()
        c.cookies['sessionid'] = req.session.session_key
        confere(logado(medico.user).get('/instalacao/comunicados/').status_code == 404,
                'médico da clínica: 404')
        r = c.get('/instalacao/comunicados/')
        html = r.content.decode()
        confere(r.status_code == 200 and 'Propaganda travada' not in html
                and '(travada)' not in html, 'a tela abre, com a propaganda liberada pelo contrato vigente')
        plans.CONTRATO_COM_PROPAGANDA = '99'
        try:
            html = c.get('/instalacao/comunicados/').content.decode()
        finally:
            plans.CONTRATO_COM_PROPAGANDA = limiar_original
        confere('Propaganda travada' in html and 'disabled' in html,
                'com a redação abaixo do limiar, a tela mostra a propaganda travada')
        confere('href="/instalacao/comunicados/"' in c.get('/instalacao/').content.decode(),
                'no menu do console')
        dados = {**base, 'publico': 'clinica', 'clinica': str(clinica.id), 'link': '/ajuda/'}
        antes = Comunicado.objects.count()
        r = c.post('/instalacao/comunicados/', {**dados, 'acao': 'previa'})
        previa = comunicados.previa('aviso', 'clinica', str(clinica.id))
        confere(r.status_code == 200 and f'<strong>{previa["pessoas"]} pessoa' in r.content.decode()
                and Comunicado.objects.count() == antes, 'a prévia conta e não grava')
        r = c.post('/instalacao/comunicados/', {**dados, 'acao': 'enviar'})
        confere(r.status_code == 302 and 'confirm' in r['Location'].lower()
                and Comunicado.objects.count() == antes, 'enviar sem o código recente: pede o código')
        r = c.post('/instalacao/comunicados/', {**base, 'titulo': '', 'acao': 'previa'})
        confere(r.status_code == 200 and 'obrigatório' in r.content.decode(), 'formulário errado volta com o erro')
        mark_recent_mfa(req)
        req.session.save()
        enfileirados = []
        original = tasks.enviar_comunicado.delay
        tasks.enviar_comunicado.delay = lambda *a, **k: enfileirados.append(a)
        try:
            with TestCase.captureOnCommitCallbacks(execute=True):
                r = c.post('/instalacao/comunicados/', {**dados, 'acao': 'enviar'})
        finally:
            tasks.enviar_comunicado.delay = original
        novo = Comunicado.objects.order_by('-created_at').first()
        confere(r.status_code == 302 and novo and novo.situacao == 'fila' and novo.criado_por_id == su.id
                and enfileirados == [(str(novo.id),)], 'com o código: grava e vai para o worker')
        evento = AuditEvent.objects.filter(action='superadmin.comunicado_criado').order_by('-created_at').first()
        confere(evento and 'Domingo' not in json.dumps(evento.integrity_metadata), 'trilha sem o texto')

        # ---------------------------------------------------------------- 5
        secao('5. O envio')
        priv, p256dh, auth = aparelho_novo()
        PushSubscription.objects.filter(user=medico.user).delete()
        PushSubscription.objects.create(user=medico.user, endpoint='https://fcm.googleapis.com/fcm/send/c1',
                                        p256dh=p256dh, auth=auth)
        Comunicado.objects.filter(pk=novo.pk).update(texto='Manutenção domingo às 2h. ' + 'Mais detalhes. ' * 20)
        servico = ServicoFalso()
        import httpx
        cliente = httpx.Client
        httpx.Client = servico
        try:
            comunicados.enviar(str(novo.id))
            segunda = comunicados.enviar(str(novo.id))
        finally:
            httpx.Client = cliente
        linhas = Notification.objects.filter(target_type='comunicado', target_id=novo.id)
        esperados = comunicados.destinatarios('aviso', 'clinica', str(clinica.id))
        confere(linhas.count() == len(esperados) and linhas.filter(user=medico.user).exists(),
                'uma linha no sino por vínculo')
        confere(segunda is None and Notification.objects.filter(target_id=novo.id).count() == len(esperados),
                'a tarefa repetida não entrega de novo')
        confere(len(servico.pedidos) == 1, 'um aviso no celular por aparelho')
        msg = json.loads(abrir(servico.pedidos[0][2], priv, p256dh, auth))
        confere(msg['titulo'] == 'Manutenção' and msg['corpo'].startswith('Manutenção domingo')
                and len(msg['corpo']) <= comunicados.RESUMO_NO_CELULAR and msg['corpo'].endswith('…'),
                'o celular recebe o título e o começo do texto')
        confere(msg['url'] == f'/app/notifications/comunicado/{novo.id}/', 'o toque abre a página do comunicado')
        novo.refresh_from_db()
        confere(novo.situacao == 'enviado' and novo.pessoas == len({u for _, u in esperados})
                and novo.aparelhos_entregues == 1, 'o histórico com os números')

        # ---------------------------------------------------------------- 6
        secao('6. A página')
        Comunicado.objects.filter(pk=novo.pk).update(texto='Linha 1\n<script>alert(1)</script>')
        cm = logado(medico.user)
        r = cm.get(f'/app/notifications/comunicado/{novo.id}/')
        html = r.content.decode()
        confere(r.status_code == 200 and '&lt;script&gt;' in html and '<script>alert' not in html
                and 'Linha 1<br>' in html, 'abre para quem recebeu, com o texto escapado')
        confere('href="/ajuda/"' in html and 'Aviso do sistema' in html, 'o link e a etiqueta do tipo')
        confere(not linhas.filter(user=medico.user, tenant=clinica, read_at__isnull=True).exists(),
                'abrir marca como lida')
        outra = Tenant.objects.exclude(pk=clinica.pk).exclude(status=TenantStatus.CLOSED).first()
        de_fora = Membership.objects.filter(tenant=outra, status=MembershipStatus.ACTIVE).exclude(
            user__in=Membership.objects.filter(tenant=clinica).values('user')).select_related('user').first() \
            if outra else None
        if de_fora:
            c3 = Client()
            c3.force_login(de_fora.user)
            s = c3.session
            s['tenant_id'] = str(outra.id)
            s.save()
            confere(c3.get(f'/app/notifications/comunicado/{novo.id}/').status_code == 404,
                    'quem não recebeu: 404')
        linha = linhas.filter(user=secretaria.user, tenant=clinica).first()
        if linha:
            r = logado(secretaria.user).post(f'/app/notifications/{linha.id}/abrir/')
            confere(r.status_code == 302 and r['Location'] == f'/app/notifications/comunicado/{novo.id}/',
                    '"Ler comunicado" no sino leva à página')

        raise _Desfazer
except _Desfazer:
    pass
finally:
    contract.VERSAO, plans.CONTRATO_COM_PROPAGANDA = contrato_original, limiar_original

print()
if falhas:
    print(f'{len(falhas)} falha(s):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('Tudo certo.')
