"""Minha conta abre e salva no overlay sem abandonar o aplicativo.

O fallback de pagina inteira continua obrigatorio: a rota tambem atende quem
ainda nao escolheu clinica e quem nao tem vinculo. Este roteiro cobra o outro
caminho, usado pelo menu do shell, e falha se o formulario voltar a navegar
para o layout isolado.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from tenancy.models import Membership, MembershipStatus

URL = '/accounts/minha-conta/'
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
falhas = []


def conferir(rotulo, condicao):
    print(f'  {"ok " if condicao else "FALHA"}  {rotulo}')
    if not condicao:
        falhas.append(rotulo)


#: Pagina que hospeda o teste do shell. **Precisa abrir para todo papel** --
#: "minha conta" e de todo mundo. Era `/app/reporting/`, que a secretaria nao
#: abre: o roteiro pegava `Membership...first()` sem dizer qual, e dependia
#: da ordem em que os vinculos sairam do banco. Num banco antigo calhava de
#: vir um dono e passava; na primeira instalacao limpa veio a secretaria, o
#: painel respondeu 302 e as quatro asercoes da secao 1 reprovaram juntas --
#: parecendo defeito do overlay, que estava intacto.
PAGINA_DO_SHELL = '/app/scheduling/'

ATIVOS = list(
    Membership.objects.filter(status=MembershipStatus.ACTIVE)
    .select_related('user', 'tenant')
    .order_by('user__email', 'tenant__slug')
)
vinculo = ATIVOS[0]
usuario = vinculo.user
antes = (usuario.first_name, usuario.last_name)

cliente = Client()
cliente.force_login(usuario)
sessao = cliente.session
sessao['tenant_id'] = str(vinculo.tenant_id)
sessao.save()

try:
    print('\n1. O menu abre um modal, mas conserva o link como fallback')
    # Em **todos** os papeis, e nao num so: o overlay fica no shell, que e o
    # mesmo para quem entra. Varrer os quatro papeis custa quatro requisicoes
    # e tira do roteiro a dependencia de qual vinculo o banco devolve
    # primeiro -- que foi exatamente o que o derrubou.
    for _v in ATIVOS:
        _c = Client()
        _c.force_login(_v.user)
        _s = _c.session
        _s['tenant_id'] = str(_v.tenant_id)
        _s.save()
        _r = _c.get(PAGINA_DO_SHELL)
        _corpo = _r.content.decode('utf-8', 'replace')
        _quem = '/'.join(_v.roles)
        conferir(f'[{_quem}] pagina do shell abriu', _r.status_code == 200)
        conferir(f'[{_quem}] gatilho assinalado para o overlay',
                 'data-nd-account-open' in _corpo)
        conferir(f'[{_quem}] href continua apontando para o fallback',
                 f'href="{URL}"' in _corpo)
        conferir(f'[{_quem}] modal global existe fora da pagina de conta',
                 'id="nd-account-modal"' in _corpo)

    print('\n2. A mesma rota entrega apenas o painel ao JavaScript')
    resposta = cliente.get(URL, **AJAX)
    corpo = resposta.content.decode('utf-8', 'replace')
    conferir('fragmento respondeu 200', resposta.status_code == 200)
    conferir('fragmento contem o formulario', 'data-nd-account-form' in corpo)
    conferir('fragmento nao trouxe outra pagina HTML', '<html' not in corpo.lower())

    print('\n3. Erro de validacao permanece dentro do modal')
    resposta = cliente.post(URL, {'first_name': '   ', 'last_name': ''}, **AJAX)
    corpo = resposta.content.decode('utf-8', 'replace')
    usuario.refresh_from_db()
    conferir('POST invalido respondeu 400', resposta.status_code == 400)
    conferir('resposta ainda e o painel do modal', 'data-nd-account-form' in corpo)
    conferir('nome anterior ficou intacto', (usuario.first_name, usuario.last_name) == antes)

    print('\n4. Salvamento assíncrono devolve o novo nome sem redirecionar')
    resposta = cliente.post(
        URL, {'first_name': 'NomeOverlay', 'last_name': 'Roteiro'}, **AJAX,
    )
    corpo = resposta.content.decode('utf-8', 'replace')
    usuario.refresh_from_db()
    conferir('POST valido respondeu 200, nao 302', resposta.status_code == 200)
    conferir('nome foi gravado', usuario.get_full_name() == 'NomeOverlay Roteiro')
    conferir('fragmento informa o nome para atualizar o cabecalho',
             'data-nd-account-saved-name="NomeOverlay Roteiro"' in corpo)

    print('\n5. Sem cabecalho AJAX, a pagina autonoma continua existindo')
    resposta = cliente.get(URL)
    corpo = resposta.content.decode('utf-8', 'replace')
    conferir('fallback respondeu 200', resposta.status_code == 200)
    conferir('fallback e documento HTML completo', '<html' in corpo.lower())
finally:
    usuario.first_name, usuario.last_name = antes
    usuario.save(update_fields=['first_name', 'last_name'])

if falhas:
    for falha in falhas:
        print('FALHA:', falha)
    raise SystemExit(1)

print('\nOK: Minha conta abre e salva no overlay, com fallback autonomo preservado.')
