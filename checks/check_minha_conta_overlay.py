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


vinculo = Membership.objects.filter(
    status=MembershipStatus.ACTIVE,
).select_related('user', 'tenant').first()
usuario = vinculo.user
antes = (usuario.first_name, usuario.last_name)

cliente = Client()
cliente.force_login(usuario)
sessao = cliente.session
sessao['tenant_id'] = str(vinculo.tenant_id)
sessao.save()

try:
    print('\n1. O menu abre um modal, mas conserva o link como fallback')
    resposta = cliente.get('/app/reporting/')
    corpo = resposta.content.decode('utf-8', 'replace')
    conferir('painel abriu', resposta.status_code == 200)
    conferir('gatilho assinalado para o overlay', 'data-nd-account-open' in corpo)
    conferir('href continua apontando para o fallback', f'href="{URL}"' in corpo)
    conferir('modal global existe fora da pagina de conta', 'id="nd-account-modal"' in corpo)

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
