"""WhatsApp pela Twilio da própria clínica (BYO, 2026-11-25).

Tenta quebrar. **Contra uma Twilio simulada** (a chamada HTTP é trocada por
uma função que responde como a API documentada e registra o que recebeu):
o roteiro prova o que o sistema manda e como reage, não que a Twilio real
aceita — isso é a homologação com uma conta de verdade, pendente em
`docs/governance/whatsapp-twilio.md`. A assinatura do aviso de status é
conferida contra o vetor da documentação da Twilio e contra vetores
calculados pelo SDK oficial (`twilio` 9.13.0, `RequestValidator`).
"""
from django.conf import settings as dj

dj.ALLOWED_HOSTS = list(dj.ALLOWED_HOSTS) + ['testserver']
dj.SECURE_SSL_REDIRECT = False
dj.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

import json
import secrets
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from django.http import QueryDict
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from base.crypto import encrypt_secret, mask_secret
from base.models import InstallationSettings
from communications import services, whatsapp_twilio as wa
from communications.models import (
    Delivery, DeliveryAttempt, DeliveryChannel, DeliveryStatus, DocumentAccessToken,
    WhatsAppModelo, WhatsAppTwilio,
)
from communications.reconciliation import reconcile_pending_whatsapp
from documents.models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from patients.contacts import SELF_RELATIONSHIP
from patients.models import Patient, PatientContact, RegistrationStage
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok   " if ok else "FALHA"}  {rotulo:<66} -> {obtido!r}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado!r}, obtido {obtido!r}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo_de(papel, clinica=tenant):
    return Membership.objects.filter(
        tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').order_by('user__email').first()


dono = vinculo_de('owner')
secretaria = vinculo_de('secretary')
medico = vinculo_de('doctor')
dono_b = vinculo_de('owner', tenant_b)

SID_A, TOKEN_A = 'AC' + 'a' * 32, 'f' * 32
SID_B, TOKEN_B = 'AC' + 'b' * 32, 'e' * 32
NUM_A, NUM_B = '+551130001000', '+552130002000'
HX = {evento: 'HX' + format(i + 1, 'x') * 32 for i, evento in enumerate(wa.EVENTOS)}

criados = {'p': [], 'a': [], 'doc': []}
config_inst = InstallationSettings.carregar()
liberado_antes = config_inst.whatsapp_twilio_liberado


# --------------------------------------------------------- Twilio simulada

class Resposta:
    def __init__(self, status, corpo):
        self.status_code = status
        self._corpo = corpo

    def json(self):
        return self._corpo


class TwilioFalsa:
    """Responde como a API documentada, por conta (Account SID da autenticação)."""

    def __init__(self):
        self.chamadas = []
        self.contas = {}       # sid -> dict(token, status, remetentes, conteudos, envio)
        self.mensagens = {}

    def conta(self, sid, token, numero, status='active', remetente='ONLINE'):
        self.contas[sid] = {
            'token': token, 'status': status, 'envio': None,
            'remetentes': [{
                'sender_id': f'whatsapp:{numero}', 'status': remetente,
                'properties': {'quality_rating': 'HIGH', 'messaging_limit': '1K Customers/24hr'},
            }],
            'conteudos': {},
        }

    fora = False

    def __call__(self, metodo, url, data=None, params=None, auth=None, timeout=None):
        self.chamadas.append({'metodo': metodo, 'url': url, 'data': dict(data or {}), 'auth': auth})
        if self.fora:
            return Resposta(503, {})
        sid, token = auth
        conta = self.contas.get(sid)
        if conta is None or conta['token'] != token:
            return Resposta(401, {'code': 20003, 'message': 'Authenticate', 'status': 401})
        if url.endswith(f'/Accounts/{sid}.json'):
            return Resposta(200, {'sid': sid, 'status': conta['status'], 'type': 'Full'})
        if url.endswith('/Channels/Senders'):
            return Resposta(200, {'senders': conta['remetentes'], 'meta': {}})
        if '/v1/Content/' in url:
            hx = url.split('/v1/Content/')[1].split('/')[0]
            c = conta['conteudos'].get(hx)
            if c is None:
                return Resposta(404, {'code': 20404, 'message': 'not found', 'status': 404})
            if url.endswith('/ApprovalRequests'):
                return Resposta(200, {'whatsapp': {'status': c['aprovacao'], 'rejection_reason': c.get('motivo', '')}})
            return Resposta(200, {
                'sid': hx, 'friendly_name': c['nome'], 'language': 'pt_BR',
                'variables': {str(i): 'x' for i in range(1, c['variaveis'] + 1)},
            })
        if metodo == 'POST' and url.endswith(f'/Accounts/{sid}/Messages.json'):
            if conta['envio'] is not None:
                return Resposta(*conta['envio'])
            msid = 'SM' + secrets.token_hex(16)
            self.mensagens[msid] = 'queued'
            return Resposta(201, {'sid': msid, 'status': 'queued'})
        if '/Messages/' in url and metodo == 'GET':
            msid = url.rsplit('/', 1)[1].removesuffix('.json')
            return Resposta(200, {'sid': msid, 'status': self.mensagens.get(msid, 'sent'), 'error_code': None})
        return Resposta(404, {'code': 20404, 'status': 404})

    def envios(self):
        return [c for c in self.chamadas if c['metodo'] == 'POST' and c['url'].endswith('Messages.json')]


falsa = TwilioFalsa()


def paciente(nome, telefone='(11) 98765-4321', whatsapp=True, sms=True, email=True, documentos=False):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome, registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['p'].append(p.id)
    agora = timezone.now()
    PatientContact.objects.create(
        tenant=tenant, patient=p, name=nome, relationship=SELF_RELATIONSHIP,
        phone=telefone, email='paciente.wa@exemplo.test',
        sms_enabled=sms, verified_phone_at=agora if sms else None,
        email_enabled=email, verified_email_at=agora if email else None,
        authorized_for_documents=documentos,
        whatsapp_opt_in_at=agora if whatsapp else None,
        whatsapp_opt_in_evidence='autorizou no roteiro' if whatsapp else '',
    )
    return p


_hora = [0]


def marcar(pac, clinica=tenant, quem=None):
    _hora[0] += 1
    quando = timezone.now() + timedelta(days=70, hours=_hora[0])
    fim = quando + timedelta(minutes=40)
    a = Appointment.objects.create(
        tenant=clinica, patient=pac, physician_membership=quem or medico,
        starts_at=quando, ends_at=fim, occupied_range=(quando, fim),
        status=AppointmentStatus.CONFIRMED, type=AppointmentType.FOLLOW_UP,
    )
    criados['a'].append(a.id)
    return a


def cliente(v, clinica=tenant):
    c = Client()
    c.force_login(v.user)
    s = c.session
    s['tenant_id'] = str(clinica.id)
    s.save()
    return c


def configurar(clinica, sid, token, numero):
    config = wa.config_da_clinica(clinica.id, criar=True)
    config.account_sid, config.numero = sid, numero
    config.auth_token_ciphertext, config.auth_token_metadata = encrypt_secret(token)
    config.auth_token_hint = mask_secret(token)
    config.invalidar_verificacao()
    config.save()
    return config


def modelo(clinica, evento, variaveis=None, aprovacao='approved', ligado=True, conta=SID_A):
    hx = HX[evento] if clinica == tenant else HX[evento].replace('HX', 'HX', 1)[:-1] + 'b'
    m, _ = WhatsAppModelo.objects.get_or_create(tenant=clinica, evento=evento)
    m.content_sid, m.ligado = hx, ligado
    m.save()
    falsa.contas[conta]['conteudos'][hx] = {
        'nome': f'{evento}_roteiro', 'aprovacao': aprovacao,
        'variaveis': len(wa.EVENTOS[evento]['variaveis']) if variaveis is None else variaveis,
    }
    return m


def assinar(config, dados, token=None):
    return wa.assinatura_esperada(token or TOKEN_A, wa.url_do_status(config), QueryDict(urlencode(dados)))


def aviso(config, dados, assinatura=None, token_url=None):
    corpo = urlencode(dados)
    return Client().post(
        f'/whatsapp/status/{token_url or config.token_webhook}/', corpo,
        content_type='application/x-www-form-urlencoded',
        HTTP_X_TWILIO_SIGNATURE=assinatura if assinatura is not None else assinar(config, dados),
    )


try:
    with patch('httpx.request', falsa):
        print('=== 1. assinatura do aviso: o algoritmo da Twilio ===')
        # O vetor da documentação (twilio.com/docs/usage/security).
        doc = QueryDict(urlencode({
            'CallSid': 'CA1234567890ABCDE', 'Caller': '+12349013030', 'Digits': '1234',
            'From': '+12349013030', 'To': '+18005551212',
        }))
        conferir('o vetor da documentação da Twilio',
                 wa.assinatura_esperada('12345', 'https://mycompany.com/myapp.php?foo=1&bar=2', doc),
                 '0/KCTR6DLpKmkAf8muzZqo1nDgQ=')
        # Calculado pelo SDK oficial (twilio 9.13.0, RequestValidator.compute_signature).
        p2 = QueryDict(urlencode({
            'AccountSid': 'AC' + '0' * 32, 'MessageSid': 'SM' + '1' * 32,
            'MessageStatus': 'delivered', 'ApiVersion': '2010-04-01', 'ChannelPrefix': 'whatsapp',
        }))
        url2 = 'https://neurodoc.example/whatsapp/status/tok_abc/'
        conferir('o vetor de aviso de WhatsApp do SDK oficial',
                 wa.assinatura_esperada('12345', url2, p2), 'FSJG06+q7QzBn1rJwy3S7KOed4I=')
        com_porta = wa.assinatura_esperada('12345', 'https://neurodoc.example:443/whatsapp/status/tok_abc/', p2)
        conferir('assinada com a porta :443 também vale', wa.assinatura_valida('12345', url2, p2, com_porta), True)
        conferir('token errado não vale',
                 wa.assinatura_valida('54321', url2, p2, 'FSJG06+q7QzBn1rJwy3S7KOed4I='), False)
        adulterado = p2.copy()
        adulterado['MessageStatus'] = 'failed'
        conferir('parâmetro adulterado não vale',
                 wa.assinatura_valida('12345', url2, adulterado, 'FSJG06+q7QzBn1rJwy3S7KOed4I='), False)
        conferir('assinatura vazia não vale', wa.assinatura_valida('12345', url2, p2, ''), False)

        print('\n=== 2. nasce desligado ===')
        WhatsAppTwilio.objects.filter(tenant__in=[tenant, tenant_b]).delete()
        WhatsAppModelo.objects.filter(tenant__in=[tenant, tenant_b]).delete()
        config_inst.whatsapp_twilio_liberado = False
        config_inst.save(update_fields=['whatsapp_twilio_liberado'])
        conferir('a instalação nasce recolhida (padrão do modelo)',
                 InstallationSettings._meta.get_field('whatsapp_twilio_liberado').default, False)
        conferir('sem configuração: "não configurado"', wa.estado(None), 'nao_configurado')
        conferir('nada sai por WhatsApp', wa.para_enviar(tenant.id, 'lembrete'), None)
        conferir('contato sem aceite: SMS como antes',
                 services._channels_for(PatientContact(
                     phone='11987654321', sms_enabled=True, verified_phone_at=timezone.now(),
                 ), whatsapp=True), [DeliveryChannel.SMS])

        print('\n=== 3. a tela: quem abre e o que ela recusa ===')
        dono_c = cliente(dono)
        url = reverse('messaging:whatsapp-twilio')
        conferir('o dono abre a tela', dono_c.get(url).status_code, 200)
        r = cliente(secretaria).get(url)
        conferir('a secretária não abre (sem MANAGE_INTEGRATIONS)', r.status_code in (403, 404), True)
        conferir('o tutorial abre sem login',
                 Client().get(reverse('onboarding:help-article', args=['whatsapp-twilio'])).status_code, 200)
        with patch('communications.tasks.verificar_whatsapp_twilio_task.delay') as fila:
            r = dono_c.post(reverse('messaging:whatsapp-twilio-credenciais'), {
                'account_sid': 'XX123', 'auth_token': 'curto', 'numero': '123',
            })
            conferir('formato errado: a tela volta com erro', r.status_code, 200)
            conferir('  e nada é gravado', WhatsAppTwilio.objects.filter(tenant=tenant).exclude(account_sid='').exists(), False)
            r = dono_c.post(reverse('messaging:whatsapp-twilio-credenciais'), {
                'account_sid': SID_A, 'auth_token': TOKEN_A, 'numero': '(11) 3000-1000',
            })
            conferir('credenciais certas: salva e volta à tela', r.status_code, 302)
        config = wa.config_da_clinica(tenant.id)
        conferir('o número fica em E.164', config.numero, NUM_A)
        conferir('o token fica cifrado (nunca em claro no banco)', TOKEN_A in config.auth_token_ciphertext, False)
        conferir('  e é lido de volta', config.auth_token(), TOKEN_A)
        conferir('salvar não é funcionar: "pendente"', wa.estado(config), 'pendente')
        html = dono_c.get(url).content.decode()
        conferir('a tela não mostra o token', TOKEN_A in html, False)
        conferir('  só a máscara', config.auth_token_hint in html, True)
        trilha = AuditEvent.objects.filter(
            tenant=tenant, action='communications.whatsapp_config_atualizada',
        ).order_by('-created_at').first()
        conferir('a trilha registra os campos, sem o token', TOKEN_A in json.dumps(trilha.integrity_metadata), False)
        conferir('  nem o número', '3000' in json.dumps(trilha.integrity_metadata), False)

        print('\n=== 4. a verificação contra a Twilio (simulada) ===')
        falsa.conta(SID_A, TOKEN_A, NUM_A)
        conferir('conta ativa e número ONLINE: verifica', wa.verificar(config), True)
        config.refresh_from_db()
        conferir('  vira "validado" (ainda não ativo)', wa.estado(config), 'desativado')
        conferir('  e a verificação usou a credencial da própria clínica',
                 {c['auth'][0] for c in falsa.chamadas}, {SID_A})
        falsa.contas[SID_A]['remetentes'][0]['status'] = 'OFFLINE'
        conferir('número OFFLINE: não verifica', wa.verificar(config), False)
        config.refresh_from_db()
        conferir('  vira "inválido" com o motivo', (wa.estado(config), 'ONLINE' in config.erro_texto), ('invalido', True))
        falsa.contas[SID_A]['remetentes'][0]['status'] = 'ONLINE'
        falsa.contas[SID_A]['token'] = 'trocado-na-twilio'
        conferir('token trocado na Twilio: não verifica', wa.verificar(config), False)
        config.refresh_from_db()
        conferir('  e diz que a credencial foi recusada',
                 (config.erro_codigo, 'recusou' in config.erro_texto), ('20003', True))
        falsa.contas[SID_A]['token'] = TOKEN_A
        conferir('corrigido, verifica de novo', wa.verificar(config), True)
        config.refresh_from_db()

        print('\n=== 5. os modelos ===')
        r = dono_c.post(reverse('messaging:whatsapp-twilio-modelos'), {'sid_lembrete': 'nao-e-hx', 'ligado_lembrete': 'on'})
        conferir('identificador fora do formato não é gravado',
                 WhatsAppModelo.objects.filter(tenant=tenant, evento='lembrete').exclude(content_sid='').exists(), False)
        m = modelo(tenant, 'lembrete')
        conferir('aprovado e com 3 variáveis: serve', wa.conferir_modelo(config, m), True)
        falsa.contas[SID_A]['conteudos'][m.content_sid]['aprovacao'] = 'pending'
        conferir('pendente na Meta: não serve', wa.conferir_modelo(config, m), False)
        falsa.contas[SID_A]['conteudos'][m.content_sid].update(aprovacao='approved', variaveis=2)
        conferir('variáveis a menos: não serve', wa.conferir_modelo(config, m), False)
        m.refresh_from_db()
        conferir('  e diz quais faltam', 'nome da clínica' in m.erro_texto, True)
        falsa.contas[SID_A]['conteudos'][m.content_sid]['variaveis'] = 3
        wa.conferir_modelo(config, m)

        print('\n=== 6. operacional só com as quatro chaves ===')
        conferir('verificado + modelo, mas desativado', wa.para_enviar(tenant.id, 'lembrete'), None)
        config.ativo = True
        config.save()
        conferir('ativo, mas a instalação recolhida', wa.para_enviar(tenant.id, 'lembrete'), None)
        config_inst.whatsapp_twilio_liberado = True
        config_inst.save(update_fields=['whatsapp_twilio_liberado'])
        conferir('ativo, liberado e modelo aprovado: sai', wa.para_enviar(tenant.id, 'lembrete') is not None, True)
        conferir('  estado "operacional"', wa.estado(config), 'operacional')
        conferir('ocasião sem modelo ligado não sai', wa.para_enviar(tenant.id, 'cancelado'), None)

        print('\n=== 7. o lembrete pelo WhatsApp da clínica ===')
        pac = paciente('ROTEIRO WA LEMBRETE')
        a = marcar(pac)
        antes = len(falsa.envios())
        entregas = services.deliver_appointment_reminder(a, a.row_version)
        canais = sorted(e.channel for e in entregas)
        conferir('e-mail e WhatsApp, e não SMS (substitui, não soma)', canais, ['email', 'whatsapp'])
        envio = falsa.envios()[-1]
        conferir('uma chamada à Twilio', len(falsa.envios()) - antes, 1)
        conferir('  pela conta da clínica', envio['auth'][0], SID_A)
        conferir('  ao número do paciente em E.164', envio['data']['To'], 'whatsapp:+5511987654321')
        conferir('  do número da clínica', envio['data']['From'], f'whatsapp:{NUM_A}')
        conferir('  com o modelo da ocasião', envio['data']['ContentSid'], HX['lembrete'])
        conferir('  sem texto livre (Body)', 'Body' in envio['data'], False)
        variaveis = json.loads(envio['data']['ContentVariables'])
        local = timezone.localtime(a.starts_at)
        conferir('  variáveis: clínica, data e hora',
                 variaveis, {'1': (tenant.trade_name or tenant.legal_name)[:60],
                             '2': local.strftime('%d/%m/%Y'), '3': local.strftime('%H:%M')})
        # O nome completo, e não pedaços: a razão social de demonstração
        # ("…Neurologia…") contém o sobrenome do médico de demonstração.
        conferir('  nada do médico nem do paciente',
                 any(t in json.loads(envio['data']['ContentVariables']).values() or
                     t in envio['data']['ContentVariables']
                     for t in [pac.full_name, medico.user.get_full_name()]), False)
        conferir('  e o aviso de status vem para a URL da clínica',
                 envio['data']['StatusCallback'], wa.url_do_status(config))
        entrega_wa = next(e for e in entregas if e.channel == 'whatsapp')
        entrega_wa.refresh_from_db()
        conferir('a entrega fica aceita com o SID', (entrega_wa.status, entrega_wa.provider_id.startswith('SM')),
                 (DeliveryStatus.ACCEPTED, True))
        services.deliver_appointment_reminder(a, a.row_version)
        conferir('o mesmo evento de novo não reenvia', len(falsa.envios()) - antes, 1)

        sem = paciente('ROTEIRO WA SEM ACEITE', whatsapp=False)
        b = marcar(sem)
        canais = sorted(e.channel for e in services.deliver_appointment_reminder(b, b.row_version))
        conferir('sem o aceite: e-mail e SMS, como antes', canais, ['email', 'sms'])

        print('\n=== 8. o aviso de status ===')
        sid_msg = entrega_wa.provider_id
        dados = {'AccountSid': SID_A, 'MessageSid': sid_msg, 'MessageStatus': 'delivered'}
        conferir('assinatura certa: 204', aviso(config, dados).status_code, 204)
        entrega_wa.refresh_from_db()
        conferir('  entregue', entrega_wa.status, DeliveryStatus.DELIVERED)
        tentativas = entrega_wa.attempts.count()
        aviso(config, dados)
        conferir('o mesmo aviso de novo não grava outra tentativa', entrega_wa.attempts.count(), tentativas)
        aviso(config, {**dados, 'MessageStatus': 'sent'})
        entrega_wa.refresh_from_db()
        conferir('"sent" atrasado não regride', entrega_wa.status, DeliveryStatus.DELIVERED)
        outra = services.deliver_appointment_reminder(marcar(pac), 1)
        alvo = next(e for e in outra if e.channel == 'whatsapp')
        falso = {'AccountSid': SID_A, 'MessageSid': alvo.provider_id, 'MessageStatus': 'failed'}
        conferir('assinatura errada: 403', aviso(config, falso, assinatura='AAAA').status_code, 403)
        conferir('assinada com outro token: 403', aviso(config, falso, assinar(config, falso, TOKEN_B)).status_code, 403)
        alvo.refresh_from_db()
        conferir('  e nada muda', alvo.status, DeliveryStatus.ACCEPTED)
        outra_conta = {**falso, 'AccountSid': SID_B}
        conferir('AccountSid de outra conta: 403', aviso(config, outra_conta).status_code, 403)
        conferir('token de URL desconhecido: 404', aviso(config, falso, token_url='naoexiste').status_code, 404)
        conferir('GET: 404', Client().get(f'/whatsapp/status/{config.token_webhook}/').status_code, 404)
        grande = {**falso, 'Lixo': 'x' * 20000}
        conferir('corpo grande demais: 413', aviso(config, grande).status_code, 413)
        conferir('falhou com código: vira "Falhou"',
                 aviso(config, {**falso, 'ErrorCode': '63016'}).status_code, 204)
        alvo.refresh_from_db()
        ultima = alvo.attempts.order_by('-attempt_number').first()
        conferir('  com o código e a explicação em português',
                 (alvo.status, ultima.provider_code, 'janela' in ultima.sanitized_error),
                 (DeliveryStatus.FAILED, 'wa_status:failed:63016', True))

        print('\n=== 9. isolamento entre clínicas ===')
        config_b = configurar(tenant_b, SID_B, TOKEN_B, NUM_B)
        falsa.conta(SID_B, TOKEN_B, NUM_B)
        wa.verificar(config_b)
        config_b.refresh_from_db()
        conferir('a clínica B tem a própria configuração', (config_b.account_sid, config_b.tenant_id), (SID_B, tenant_b.id))
        conferir('os tokens de URL são diferentes', config_b.token_webhook != config.token_webhook, True)
        conferir('B sem modelo nem ativação: nada sai por B', wa.para_enviar(tenant_b.id, 'lembrete'), None)
        conferir('e A continua saindo por A', wa.para_enviar(tenant.id, 'lembrete')[0].account_sid, SID_A)
        # Um aviso legítimo da conta B, na URL de B, apontando para a entrega de A.
        dados_b = {'AccountSid': SID_B, 'MessageSid': sid_msg, 'MessageStatus': 'failed'}
        r = aviso(config_b, dados_b, assinar(config_b, dados_b, TOKEN_B))
        entrega_wa.refresh_from_db()
        conferir('aviso válido de B não mexe em entrega de A', (r.status_code, entrega_wa.status),
                 (204, DeliveryStatus.DELIVERED))
        dados_ba = {'AccountSid': SID_B, 'MessageSid': alvo.provider_id, 'MessageStatus': 'delivered'}
        r = aviso(config, dados_ba, assinar(config, dados_ba, TOKEN_B))
        conferir('assinado por B na URL de A: 403', r.status_code, 403)
        tela_b = cliente(dono_b, tenant_b).get(url).content.decode()
        conferir('a tela de B mostra o número de B, e não o de A', (NUM_B in tela_b, NUM_A in tela_b), (True, False))
        r = cliente(dono_b, tenant_b).post(reverse('messaging:whatsapp-twilio-ativar'), {'acao': 'suspender'})
        config.refresh_from_db()
        conferir('suspender em B não suspende A', config.ativo, True)

        print('\n=== 10. falhas da Twilio no envio ===')
        p3 = paciente('ROTEIRO WA FALHAS')
        falsa.contas[SID_A]['envio'] = (400, {'code': 63016, 'message': 'Outside window', 'status': 400})
        lote = services.deliver_appointment_reminder(marcar(p3), 1)
        e = next(x for x in lote if x.channel == 'whatsapp')
        e.refresh_from_db()
        t = e.attempts.order_by('-attempt_number').first()
        conferir('recusa (400): "Falhou" com o código, sem nova tentativa',
                 (e.status, t.provider_code), (DeliveryStatus.FAILED, 'twilio:63016'))
        conferir('  e o SMS sai de reserva (o paciente não fica sem aviso)',
                 sorted(x.channel for x in lote), ['email', 'sms', 'whatsapp'])
        p_sem_sms = paciente('ROTEIRO WA SEM SMS', sms=False)
        lote = services.deliver_appointment_reminder(marcar(p_sem_sms), 1)
        conferir('  sem SMS habilitado, não inventa SMS', sorted(x.channel for x in lote), ['email', 'whatsapp'])
        falsa.contas[SID_A]['envio'] = (503, {'status': 503})
        with services.tentar_de_novo_se_o_transporte_falhar(ultima_tentativa=True):
            e = next(x for x in services.deliver_appointment_reminder(marcar(p3), 1) if x.channel == 'whatsapp')
        e.refresh_from_db()
        conferir('Twilio fora (503) até a última tentativa: "Falhou"', e.status, DeliveryStatus.FAILED)
        try:
            with services.tentar_de_novo_se_o_transporte_falhar(ultima_tentativa=False):
                e = next(x for x in services.deliver_appointment_reminder(marcar(p3), 1) if x.channel == 'whatsapp')
            adiou = False
        except services.EntregaAdiada:
            adiou = True
        e.refresh_from_db()
        conferir('Twilio fora antes da última: volta à fila para tentar de novo', (adiou, e.status),
                 (True, DeliveryStatus.PENDING))
        falsa.contas[SID_A]['envio'] = (401, {'code': 20003, 'status': 401})
        e = next(x for x in services.deliver_appointment_reminder(marcar(p3), 1) if x.channel == 'whatsapp')
        config.refresh_from_db()
        conferir('credencial recusada no envio: a configuração vira "inválido"', wa.estado(config), 'invalido')
        falsa.contas[SID_A]['envio'] = None
        wa.verificar(config)
        config.refresh_from_db()
        # Escolhido o canal, a clínica suspende antes do envio.
        d = Delivery.objects.create(
            tenant=tenant, appointment=marcar(p3), contact=p3.contacts.first(),
            channel=DeliveryChannel.WHATSAPP, idempotency_key=f'roteiro:{secrets.token_hex(6)}', event_version=1,
        )
        config.ativo = False
        config.save()
        services._send(d, '', whatsapp=('lembrete', ['C', '01/01/2030', '09:00']))
        d.refresh_from_db()
        conferir('suspensa entre a escolha e o envio: "canal indisponível"', d.status, DeliveryStatus.CHANNEL_UNAVAILABLE)
        config.ativo = True
        config.save()
        d2 = Delivery.objects.create(
            tenant=tenant, appointment=marcar(p3), contact=p3.contacts.first(),
            channel=DeliveryChannel.WHATSAPP, idempotency_key=f'roteiro:{secrets.token_hex(6)}', event_version=1,
        )
        services._send(d2, 'texto livre')
        d2.refresh_from_db()
        conferir('entrega de WhatsApp sem modelo nunca vira texto livre', d2.status, DeliveryStatus.CHANNEL_UNAVAILABLE)

        print('\n=== 11. consentimento ===')
        c = pac.contacts.first()
        c.whatsapp_opt_out_at = timezone.now()
        c.save()
        conferir('aceite revogado: o contato sai do WhatsApp', services._channels_for(c, whatsapp=True), ['email', 'sms'])
        from patients.forms import PatientContactForm

        form = PatientContactForm(data={
            'name': 'X', 'phone': '11987654321', 'accepts_whatsapp': 'on',
        })
        conferir('aceite sem procedência é recusado', 'whatsapp_opt_in_evidence' in form.errors, True)
        from patients.contacts import remove_contact

        enc = paciente('ROTEIRO WA ENCERRADO')
        contato = enc.contacts.first()
        Delivery.objects.create(  # com histórico, o contato é encerrado e não apagado
            tenant=tenant, appointment=marcar(enc), contact=contato,
            channel=DeliveryChannel.EMAIL, idempotency_key=f'roteiro:{secrets.token_hex(6)}', event_version=1,
            status=DeliveryStatus.ACCEPTED,
        )
        conferir('contato encerrado', remove_contact(contato), 'encerrado')
        contato.refresh_from_db()
        conferir('  perde o aceite do WhatsApp', contato.aceita_whatsapp, False)

        print('\n=== 12. aviso de horário e documento ===')
        modelo(tenant, 'marcado')
        wa.conferir_modelo(config, WhatsAppModelo.objects.get(tenant=tenant, evento='marcado'))
        pn = paciente('ROTEIRO WA AVISO')
        an = marcar(pn)
        entregas = services.deliver_appointment_notice(an, 'booked', an.row_version)
        conferir('aviso de marcação: e-mail e WhatsApp', sorted(e.channel for e in entregas), ['email', 'whatsapp'])
        chave_email = next(e.idempotency_key for e in entregas if e.channel == 'email')
        conferir('  a chave do e-mail continua a de antes', chave_email.endswith(':whatsapp'), False)
        modelo(tenant, 'documento')
        wa.conferir_modelo(config, WhatsAppModelo.objects.get(tenant=tenant, evento='documento'))
        pd = paciente('ROTEIRO WA DOC', documentos=True)
        doc = MedicalDocument.objects.create(
            tenant=tenant, patient=pd, physician=medico,
            kind=MedicalDocumentKind.REPORT, status=MedicalDocumentStatus.ISSUED,
            document_number=f'REL-WA-{secrets.token_hex(3)}', issued_at=timezone.now(),
            content_snapshot={'report_text': 'Relatorio do roteiro do WhatsApp.'},
            validation_token=secrets.token_urlsafe(16),
        )
        criados['doc'].append(doc.id)
        entregas = services.deliver_document(doc)
        conferir('documento: e-mail e WhatsApp', sorted(e.channel for e in entregas), ['email', 'whatsapp'])
        vars_doc = json.loads(falsa.envios()[-1]['data']['ContentVariables'])
        conferir('  o link seguro de sempre (/d/)', '/d/' in vars_doc['2'], True)
        conferir('  e nada do documento (tipo, número, texto)',
                 any(t in json.dumps(vars_doc) for t in ['Relat', 'REL-WA', 'roteiro']), False)

        print('\n=== 13. a consulta periódica (aviso que não chegou) ===')
        pr = paciente('ROTEIRO WA CONSULTA')
        e = next(x for x in services.deliver_appointment_reminder(marcar(pr), 1) if x.channel == 'whatsapp')
        Delivery.objects.filter(id=e.id).update(next_attempt_at=timezone.now() - timedelta(minutes=1))
        falsa.mensagens[e.provider_id] = 'delivered'
        reconcile_pending_whatsapp()
        e.refresh_from_db()
        conferir('a consulta acha "delivered": entregue', e.status, DeliveryStatus.DELIVERED)
        e = next(x for x in services.deliver_appointment_reminder(marcar(pr), 1) if x.channel == 'whatsapp')
        falsa.mensagens[e.provider_id] = 'sent'
        for _ in range(2):
            Delivery.objects.filter(id=e.id).update(next_attempt_at=timezone.now() - timedelta(minutes=1))
            reconcile_pending_whatsapp()
        e.refresh_from_db()
        conferir('sem resposta final em duas consultas: "sem confirmação"', e.status, DeliveryStatus.UNKNOWN)

        print('\n=== 14. envio de teste ===')
        from communications.tasks import enviar_teste_whatsapp_twilio_task

        enviar_teste_whatsapp_twilio_task.apply(args=[str(tenant.id), dono.user_id, 'lembrete', '(11) 91234-5678'])
        config.refresh_from_db()
        conferir('o teste sai e guarda só o SID', (config.teste_sid.startswith('SM'), config.teste_status),
                 (True, 'aceita pela Twilio'))
        conferir('  o celular do teste não fica no banco',
                 '91234' in json.dumps([config.teste_sid, config.teste_status, config.teste_erro]), False)
        dt = {'AccountSid': SID_A, 'MessageSid': config.teste_sid, 'MessageStatus': 'read'}
        aviso(config, dt)
        aviso(config, {**dt, 'MessageStatus': 'sent'})
        config.refresh_from_db()
        conferir('o aviso do teste vai à tela, sem regredir', config.teste_status, 'read')

        print('\n=== 15. o que não pode mudar ===')
        import pathlib

        from base.management.commands.rotate_secrets_master_key import CAMPOS

        conferir('o Auth Token entra na rotação da chave-mestra',
                 any(m == 'communications.WhatsAppTwilio' for m, *_ in CAMPOS), True)
        fonte = pathlib.Path(dj.BASE_DIR, 'communications', 'whatsapp_views.py').read_text(encoding='utf-8')
        conferir('a tela não chama a Twilio (verificar e testar vão ao worker)',
                 any(f in fonte for f in ('enviar_modelo(', 'wa.verificar(', 'consultar_mensagem(')), False)

        print('\n=== 16a. a verificação sempre termina ===')
        from communications import whatsapp_views
        from communications.tasks import verificar_whatsapp_twilio_task

        falsa.fora = True
        config.verificacao_pedida_em = timezone.now()
        config.save()
        verificar_whatsapp_twilio_task.apply(args=[str(tenant.id), dono.user_id], retries=2)
        config.refresh_from_db()
        conferir('Twilio fora na última tentativa: termina com o motivo',
                 (config.erro_codigo, config.verificacao_concluida_em is not None,
                  whatsapp_views._verificando(config)), ('rede', True, False))
        falsa.fora = False
        wa.verificar(config)
        config.refresh_from_db()
        config.verificacao_pedida_em = timezone.now()
        config.verificacao_concluida_em = config.verificacao_pedida_em - timedelta(seconds=1)
        conferir('verificação pedida agora: a tela espera', whatsapp_views._verificando(config), True)
        config.verificacao_pedida_em = timezone.now() - timedelta(minutes=10)
        conferir('pedida há 10 min sem resposta: a tela para de esperar', whatsapp_views._verificando(config), False)
        config.save()

        print('\n=== 16. suspender, recolher e apagar ===')
        dono_c.post(reverse('messaging:whatsapp-twilio-ativar'), {'acao': 'suspender'})
        config.refresh_from_db()
        conferir('suspender: nada sai', (config.ativo, wa.para_enviar(tenant.id, 'lembrete')), (False, None))
        dono_c.post(reverse('messaging:whatsapp-twilio-ativar'), {'acao': 'ativar'})
        conferir('reativar', wa.para_enviar(tenant.id, 'lembrete') is not None, True)
        config_inst.whatsapp_twilio_liberado = False
        config_inst.save(update_fields=['whatsapp_twilio_liberado'])
        conferir('a instalação recolhe: nada sai em clínica nenhuma', wa.para_enviar(tenant.id, 'lembrete'), None)
        dono_c.post(reverse('messaging:whatsapp-twilio-remover'))
        config.refresh_from_db()
        conferir('apagar: sem token e "não configurado"',
                 (config.auth_token_ciphertext, wa.estado(config)), ('', 'nao_configurado'))
        conferir('  e as ocasiões desligadas',
                 WhatsAppModelo.objects.filter(tenant=tenant, ligado=True).exists(), False)

    if falhas:
        print('\ncheck_whatsapp_twilio: FALHAS')
        for f in falhas:
            print('  -', f)
        raise SystemExit(1)
    print('\ncheck_whatsapp_twilio: tudo certo (contra a Twilio simulada).')
finally:
    entregas = Delivery.objects.filter(contact__patient_id__in=criados['p'])
    DeliveryAttempt.objects.filter(delivery__in=entregas).delete()
    DocumentAccessToken.objects.filter(document_id__in=criados['doc']).delete()
    entregas.delete()
    MedicalDocument.objects.filter(id__in=criados['doc']).delete()
    Appointment.objects.filter(id__in=criados['a']).delete()
    PatientContact.objects.filter(patient_id__in=criados['p']).delete()
    Patient.objects.filter(id__in=criados['p']).delete()
    WhatsAppModelo.objects.filter(tenant__in=[tenant, tenant_b]).delete()
    WhatsAppTwilio.objects.filter(tenant__in=[tenant, tenant_b]).delete()
    config_inst.whatsapp_twilio_liberado = liberado_antes
    config_inst.save(update_fields=['whatsapp_twilio_liberado'])
