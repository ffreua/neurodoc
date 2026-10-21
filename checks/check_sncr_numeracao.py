"""Numeração do SNCR: o pedido de bloco, os desfechos e os números sem repetir.

Sprint 1 da integração (`docs/sncr/`). A Anvisa é **simulada** aqui
(`httpx.MockTransport`), resposta por resposta: o teste real é o primeiro
pedido em produção, depois do CNPJ (decisão D8). Tenta quebrar. As
perguntas são:

- desligada, sem CNPJ ou com CRM não validado, nada começa?
- a secretária não abre o painel?
- o pedido manda ao SNCR o `Origin`, o token como `Bearer` e o corpo do
  manual (conselho, tipo, documento só com dígitos, UF, CNPJ)?
- o bloco recebido vira 1.000 números, como texto, com os zeros à esquerda?
- o retorno do Gov.br vale **uma vez**, e só no navegador que pediu?
- cada desfecho vai para o estado certo: 401 do login → não enviado;
  404/429 → recusado; 500/503, tempo esgotado depois de enviar e resposta
  quebrada → **incerto**; falha ao conectar → não enviado?
- o incerto barra pedido novo; o limite de 3 por mês barra; saldo livre
  barra; login de mais de 5 minutos expira sem falar com a Anvisa; pedido
  parado em "enviando" vira incerto?
- bloco que não forma faixa, ou que repete números, fica não utilizável?
- duas reservas ao mesmo tempo nunca levam o mesmo número; reservar de
  novo para o mesmo documento devolve o mesmo; usado não vira perdido?
- o bloco é do médico: o mesmo saldo na outra clínica dele, e nada na
  tela de outro médico?
- o token não vai para a trilha?
"""
import json
import threading
from datetime import timedelta
from unittest import mock

