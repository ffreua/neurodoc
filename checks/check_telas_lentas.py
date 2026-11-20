"""Registro das telas lentas (2026-11-20, `base/lentidao.py`).

O que este roteiro tenta quebrar:

1. resposta rápida não grava nada; lenta grava o nome da rota, o método, o
   status, o tempo e as consultas — e **nunca** o endereço nem a busca;
2. stream (SSE) não entra, e limite 0 desliga;
3. falha ao gravar não derruba a resposta;
4. uma tela de verdade, pelo cliente de teste, entra com a rota e as
   consultas contadas;
5. a limpeza apaga só o que passou de 30 dias, e o resumo agrega por rota;
6. o console: anônimo, não superusuário e superusuário sem o código em 404;
   com o código, a página lista a rota;
7. o middleware está depois dos estáticos.

Tudo numa transação desfeita no fim.
"""
import uuid
from datetime import timedelta
from unittest import mock

from django.conf import settings as dj_settings
from django.db import transaction
from django.http import HttpResponse, StreamingHttpResponse
from django.test import Client, RequestFactory, override_settings
from django.urls import resolve, reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from base import lentidao
from base.models import TelaLenta

falhas = []


def conferir(rotulo, condicao, detalhe=''):
    print(f'  {"ok   " if condicao else "FALHA"} {rotulo}' + (f'  [{detalhe}]' if not condicao and detalhe else ''))
    if not condicao:
        falhas.append(rotulo)


class Desfazer(Exception):
    pass


def pedido(caminho):
    req = RequestFactory().get(caminho)
    req.resolver_match = resolve(caminho.split('?')[0])
    return req


def lenta(ms, resposta=None):
    """Um `get_response` que "leva" `ms` milissegundos, sem esperar de verdade."""
    relogio = iter([0.0, ms / 1000])

    def get_response(request):
        return resposta or HttpResponse('ok')

    return get_response, mock.patch.object(lentidao.time, 'perf_counter', lambda: next(relogio))


