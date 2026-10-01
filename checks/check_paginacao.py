"""Paginacao: as telas aguentam a primeira e a ultima pagina.

Defeito de paginacao tem uma propriedade cruel: ele **nao existe** enquanto
a base e pequena. Com menos de uma pagina de dados o bloco de navegacao nem
e renderizado, e todo roteiro passa. Ele nasce no dia em que a clinica
cresce -- ou, como aconteceu aqui, no minuto em que duas mil fichas sao
migradas de uma vez. A tela principal da secretaria virou erro 500 na
mesma hora.

**O que quebrou, e por que passou despercebido.** A lista de pacientes
escrevia `{{ patients.previous_page_number|default:1 }}`. Parece defensivo
e nao e: o filtro `default` trata valor **vazio**, nao **excecao** -- e
`previous_page_number` levanta `EmptyPage` na primeira pagina, porque a
pagina zero nao existe. O template Django so engole excecao que se declara
silenciosa, e `EmptyPage` nao se declara.

Por isso este roteiro **cria volume** antes de olhar: sem passar de uma
pagina, ele nao testaria nada.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse

from patients.models import Patient, RegistrationStage
from patients.selectors import PAGE_SIZE
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:56} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()
cliente = Client()
cliente.force_login(vinculo.user)
sessao = cliente.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()

try:
    print(f'\n1. Criando volume ({PAGE_SIZE} por pagina, precisamos de 3 paginas)')
    # Sem volume, o bloco de paginacao nao e renderizado e o roteiro
    # passaria sem olhar para nada.
    quantos = PAGE_SIZE * 3
    existentes = Patient.objects.filter(
        tenant=tenant, registration_stage=RegistrationStage.COMPLETE,
        status='active',
    ).count()
    faltam = max(0, quantos - existentes)
    for i in range(faltam):
        p = Patient.objects.create(
            tenant=tenant, full_name=f'Roteiro Paginacao {i:04d}',
            registration_stage=RegistrationStage.COMPLETE,
            birth_date_unknown_reason='Roteiro de verificacao.',
        )
        criados.append(p.id)
    print(f'      criados {faltam}; total agora {existentes + faltam}')

    url = reverse('patients:list')
    primeira = cliente.get(url)
    conferir('a lista abre na primeira pagina', primeira.status_code, 200)
    html = primeira.content.decode()
    paginas = primeira.context['patients'].paginator.num_pages if primeira.context else None
    conferir('e ha mais de uma pagina mesmo', paginas is None or paginas > 1, True)
    conferir('o bloco de paginacao aparece', 'Paginação' in html, True)
    conferir('"Anterior" aparece desabilitado, nao como link quebrado',
             'page-item disabled' in html, True)
    # `pagination-common-style` forca `width:30px; height:30px;
    # border-radius:100%` em todo `li a` -- feita para bolinhas numeradas,
    # nao para rotulos de palavra. Com ela, "Proxima" saia espremida num
    # circulo de 30px e o texto transbordava por cima da borda.
    conferir('a paginacao nao usa a classe de bolinha numerada',
             'pagination-common-style' in html, False)
    conferir('os rotulos sao palavras, e nao numeros',
             'Anterior' in html and 'Próxima' in html, True)

    print('\n2. A ultima pagina tambem abre')
    total = Patient.objects.filter(
        tenant=tenant, registration_stage=RegistrationStage.COMPLETE, status='active',
    ).count()
    ultima_pagina = (total + PAGE_SIZE - 1) // PAGE_SIZE
    ultima = cliente.get(url, {'page': ultima_pagina})
    conferir(f'pagina {ultima_pagina} (a ultima)', ultima.status_code, 200)

    print('\n3. Pagina invalida nao vira erro 500')
    # `get_page` do Django trata as tres; o roteiro confere que a tela
    # inteira sobrevive, e nao so o seletor.
    for rotulo, valor in [('zero', '0'), ('negativa', '-3'),
                          ('alem do fim', '99999'), ('texto', 'abc')]:
        conferir(f'?page={valor} ({rotulo})', cliente.get(url, {'page': valor}).status_code, 200)

    print('\n4. A busca com resultado grande tambem pagina')
    busca = cliente.get(url, {'q': 'Roteiro Paginacao'})
    conferir('a busca abre', busca.status_code, 200)
    conferir('e a primeira pagina dela nao quebra',
             'Paginação' in busca.content.decode(), True)
    conferir('a ultima pagina da busca abre',
             cliente.get(url, {'q': 'Roteiro Paginacao', 'page': 2}).status_code, 200)

    print('\n5. A busca devolve quem se procurou, e nao a clinica inteira')
    # `Q(cpf=digits)` com `digits` vazio vira `Q(cpf="")` e casa com todo
    # paciente sem CPF; o mesmo com telefone. Com uma duzia de fichas
    # ninguem percebe -- nenhuma tem o campo em branco. Com duas mil,
    # buscar "Fernando" devolvia noventa e cinco pessoas, das quais vinte
    # e uma se chamavam Fernando, e a primeira pagina vinha cheia de nomes
    # comecados em A. Quem usa le isso como "a busca nao funciona".
    from patients.selectors import list_patients
    from tenancy.context import AccessContext

    ctx = AccessContext(
        user_id=vinculo.user_id, tenant_id=tenant.id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles or []), request_id=None,
        tenant_status=tenant.status, capabilities=frozenset(),
    )
    alvo = Patient.objects.create(
        tenant=tenant, full_name='Roteiro Busca Alvo Unico',
        registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro.',
    )
    criados.append(alvo.id)
    # O ruido: sem CPF e sem telefone, que era o estado que poluia o OR.
    ruido = Patient.objects.create(
        tenant=tenant, full_name='Aaaa Ruido Sem Cpf Nem Fone',
        registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro.',
    )
    criados.append(ruido.id)

    achados = list_patients(ctx, query='Roteiro Busca Alvo')
    nomes = {p.full_name for p in achados.object_list}
    conferir('a busca por nome acha quem tem o nome',
             'ROTEIRO BUSCA ALVO UNICO' in nomes, True)
    conferir('e NAO traz quem so tem o campo em branco',
             'AAAA RUIDO SEM CPF NEM FONE' in nomes, False)
    conferir('o total e so o de quem tem o nome', achados.paginator.count, 1)

    # O que a busca por numero tem de continuar achando.
    com_numero = list_patients(ctx, query=alvo.record_number)
    conferir('busca pelo numero do prontuario ainda acha',
             alvo.id in {p.id for p in com_numero.object_list}, True)

    print('\n6. As demais telas paginadas')
    # A busca por CID pagina pela mesma mecanica.
    for nome, endereco, par in [
        ('pacientes por CID', reverse('clinical:por-cid'), {'q': 'G40'}),
        ('pacientes por CID, pagina 1', reverse('clinical:por-cid'), {'q': 'G40', 'page': '1'}),
        ('pacientes por CID, pagina invalida', reverse('clinical:por-cid'),
         {'q': 'G40', 'page': '0'}),
    ]:
        conferir(nome, cliente.get(endereco, par).status_code, 200)

finally:
    n = Patient.objects.filter(id__in=criados).delete()[0]
    print(f'\n  limpeza: {n} objeto(s) de paciente removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: a primeira e a ultima pagina abrem, e numero de pagina invalido')
print('    nao vira erro 500.')