import httpx
from django.conf import settings as dj_settings
from django.db import connection
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import PhysicianProfile, User
from audit.models import AuditEvent
from documents import issuance
from documents.models import Attachment, MedicalDocument, MedicalDocumentKind
from patients.models import Patient
from sncr import cliente as api
from sncr import fluxo, numeracao
from sncr.models import (
    BlocoNumeracao, Configuracao, EstadoNumero, EstadoPedido, NumeroSncr, PedidoNumeracao,
)
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
user = User.objects.get(email='doctor-a@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
medico = PhysicianProfile.objects.get(user=user)
original_medico = (medico.verification_status, medico.crm_number, medico.crm_state)
config = Configuracao.carregar()
original_config = (config.ativo, config.ambiente, config.cnpj_mantenedora)
CNPJ = '11222333000181'

medico.verification_status = medico.VerificationStatus.VERIFIED
medico.crm_number, medico.crm_state = '123.456', 'SP'
medico.save(update_fields=['verification_status', 'crm_number', 'crm_state'])


def limpar():
    NumeroSncr.objects.filter(medico=medico).delete()
    BlocoNumeracao.objects.filter(medico=medico).delete()
    PedidoNumeracao.objects.filter(medico=medico).delete()


def limpar_ret():
    NumeroSncr.objects.filter(medico=medico, tipo='RET').delete()
    BlocoNumeracao.objects.filter(medico=medico, tipo='RET').delete()
    PedidoNumeracao.objects.filter(medico=medico, tipo='RET').delete()


def entrar(u=user, tenant=tenant_a):
    c = Client()
    c.force_login(u)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


chamadas = []


def anvisa(token_status=200, post=None):
    """Um SNCR falso. `post` é (status, corpo) ou uma exceção do httpx."""
    def handler(req):
        chamadas.append(req)
        if req.url.path.endswith('/auth/token'):
            if token_status != 200:
                return httpx.Response(token_status, json={'error': 'Sessão inválida ou expirada'})
            return httpx.Response(200, json={'access_token': 'TOKEN-SECRETO-XYZ', 'token_type': 'Bearer'})
        if isinstance(post, Exception):
            raise post
        status, corpo = post or (200, {'inicio': '0000001000', 'fim': '0000001999', 'quantidade': 1000})
        if isinstance(corpo, str):
            return httpx.Response(status, text=corpo)
        return httpx.Response(status, json=corpo)
    return handler


def com_anvisa(handler):
    return mock.patch.object(
        fluxo, 'criar_cliente',
        lambda cfg: api.Cliente(cfg.base_url, fluxo._origem(), transport=httpx.MockTransport(handler)),
    )


def pedir(tipo, handler, session_id='sess-1'):
    """Clique em pedir e retorno do Gov.br. Devolve o pedido mais recente."""
    c = entrar()
    with com_anvisa(handler):
        r = c.post(f'/app/sncr/pedir/{tipo}/')
        if r.status_code == 302 and 'auth/login' in r['Location']:
            c.get('/app/sncr/retorno/', {'session_id': session_id})
    return PedidoNumeracao.objects.filter(medico=medico, tipo=tipo).order_by('-created_at').first(), r, c


try:
    limpar()
    print('=== 1. o que impede começar ===')
    config.ativo, config.cnpj_mantenedora = False, ''
    config.save()
    motivos = fluxo.conferir(config, medico, 'RCE')
    conferir('desligada: impedimento', any('desligada' in m for m in motivos))
    conferir('sem CNPJ: impedimento', any('CNPJ' in m for m in motivos))
    p, r, _c = pedir('RCE', anvisa())
    conferir('desligada: o POST não cria pedido nem sai para o Gov.br', p is None and r.status_code == 302
             and 'auth/login' not in r['Location'])
    config.ativo, config.cnpj_mantenedora, config.ambiente = True, CNPJ, 'homologacao'
    config.save()
    medico.verification_status = medico.VerificationStatus.PENDING
    medico.save(update_fields=['verification_status'])
    conferir('CRM não validado: impedimento',
             any('CRM' in m for m in fluxo.conferir(config, medico, 'RCE')))
    medico.verification_status = medico.VerificationStatus.VERIFIED
    medico.save(update_fields=['verification_status'])
    conferir('tudo certo: nenhum impedimento', fluxo.conferir(config, medico, 'RCE') == [],
             fluxo.conferir(config, medico, 'RCE'))
    conferir('a secretária não abre o painel', entrar(secretaria).get('/app/sncr/').status_code == 404)
    conferir('o médico abre o painel', entrar().get('/app/sncr/').status_code == 200)

    print('=== 2. o pedido que dá certo ===')
    chamadas.clear()
    p, r, c = pedir('RCE', anvisa())
    destino = r['Location']
    conferir('vai ao login do SNCR de homologação',
             destino.startswith('https://api-gateway.hmg.apps.anvisa.gov.br/api-sncr/api/v1/auth/login'))
    conferir('com o retorno em /app/sncr/retorno/', 'app%2Fsncr%2Fretorno' in destino, destino[-80:])
    conferir('pedido concluído', p.estado == EstadoPedido.CONCLUIDO, (p.estado, p.mensagem))
    token_req = next((x for x in chamadas if x.url.path.endswith('/auth/token')), None)
    post_req = next((x for x in chamadas if x.method == 'POST'), None)
    conferir('a troca manda o session_id e o Origin',
             token_req is not None and token_req.url.params.get('session_id') == 'sess-1'
             and token_req.headers.get('origin') == fluxo._origem())
    corpo = json.loads(post_req.content) if post_req else {}
    conferir('o pedido leva o token como Bearer',
             post_req is not None and post_req.headers.get('authorization') == 'Bearer TOKEN-SECRETO-XYZ')
    conferir('o corpo é o do manual, com o CRM só em dígitos',
             corpo == {'conselho': 'CRM', 'tipo': 'RCE', 'documento': '123456', 'uf': 'SP', 'cnpj': CNPJ}, corpo)
    conferir('sem o cabeçalho X-Jws-Integradora (L1)', post_req is not None and 'x-jws-integradora' not in post_req.headers)
    nums = list(NumeroSncr.objects.filter(medico=medico, tipo='RCE').order_by('ordem').values_list('numero', flat=True))
    conferir('1.000 números', len(nums) == 1000, len(nums))
    conferir('como texto, com os zeros à esquerda', nums[:1] == ['0000001000'] and nums[-1:] == ['0000001999'])
    conferir('saldo 1.000', numeracao.saldo(medico, 'RCE', 'homologacao') == 1000)

    print('=== 3. o retorno vale uma vez ===')
    chamadas.clear()
    with com_anvisa(anvisa()):
        c.get('/app/sncr/retorno/', {'session_id': 'sess-1'})
    conferir('o mesmo retorno de novo não fala com a Anvisa', chamadas == [])
    conferir('saldo livre impede pedir outro bloco',
             any('livres' in m for m in fluxo.conferir(config, medico, 'RCE')))
    chamadas.clear()
    with com_anvisa(anvisa()):
        entrar().get('/app/sncr/retorno/', {'session_id': 'de-outra-pessoa'})
    conferir('retorno sem pedido neste navegador é recusado sem falar com a Anvisa', chamadas == [])

    print('=== 4. reservar sem repetir ===')
    paciente = Patient.objects.filter(tenant=tenant_a).first()
    vinculo = Membership.objects.get(tenant=tenant_a, user=user)
    docs = [issuance.create_draft(tenant_a, paciente, None, vinculo, user.id, MedicalDocumentKind.PRESCRIPTION,
                                  {'prescription_text': 'Teste SNCR', 'prescription_format': 'simple'})
            for _ in range(2)]
    resultado, barreira = {}, threading.Barrier(2)

    def reservar(i):
        barreira.wait()
        try:
            resultado[i] = numeracao.reservar(medico, 'RCE', 'homologacao', docs[i], tenant_a.id).numero
        except numeracao.SemNumeroLivre:
            resultado[i] = None
        finally:
            connection.close()

    linhas = [threading.Thread(target=reservar, args=(i,)) for i in range(2)]
    [t.start() for t in linhas]
    [t.join() for t in linhas]
    conferir('duas reservas ao mesmo tempo: números diferentes',
             len(resultado) == 2 and None not in resultado.values() and resultado[0] != resultado[1], resultado)
    if None in resultado.values():
        raise SystemExit('FALHA: a reserva simultânea não achou número livre; o resto do roteiro depende dela')
    de_novo = numeracao.reservar(medico, 'RCE', 'homologacao', docs[0], tenant_a.id).numero
    conferir('reservar de novo para o mesmo documento devolve o mesmo', de_novo == resultado.get(0))
    usado = numeracao.consumir(NumeroSncr.objects.get(numero=resultado[0], ambiente='homologacao', tipo='RCE'))
    try:
        numeracao.marcar_perdido(usado, 'teste')
        conferir('usado não vira perdido', False)
    except ValueError:
        conferir('usado não vira perdido', True)
    perdido = numeracao.marcar_perdido(NumeroSncr.objects.get(numero=resultado[1], ambiente='homologacao', tipo='RCE'), 'teste')
    conferir('perdido não volta a livre', perdido.estado == EstadoNumero.PERDIDO)
    conferir('saldo desconta os dois', numeracao.saldo(medico, 'RCE', 'homologacao') == 998)

    print('=== 5. o bloco é do médico ===')
    html_b = entrar(tenant=tenant_b).get('/app/sncr/').content.decode() if Membership.objects.filter(
        tenant=tenant_b, user=user, status='active').exists() else None
    if html_b is not None:
        conferir('na outra clínica dele, o mesmo saldo', 'data-nd-sncr-tipo="RCE"' in html_b and '>998<' in html_b)
    else:
        print('  (a médica de demonstração não está na clínica B — seção pulada)')
    outro = PhysicianProfile.objects.exclude(pk=medico.pk).first()
    if outro is not None:
        conferir('outro médico não vê estes números', numeracao.saldo(outro, 'RCE', 'homologacao') == 0)

    print('=== 6. os desfechos (RET) ===')
    casos = [
        ('login expirado (401 na troca)', anvisa(token_status=401), EstadoPedido.FALHOU, False),
        ('CRM diferente do CPF (404)', anvisa(post=(404, {'mensagem': 'Inscrição fornecida é diferente da inscrição do usuário'})), EstadoPedido.RECUSADO, True),
        ('limite da Anvisa (429)', anvisa(post=(429, {'mensagem': 'Limite excedido'})), EstadoPedido.RECUSADO, True),
        ('falha ao conectar', anvisa(post=httpx.ConnectError('recusada')), EstadoPedido.FALHOU, True),
        ('erro 500 depois de receber', anvisa(post=(500, {'mensagem': 'erro'})), EstadoPedido.INCERTO, True),
        ('503 depois de receber', anvisa(post=(503, 'indisponivel')), EstadoPedido.INCERTO, True),
        ('tempo esgotado depois de enviar', anvisa(post=httpx.ReadTimeout('sem resposta')), EstadoPedido.INCERTO, True),
        ('200 sem início e fim', anvisa(post=(200, {'mensagem': 'ok'})), EstadoPedido.INCERTO, True),
    ]
    for rotulo, handler, esperado, deve_postar in casos:
        PedidoNumeracao.objects.filter(medico=medico, tipo='RET').delete()
        chamadas.clear()
        p, _r, _c = pedir('RET', handler)
        postou = any(x.method == 'POST' for x in chamadas)
        conferir(f'{rotulo} → {esperado}', p is not None and p.estado == esperado and postou == deve_postar,
                 (p.estado if p else None, postou))
    conferir('nenhum número de RET nasceu desses desfechos', not NumeroSncr.objects.filter(medico=medico, tipo='RET').exists())
    conferir('o incerto barra pedido novo', any('incerto' in m for m in fluxo.conferir(config, medico, 'RET')))
    chamadas.clear()
    p_antes = PedidoNumeracao.objects.filter(medico=medico, tipo='RET').count()
    pedir('RET', anvisa())
    conferir('com incerto pendente, o clique não pede nada',
             chamadas == [] and PedidoNumeracao.objects.filter(medico=medico, tipo='RET').count() == p_antes)

    print('=== 7. bloco que não se usa ===')
    PedidoNumeracao.objects.filter(medico=medico, tipo='RET').delete()
    p, _r, _c = pedir('RET', anvisa(post=(200, {'inicio': 'A1', 'fim': 'B9', 'quantidade': 2})))
    conferir('faixa irreconhecível: concluído, mas não utilizável',
             p.estado == EstadoPedido.CONCLUIDO and not p.bloco.utilizavel and p.bloco.numeros.count() == 0)
    limpar_ret()
    p1, _r, _c = pedir('RET', anvisa(post=(200, {'inicio': '5000', 'fim': '5999', 'quantidade': 1000})))
    NumeroSncr.objects.filter(medico=medico, tipo='RET').update(estado=EstadoNumero.PERDIDO)
    p2, _r, _c = pedir('RET', anvisa(post=(200, {'inicio': '5000', 'fim': '5999', 'quantidade': 1000})))
    conferir('bloco que repete números fica não utilizável', p2.estado == EstadoPedido.CONCLUIDO
             and not p2.bloco.utilizavel and 'repete' in p2.bloco.motivo_bloqueio)
    conferir('quantidade que não bate não gera números', numeracao.enumerar('100', '199', 50) is None)

    print('=== 8. limite do mês, login expirado, pedido parado ===')
    limpar_ret()
    for _ in range(3):
        PedidoNumeracao.objects.create(
            medico=medico, solicitado_por=user, tenant=tenant_a, tipo='RET', ambiente='homologacao',
            uf='SP', documento='123456', cnpj=CNPJ, estado=EstadoPedido.CONCLUIDO, enviado_em=timezone.now(),
        )
    conferir('3 no mês: impedimento', any('limite' in m for m in fluxo.conferir(config, medico, 'RET')))
    limpar_ret()
    c = entrar()
    with com_anvisa(anvisa()):
        c.post('/app/sncr/pedir/RET/')
    pend = PedidoNumeracao.objects.filter(medico=medico, tipo='RET').latest('created_at')
    PedidoNumeracao.objects.filter(pk=pend.pk).update(created_at=timezone.now() - timedelta(minutes=6))
    chamadas.clear()
    with com_anvisa(anvisa()):
        c.get('/app/sncr/retorno/', {'session_id': 'tarde'})
    pend.refresh_from_db()
    conferir('login de mais de 5 minutos expira sem falar com a Anvisa',
             pend.estado == EstadoPedido.EXPIRADO and chamadas == [], pend.estado)
    parado = PedidoNumeracao.objects.create(
        medico=medico, solicitado_por=user, tenant=tenant_a, tipo='RET', ambiente='homologacao',
        uf='SP', documento='123456', cnpj=CNPJ, estado=EstadoPedido.ENVIANDO,
        enviado_em=timezone.now() - timedelta(minutes=10),
    )
    fluxo.pedidos_parados()
    parado.refresh_from_db()
    conferir('pedido parado em "enviando" vira incerto', parado.estado == EstadoPedido.INCERTO)

    print('=== 9. a trilha ===')
    eventos = AuditEvent.objects.filter(object_type='sncr_pedido', created_at__gte=timezone.now() - timedelta(minutes=10))
    conferir('os pedidos entram na trilha', eventos.filter(action='sncr.pedido_concluido').exists()
             and eventos.filter(action='sncr.pedido_incerto').exists())
    conferir('o token nunca vai para a trilha',
             not any('TOKEN-SECRETO' in json.dumps(e.integrity_metadata or {}) for e in eventos))
    conferir('nem para o pedido', not PedidoNumeracao.objects.filter(medico=medico, mensagem__contains='TOKEN').exists())
finally:
    print('=== limpeza ===')
    limpar()
    for d in MedicalDocument.objects.filter(content_snapshot__prescription_text='Teste SNCR'):
        att = d.pdf_attachment_id
        d.delete()
        if att:
            Attachment.objects.filter(id=att).delete()
    config.ativo, config.ambiente, config.cnpj_mantenedora = original_config
    config.save()
    medico.verification_status, medico.crm_number, medico.crm_state = original_medico
    medico.save(update_fields=['verification_status', 'crm_number', 'crm_state'])
    print('  pedidos, blocos, números e rascunhos do roteiro removidos; configuração restaurada')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: numeração do SNCR — pedido pelo Gov.br com o corpo do manual, desfechos no estado certo,')
print('    incerto sem repetição, nenhum número em duas reservas, bloco do médico e token fora da trilha.')