try:
    with transaction.atomic():
        TelaLenta.objects.all().delete()
        caminho = reverse('patients:list') + '?q=MARIA+DA+SILVA'

        print('1. Rápida não grava; lenta grava a rota e nada que identifique')
        with override_settings(TELAS_LENTAS_MS=500):
            get_response, relogio = lenta(120)
            with relogio:
                lentidao.TelasLentasMiddleware(get_response)(pedido(caminho))
            conferir('resposta de 120 ms não grava', TelaLenta.objects.count() == 0)
            get_response, relogio = lenta(900)
            with relogio:
                lentidao.TelasLentasMiddleware(get_response)(pedido(caminho))
        registro = TelaLenta.objects.first()
        conferir('resposta de 900 ms grava', registro is not None)
        if registro:
            conferir('com o nome da rota', registro.rota == 'patients:list', registro.rota)
            conferir('método, status e tempo', (registro.metodo, registro.status, registro.milissegundos)
                     == ('GET', 200, 900), (registro.metodo, registro.status, registro.milissegundos))
            texto = ' '.join(str(getattr(registro, f.name)) for f in TelaLenta._meta.fields)
            conferir('sem o endereço nem a busca', 'MARIA' not in texto and '/app/' not in texto, texto)

        print('\n2. Stream não entra; limite 0 desliga')
        TelaLenta.objects.all().delete()
        with override_settings(TELAS_LENTAS_MS=500):
            get_response, relogio = lenta(5000, StreamingHttpResponse(iter(['x'])))
            with relogio:
                lentidao.TelasLentasMiddleware(get_response)(pedido(caminho))
        conferir('stream de 5 s não grava', TelaLenta.objects.count() == 0)
        with override_settings(TELAS_LENTAS_MS=0):
            get_response, relogio = lenta(5000)
            with mock.patch.object(lentidao.time, 'perf_counter', side_effect=AssertionError('mediu')):
                lentidao.TelasLentasMiddleware(get_response)(pedido(caminho))
        conferir('limite 0 nem mede', TelaLenta.objects.count() == 0)

        print('\n3. Falha ao gravar não derruba a resposta')
        with override_settings(TELAS_LENTAS_MS=500):
            get_response, relogio = lenta(900)
            with relogio, mock.patch.object(TelaLenta.objects, 'create', side_effect=RuntimeError('banco')):
                resposta = lentidao.TelasLentasMiddleware(get_response)(pedido(caminho))
        conferir('a resposta sai mesmo assim', resposta.status_code == 200)

        print('\n4. Uma tela de verdade, pelo cliente de teste')
        sufixo = uuid.uuid4().hex[:8]
        superu = User.objects.create_user(email=f'lentas-{sufixo}@example.com', password='SenhaLonga!2026xx',
                                          is_staff=True, is_superuser=True)
        User.objects.filter(id=superu.id).update(email_verified_at=timezone.now())
        dispositivo = TOTPDevice.objects.create(user=superu, name='roteiro', confirmed=True)
        cliente = Client(HTTP_HOST='localhost')
        cliente.force_login(superu)
        TelaLenta.objects.all().delete()
        with override_settings(TELAS_LENTAS_MS=1):
            cliente.get(reverse('accounts:login'))
        real = TelaLenta.objects.filter(rota='accounts:login').first()
        conferir('a tela de login entra com a rota', real is not None,
                 list(TelaLenta.objects.values_list('rota', flat=True)))

        print('\n5. Limpeza e resumo')
        TelaLenta.objects.all().delete()
        for ms in (600, 700, 800, 900, 4000):
            TelaLenta.objects.create(rota='reporting:dashboard', metodo='GET', status=200, milissegundos=ms, consultas=30)
        antiga = TelaLenta.objects.create(rota='reporting:painel', metodo='GET', status=200, milissegundos=700, consultas=40)
        TelaLenta.objects.filter(id=antiga.id).update(criada_em=timezone.now() - timedelta(days=31))
        linhas = {linha['rota']: linha for linha in lentidao.resumo(30)}
        d = linhas.get('reporting:dashboard', {})
        conferir('resumo agrega por rota', d.get('ocorrencias') == 5 and d.get('mediana') == 800
                 and d.get('maximo') == 4000 and d.get('consultas') == 30, d)
        conferir('o de 31 dias fica fora do resumo de 30', 'reporting:painel' not in linhas)
        apagados = lentidao.apagar_antigas()
        conferir('a limpeza apaga só o antigo', apagados == 1 and TelaLenta.objects.count() == 5,
                 (apagados, TelaLenta.objects.count()))

        print('\n6. O console')
        url = reverse('superadmin:telas-lentas')
        conferir('anônimo em 404', Client(HTTP_HOST='localhost').get(url).status_code in (302, 404))
        comum = User.objects.create_user(email=f'comum-{sufixo}@example.com', password='SenhaLonga!2026xx')
        c2 = Client(HTTP_HOST='localhost')
        c2.force_login(comum)
        conferir('não superusuário em 404', c2.get(url).status_code == 404)
        conferir('superusuário sem o código em 404', cliente.get(url).status_code == 404)
        sessao = cliente.session
        sessao[DEVICE_ID_SESSION_KEY] = dispositivo.persistent_id
        sessao.save()
        resposta = cliente.get(url + '?dias=30')
        conferir('com o código abre e lista a rota', resposta.status_code == 200
                 and b'reporting:dashboard' in resposta.content, resposta.status_code)
        conferir('período fora da lista cai em 7 dias', cliente.get(url + '?dias=abc').status_code == 200)

        print('\n7. O middleware fica depois dos estáticos')
        mw = list(dj_settings.MIDDLEWARE)
        conferir('depois de ReleaseStaticMiddleware e antes da sessão',
                 mw.index('ops.staticfiles.ReleaseStaticMiddleware') < mw.index('base.lentidao.TelasLentasMiddleware')
                 < mw.index('django.contrib.sessions.middleware.SessionMiddleware'))

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'{len(falhas)} FALHA(S):')
    for f_ in falhas:
        print('  -', f_)
    raise SystemExit(1)
print('Tudo certo.')
