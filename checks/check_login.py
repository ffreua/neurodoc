"""As duas portas de entrada que devolviam tela crua.

Os dois defeitos foram encontrados em producao, no primeiro dia de uso, e
os dois tinham o mesmo formato: a pessoa faz tudo certo, o sistema recusa,
e a tela nao diz o que houve nem o que fazer.

**1. Quem se cadastrou e ainda nao confirmou o e-mail levava 404.** O
`TenantMiddleware` so oferecia a saida (mandar escolher a organizacao) a
quem ja tinha `email_verified_at` -- quem mais precisava de orientacao era
quem nao a recebia. O sintoma engana: a senha funciona, o login responde
302, e a primeira tela depois de entrar e um "Not Found". Quem recebeu
isso concluiu que a conta nao tinha sido criada e tentou se cadastrar de
novo, agora com o e-mail em uso.

**2. Sair e entrar de novo na mesma aba dava 403 cru.** `auth_login` chama
`rotate_token` e troca o cookie CSRF; o formulario que ficou na aba carrega
o token de antes. Abrir outra aba "resolve", e e por isso que o defeito
chega relatado como "em aba nova funciona" -- frase que manda quem
investiga procurar sessao, replica ou cache, e nao token.
"""
from django.conf import settings as dj_settings
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com as configuracoes de producao,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo e o roteiro passaria a medir
# o redirecionamento em vez do que veio a conferir -- com todas as
# assercoes falhando por 301, que parece defeito no codigo testado.
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from tenancy.models import Membership

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:56} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


usuario = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.filter(user=usuario).first()
verificado_antes = usuario.email_verified_at

try:
    print('\n1. E-mail nao confirmado: tela que explica, nao 404')
    usuario.email_verified_at = None
    usuario.save(update_fields=['email_verified_at'])
    c = Client()
    c.force_login(usuario)
    s = c.session
    s['tenant_id'] = str(vinculo.tenant_id)
    s.save()
    r = c.get('/app/')
    conferir('GET /app/ sem e-mail confirmado', r.status_code, 403)
    corpo = r.content.decode('utf-8', 'replace')
    conferir('a tela fala em confirmar o e-mail', 'confirmar' in corpo.lower(), True)
    conferir('oferece reenviar a confirmacao', 'verify-email/resend' in corpo, True)
    conferir('oferece sair', 'logout' in corpo, True)
    conferir('nao e a pagina de "Not Found"', 'Not Found' in corpo, False)

    print('\n2. Com o e-mail confirmado, o caminho volta ao normal')
    usuario.email_verified_at = timezone.now()
    usuario.save(update_fields=['email_verified_at'])
    r = c.get('/app/')
    conferir('GET /app/ deixa de ser 403', r.status_code != 403, True)

    print('\n3. Sem organizacao escolhida, manda escolher (e nao 404)')
    c2 = Client()
    c2.force_login(usuario)
    r = c2.get('/app/')
    conferir('GET /app/ sem tenant na sessao', r.status_code, 302)
    conferir('leva ao seletor de organizacao', 'select-organization' in r['Location'], True)

    print('\n4. Token CSRF velho: tela que explica, nao 403 cru')
    cc = Client(enforce_csrf_checks=True)
    r = cc.post('/accounts/login/', {
        'username': 'doctor-a@demo.neurodoc.local',
        'password': 'senha-errada-de-proposito',
        'csrfmiddlewaretoken': 'token-que-nao-confere',
    })
    conferir('POST com token invalido', r.status_code, 403)
    corpo = r.content.decode('utf-8', 'replace')
    conferir('nao e a pagina crua do Django', 'CSRF verification failed' in corpo, False)
    conferir('a tela explica que a aba ficou para tras', 'aba' in corpo.lower(), True)
    conferir('oferece um caminho de volta', 'href=' in corpo, True)
    # A palavra "CSRF" nao vai para a tela: quem le nao tem o que fazer com
    # ela, e um termo tecnico numa pagina de erro produz o chamado de
    # suporte que a pagina deveria evitar.
    conferir('nao mostra a sigla tecnica', 'CSRF' in corpo, False)

finally:
    usuario.email_verified_at = verificado_antes
    usuario.save(update_fields=['email_verified_at'])
    print('\n  estado de verificacao do usuario restaurado')

if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('\nOK: quem nao confirmou o e-mail recebe instrucao em vez de 404,')
print('    e o token vencido numa aba aberta explica em vez de recusar em branco.')
