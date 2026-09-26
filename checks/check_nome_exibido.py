"""O nome que aparece na tela e o mesmo que sai na receita?

Encontrado em uso real: o medico se cadastrou, preencheu o perfil
profissional -- nome, CRM, RQE -- e a agenda continuou estampando o
**e-mail** dele. Ele tinha editado o nome na tela de equipe e papeis, e
aquela tela salva `PhysicianProfile.professional_name`; nenhuma tela do
produto edita `User.first_name`, que so se preenche pelo admin tecnico.

O pior nao era a feiura, era a incoerencia: `documents/issuance.py` e
`documents/verification.py` ja usavam `professional_name`, entao o mesmo
medico saia "Fernando Freua" no documento que o paciente leva a farmacia e
"dr.freua@gmail.com" na agenda de quem o atende.

O que este roteiro cobra:

- a cascata de `get_full_name`: conta > perfil profissional > e-mail;
- que `get_short_name` siga a mesma ordem -- sem isso a saudacao do topo
  diz "Ola, dr.freua@gmail.com" para quem a agenda ao lado ja chama pelo
  nome;
- que quem NAO e medico continue caindo no e-mail, como antes;
- **que a tela e o documento nao divirjam** -- a assercao que teria pego
  este defeito no dia em que ele nasceu;
- que a agenda nao faca uma consulta por linha para descobrir o nome.
"""
from django.conf import settings as dj_settings
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.db import connection

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import PhysicianProfile, User
from tenancy.models import Membership, MembershipStatus, Role

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:56} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


medico = User.objects.filter(physician_profile__isnull=False).first()
assert medico is not None, 'a semeadura precisa de ao menos um medico com perfil'
perfil = medico.physician_profile
nome_antes, sobrenome_antes = medico.first_name, medico.last_name
nome_prof_antes = perfil.professional_name

try:
    print('\n1. A cascata: conta > perfil profissional > e-mail')
    medico.first_name = 'Nome'
    medico.last_name = 'DaConta'
    medico.save(update_fields=['first_name', 'last_name'])
    medico.refresh_from_db()
    conferir('com nome na conta, vence o da conta', medico.get_full_name(), 'Nome DaConta')

    medico.first_name = ''
    medico.last_name = ''
    medico.save(update_fields=['first_name', 'last_name'])
    medico = User.objects.get(pk=medico.pk)
    perfil = medico.physician_profile
    perfil.professional_name = 'Dra. Teste Do Roteiro'
    perfil.save(update_fields=['professional_name'])
    medico = User.objects.get(pk=medico.pk)
    conferir('sem nome na conta, usa o profissional',
             medico.get_full_name(), 'Dra. Teste Do Roteiro')
    conferir('o primeiro nome tambem', medico.get_short_name(), 'Dra.')

    # O e-mail e o ultimo recurso, e nao o primeiro. Este caso e o defeito
    # original: perfil preenchido e a tela mostrando o endereco de e-mail.
    conferir('NAO cai no e-mail tendo perfil',
             medico.get_full_name() == medico.email, False)

    print('\n2. Quem nao e medico segue no e-mail, como antes')
    outro = User.objects.filter(physician_profile__isnull=True, first_name='').first()
    if outro is None:
        outro = User.objects.create_user(email='zz-sem-perfil@example.invalid')
        criado = True
    else:
        criado = False
    conferir('sem perfil e sem nome, cai no e-mail', outro.get_full_name(), outro.email)
    conferir('primeiro nome idem', outro.get_short_name(), outro.email)
    if criado:
        outro.delete()

    print('\n3. A tela e o documento dizem o MESMO nome')
    # A assercao que teria pego o defeito no dia em que nasceu. A emissao
    # assina com `professional_name` (`documents/issuance.py`), e a
    # verificacao publica do QR mostra o mesmo (`documents/verification.py`).
    # Se a tela divergir disso, o paciente le um nome na receita e o
    # consultorio ve outro na agenda.
    medico = User.objects.get(pk=medico.pk)
    conferir('nome na tela == nome que assina o documento',
             medico.get_full_name(), medico.physician_profile.professional_name)

    print('\n4. A agenda nao consulta o banco uma vez por linha')
    vinculo = Membership.objects.filter(
        user=medico, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).select_related('tenant').first()
    if vinculo is None:
        print('  (medico sem vinculo ativo; secao pulada)')
    else:
        c = Client()
        c.force_login(medico)
        sessao = c.session
        sessao['tenant_id'] = str(vinculo.tenant_id)
        sessao.save()
        with CaptureQueriesContext(connection) as capturadas:
            resposta = c.get('/app/scheduling/dia/')
        consultas_de_perfil = sum(
            1 for q in capturadas.captured_queries
            if 'accounts_physicianprofile' in q['sql'].lower()
        )
        print(f'  agenda do dia -> HTTP {resposta.status_code}, '
              f'{len(capturadas.captured_queries)} consultas no total, '
              f'{consultas_de_perfil} tocando o perfil profissional')
        # Duas ou menos: as consultas trazem o perfil por `select_related`,
        # entao o que sobra e a do proprio usuario da sessao. Uma por
        # agendamento apareceria como dezenas.
        if consultas_de_perfil > 3:
            falhas.append(
                f'a agenda faz {consultas_de_perfil} consultas ao perfil profissional; '
                f'falta `select_related` em alguma delas'
            )
        corpo = resposta.content.decode('utf-8', 'replace')
        # Mira no elemento que nomeia o medico, e nao na pagina inteira: o
        # menu do topo mostra o e-mail da conta logada de proposito
        # (`partials/header.html`), logo abaixo do nome, e e assim que se
        # sabe em qual conta se esta. Procurar o e-mail no corpo todo
        # acusaria aquele -- foi o falso positivo que a primeira versao
        # deste roteiro deu.
        import re as _re

        nomes = _re.findall(
            r'<span class="fs-11 text-muted">\s*(.*?)\s*</span>', corpo, _re.S,
        )
        nome_na_agenda = nomes[0].strip() if nomes else '(nao encontrado)'
        conferir('a agenda nomeia o medico pelo nome profissional',
                 nome_na_agenda, medico.physician_profile.professional_name)
        conferir('e nao pelo e-mail', nome_na_agenda == medico.email, False)

finally:
    medico = User.objects.get(pk=medico.pk)
    medico.first_name, medico.last_name = nome_antes, sobrenome_antes
    medico.save(update_fields=['first_name', 'last_name'])
    p = PhysicianProfile.objects.filter(user=medico).first()
    if p is not None:
        p.professional_name = nome_prof_antes
        p.save(update_fields=['professional_name'])
    print('\n  nome da conta e nome profissional restaurados')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: a tela chama o medico pelo nome profissional quando a conta nao tem nome,')
print('    diz o mesmo que a receita assinada, e nao consulta o banco por linha.')
