"""A lista de pedidos do painel do SNCR é curta, e não esconde o que pede ação.

Pedido de 2026-11-22: o cartão "Pedidos" crescia um item por tentativa de
login no Gov.br e empurrava o resto da tela. O roteiro tenta quebrar:

1. o painel mostra no máximo `PEDIDOS_NO_PAINEL` pedidos comuns, os mais
   recentes, e aponta o histórico quando há mais;
2. o pedido **incerto** aparece sempre — mesmo o mais antigo de todos —,
   com os botões de conferir, porque enquanto ele existir o pedido novo
   daquele tipo fica barrado;
3. o histórico pagina todos os pedidos, do mais recente, com os botões do
   incerto, e página inválida não vira erro 500;
4. sem pedido nenhum, nem o link do histórico nem erro;
5. o pedido de outro médico não aparece, e quem não emite documento não abre.

Tudo dentro de uma transação desfeita.
"""
import datetime

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.test import Client
from django.utils import timezone

from accounts.models import PhysicianProfile, User
from sncr import views as sncr_views
from sncr.models import EstadoPedido, PedidoNumeracao
from tenancy.models import Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe and not ok else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
user = User.objects.get(email='doctor-a@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
medico = PhysicianProfile.objects.get(user=user)


def cliente(u=user):
    c = Client()
    c.force_login(u)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def pedido(tipo, estado, dias_atras, mensagem='', quem=None):
    p = PedidoNumeracao.objects.create(
        medico=quem or medico, solicitado_por=user, tenant=tenant, tipo=tipo, ambiente='homologacao',
        uf='SP', documento='123456', estado=estado, mensagem=mensagem,
    )
    PedidoNumeracao.objects.filter(id=p.id).update(created_at=timezone.now() - datetime.timedelta(days=dias_atras))
    return p


try:
    with transaction.atomic():
        PedidoNumeracao.objects.filter(medico=medico).delete()

        print('=== 4. sem pedido nenhum ===')
        r = cliente().get('/app/sncr/')
        html = r.content.decode()
        conferir('o painel abre', r.status_code == 200, str(r.status_code))
        conferir('diz que não há pedido e não mostra o link do histórico',
                 'Nenhum pedido ainda.' in html and '/app/sncr/historico/' not in html)

        print('=== 1 e 2. o painel: curto, e com o incerto ===')
        teto = sncr_views.PEDIDOS_NO_PAINEL
        incerto_antigo = pedido('RCE', EstadoPedido.INCERTO, 400, mensagem='MARCA-INCERTO-ANTIGO')
        comuns = [pedido('RET', EstadoPedido.EXPIRADO, i + 1, mensagem=f'MARCA-COMUM-{i:02d}') for i in range(teto + 9)]
        outro_medico = PhysicianProfile.objects.exclude(id=medico.id).first()
        if outro_medico:
            pedido('RCE', EstadoPedido.CONCLUIDO, 0, mensagem='MARCA-DE-OUTRO-MEDICO', quem=outro_medico)

        r = cliente().get('/app/sncr/')
        html = r.content.decode()
        mostrados = [i for i in range(teto + 9) if f'MARCA-COMUM-{i:02d}' in html]
        conferir(f'no máximo {teto} pedidos comuns no painel', len(mostrados) == teto, str(len(mostrados)))
        conferir('são os mais recentes', mostrados == list(range(teto)), str(mostrados))
        conferir('o incerto de 400 dias atrás aparece mesmo assim', 'MARCA-INCERTO-ANTIGO' in html)
        conferir('com os botões de conferir no portal', 'data-nd-sncr-conferir' in html
                 and f'/app/sncr/pedido/{incerto_antigo.id}/conferir/' in html)
        conferir('o link do histórico aparece, com o total',
                 '/app/sncr/historico/' in html and f'({teto + 10} pedidos)' in html)
        conferir('o pedido de outro médico não aparece', 'MARCA-DE-OUTRO-MEDICO' not in html)

        print('=== 3. o histórico ===')
        r = cliente().get('/app/sncr/historico/')
        html = r.content.decode()
        conferir('o histórico abre', r.status_code == 200, str(r.status_code))
        conferir('mostra todos (cabem numa página)', all(f'MARCA-COMUM-{i:02d}' in html for i in range(teto + 9))
                 and 'MARCA-INCERTO-ANTIGO' in html)
        conferir('do mais recente ao mais antigo',
                 html.index('MARCA-COMUM-00') < html.index('MARCA-COMUM-05') < html.index('MARCA-INCERTO-ANTIGO'))
        conferir('o incerto tem os botões no histórico também', 'data-nd-sncr-conferir' in html)
        conferir('sem o de outro médico', 'MARCA-DE-OUTRO-MEDICO' not in html)

        por_pagina = sncr_views.PEDIDOS_POR_PAGINA
        for i in range(por_pagina):
            pedido('RET', EstadoPedido.EXPIRADO, 500 + i, mensagem=f'MARCA-VELHO-{i:02d}')
        r = cliente().get('/app/sncr/historico/')
        html = r.content.decode()
        conferir('com mais de uma página, pagina', '?page=2' in html and 'MARCA-VELHO-24' not in html)
        r2 = cliente().get('/app/sncr/historico/?page=2')
        conferir('a página 2 traz os mais antigos', r2.status_code == 200 and 'MARCA-VELHO-24' in r2.content.decode())
        for ruim in ('999', 'abc', '-1', '0'):
            conferir(f'página "{ruim}" não vira erro', cliente().get(f'/app/sncr/historico/?page={ruim}').status_code == 200)

        print('=== 5. quem não emite documento ===')
        conferir('a secretária não abre o histórico',
                 cliente(secretaria).get('/app/sncr/historico/').status_code in (403, 404))

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'{len(falhas)} FALHA(S):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('check_sncr_lista_de_pedidos: tudo certo.')
