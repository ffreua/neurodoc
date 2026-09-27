"""Cada um edita o proprio nome, e so o proprio.

`User.first_name`/`last_name` so se preenchiam pelo admin tecnico do
Django, que e de quem opera o servidor. Quem se cadastrava ficava com a
conta sem nome, e as telas que mostram pessoa estampavam o **e-mail** no
lugar. Para o medico, `PhysicianProfile.professional_name` passou a cobrir
o buraco (`3911283`); para a secretaria e para quem administra, nao havia
nada -- e sao justamente os papeis sem perfil profissional.

O que este roteiro cobra, e que e onde da errado:

- a tela abre para **qualquer** vinculo, inclusive para quem nao escolheu
  organizacao e para quem nao tem nenhuma (o superadministrador). Ela vive
  fora de `/app/` exatamente por isso;
- o nome gravado passa a aparecer, vencendo o perfil profissional;
- **nao existe caminho para editar o nome de outra pessoa** -- a rota nao
  tem identificador, e `request.user` e a garantia;
- espaco em branco nao e nome: `'   '` gravado devolveria `get_full_name`
  ao e-mail, com a tela dizendo que salvou;
- o e-mail nao se altera por aqui, nem por POST direto.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from tenancy.models import Membership, MembershipStatus

URL = '/accounts/minha-conta/'
falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


alvo = User.objects.filter(is_active=True).first()
vizinho = User.objects.filter(is_active=True).exclude(pk=alvo.pk).first()
antes = (alvo.first_name, alvo.last_name)
antes_vizinho = (vizinho.first_name, vizinho.last_name) if vizinho else None

try:
    print('\n1. Fechada para quem nao entrou')
    anonimo = Client()
    r = anonimo.get(URL)
    conferir('anonimo e mandado ao login', r.status_code, 302)
    conferir('para o login mesmo', 'login' in r.get('Location', ''), True)

    print('\n2. Abre SEM organizacao escolhida')
    # A razao de a tela viver fora de `/app/`: quem opera o servidor nao
    # tem vinculo em clinica nenhuma, e tambem precisa de nome. Se esta
    # assercao falhar, a tela virou privilegio de quem ja escolheu clinica.
    c = Client()
    c.force_login(alvo)
    r = c.get(URL)
    conferir('sem tenant na sessao, a tela abre', r.status_code, 200)

    print('\n3. Grava o nome, e ele passa a valer')
    r = c.post(URL, {'first_name': 'Nome', 'last_name': 'DoRoteiro'}, follow=True)
    alvo.refresh_from_db()
    conferir('first_name gravado', alvo.first_name, 'Nome')
    conferir('last_name gravado', alvo.last_name, 'DoRoteiro')
    conferir('o nome exibido passa a ser o da conta', alvo.get_full_name(), 'Nome DoRoteiro')

    print('\n4. Espaco em branco nao e nome')
    r = c.post(URL, {'first_name': '   ', 'last_name': ''})
    alvo.refresh_from_db()
    conferir('o formulario recusa', r.status_code, 400)
    conferir('e nao apagou o que ja estava la', alvo.first_name, 'Nome')

    print('\n5. Nao ha como editar o nome de outra pessoa')
    if vizinho is None:
        print('  (so ha um usuario nesta instalacao; secao pulada)')
    else:
        marca = vizinho.first_name
        # Tentar pela rota com identificador -- que nao existe, e e por isso
        # que nao ha verificacao de dono a esquecer.
        r = c.post(f'/accounts/minha-conta/{vizinho.pk}/', {'first_name': 'Invadido'})
        conferir('rota com id nao existe', r.status_code in (404, 301), True)
        # E mandando o id no corpo, caso a view um dia passe a le-lo.
        c.post(URL, {'first_name': 'MeuNome', 'last_name': '', 'user': str(vizinho.pk),
                     'id': str(vizinho.pk), 'pk': str(vizinho.pk)})
        vizinho.refresh_from_db()
        conferir('o id no corpo do POST e ignorado', vizinho.first_name, marca)

    print('\n6. O e-mail nao se altera por aqui')
    email_antes = alvo.email
    c.post(URL, {'first_name': 'Nome', 'last_name': 'DoRoteiro',
                 'email': 'invadido@example.invalid'})
    alvo.refresh_from_db()
    conferir('e-mail intacto', alvo.email, email_antes)

    print('\n7. A tela se alcanca pelo menu')
    vinculo = Membership.objects.filter(
        user=alvo, status=MembershipStatus.ACTIVE,
    ).select_related('tenant').first()
    if vinculo is None:
        print('  (usuario sem vinculo; secao pulada)')
    else:
        sessao = c.session
        sessao['tenant_id'] = str(vinculo.tenant_id)
        sessao.save()
        # `/app/reporting/`, e nao `/app/`: aquele prefixo sozinho nao e
        # rota, e devolve 404 -- a assercao mediria a ausencia da pagina em
        # vez da ausencia do link. O painel e a primeira tela de quem entra,
        # e e onde o menu do topo aparece.
        resposta = c.get('/app/reporting/', follow=True)
        corpo = resposta.content.decode('utf-8', 'replace')
        conferir('a pagina do painel renderiza', resposta.status_code, 200)
        conferir('o menu do topo linka para a tela', URL in corpo, True)

finally:
    alvo.first_name, alvo.last_name = antes
    alvo.save(update_fields=['first_name', 'last_name'])
    if vizinho is not None and antes_vizinho is not None:
        vizinho.first_name, vizinho.last_name = antes_vizinho
        vizinho.save(update_fields=['first_name', 'last_name'])
    print('\n  nomes restaurados')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: cada um edita o proprio nome, a tela abre sem organizacao escolhida,')
print('    espaco em branco e recusado e nao ha caminho para o nome de outro.')
