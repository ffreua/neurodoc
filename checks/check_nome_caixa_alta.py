"""O nome do paciente numa forma so: caixa alta, sem espaco sobrando.

Tres pessoas cadastram e saem tres grafias. A lista de pacientes vira um
mosaico, a agenda tambem, e o documento impresso herda a pressa de quem
digitou.

O que este roteiro cobra, e onde da errado:

- **todo caminho que cria paciente normaliza.** Sao quatro, e so um passa
  por formulario: o cadastro completo, o pre-cadastro que a secretaria faz
  ao telefone, a importacao e a semeadura. Normalizar so no formulario
  deixaria tres de quatro de fora -- que e exatamente como a grafia solta
  entrava;
- **o acento permanece.** "JOSE" nao e padronizar aparencia, e escrever o
  nome errado;
- **o espaco em excesso some.** Dois espacos no meio nao aparecem na tela,
  aparecem na busca: ninguem acha "Maria  Silva" procurando "Maria Silva";
- **a busca continua achando.** Quem digita minuscula tem de achar;
- **o nome da mae acompanha**, porque sai na mesma receita;
- **o contato do proprio paciente acompanha**, e o **do parente nao**:
  padronizar aparencia nao autoriza reescrever o nome de quem cuida;
- **a funcao e idempotente.** Ela roda no `clean()` e no `save()`, e dois
  passes nao podem produzir resultado diferente de um.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from patients.contacts import SELF_RELATIONSHIP
from patients.models import Patient, PatientContact, RegistrationStage
from patients.naming import normalizar_nome
from patients.selectors import busca_rapida, list_patients
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = []
contatos = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido!r}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado!r}, obtido {obtido!r}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()
ctx = AccessContext(
    user_id=vinculo.user_id, tenant_id=tenant.id, membership_id=vinculo.id,
    permissions=frozenset(vinculo.roles or []), request_id=None,
    tenant_status=tenant.status, capabilities=frozenset(),
)


def _cpf_valido(base):
    """Completa os dois digitos verificadores que a ficha exige."""
    n = [int(x) for x in base]
    d1 = (sum(v * p for v, p in zip(n, range(10, 1, -1))) * 10) % 11 % 10
    d2 = (sum(v * p for v, p in zip(n + [d1], range(11, 1, -1))) * 10) % 11 % 10
    return base + str(d1) + str(d2)


def criar(nome, **extra):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome,
        registration_stage=extra.pop('estagio', RegistrationStage.COMPLETE),
        **extra,
    )
    criados.append(p.id)
    return p


try:
    print('\n1. A funcao, isolada')
    conferir('caixa alta', normalizar_nome('maria da silva'), 'MARIA DA SILVA')
    conferir('o acento permanece', normalizar_nome('josé antônio'), 'JOSÉ ANTÔNIO')
    conferir('ç vira Ç, nao C', normalizar_nome('conceição'), 'CONCEIÇÃO')
    conferir('espaco duplo colapsa', normalizar_nome('Maria  da   Silva'), 'MARIA DA SILVA')
    conferir('espaco nas pontas some', normalizar_nome('  Ana Paula  '), 'ANA PAULA')
    conferir('quebra de linha tambem', normalizar_nome('Ana\nPaula'), 'ANA PAULA')
    conferir('vazio nao estoura', normalizar_nome(''), '')
    conferir('None nao estoura', normalizar_nome(None), '')
    # Roda no clean() e no save(): dois passes tem de dar o mesmo.
    uma_vez = normalizar_nome('maria  da silva')
    conferir('idempotente', normalizar_nome(uma_vez), uma_vez)

    print('\n2. Todo caminho que cria paciente normaliza')
    # `objects.create()` nao chama `full_clean()`. E o caminho do
    # pre-cadastro da agenda, da importacao e da semeadura.
    direto = criar('joão carlos  pereira')
    conferir('create() direto, sem formulario', direto.full_name, 'JOÃO CARLOS PEREIRA')
    direto.refresh_from_db()
    conferir('e o que foi parar no banco', direto.full_name, 'JOÃO CARLOS PEREIRA')

    preliminar = criar('ana  beatriz', estagio=RegistrationStage.PRELIMINARY)
    conferir('pre-cadastro da agenda', preliminar.full_name, 'ANA BEATRIZ')

    # Renomear tambem passa pela normalizacao.
    direto.full_name = 'joão carlos de souza'
    direto.save()
    direto.refresh_from_db()
    conferir('renomear tambem normaliza', direto.full_name, 'JOÃO CARLOS DE SOUZA')

    # `save(update_fields=...)` e o caminho que mais escapa de validacao.
    direto.full_name = 'joao c. souza'
    direto.save(update_fields=['full_name'])
    direto.refresh_from_db()
    conferir('save(update_fields) tambem', direto.full_name, 'JOAO C. SOUZA')

    print('\n3. O formulario mostra o nome como ele vai ficar')
    from patients.forms import PatientForm

    molde = PatientForm(tenant_id=tenant.id)
    corpo = {}
    for nome_campo, campo in molde.fields.items():
        if not campo.required:
            continue
        if nome_campo == 'full_name':
            corpo[nome_campo] = 'carla  mendes'
        elif nome_campo == 'cpf':
            # Um CPF que ninguem usa nesta clinica: a ficha o exige, e o
            # campo tem restricao de unicidade por inquilino.
            base = '529982246'
            while Patient.objects.filter(
                tenant=tenant, cpf=_cpf_valido(base),
            ).exists():
                base = str(int(base) + 1).zfill(9)
            corpo[nome_campo] = _cpf_valido(base)
        elif hasattr(campo, 'choices'):
            opcoes = [v for v, _ in campo.choices if v not in ('', None)]
            corpo[nome_campo] = opcoes[0]
        else:
            corpo[nome_campo] = 'Roteiro'
    corpo['birth_date_unknown_reason'] = 'Roteiro de verificacao.'
    formulario = PatientForm(corpo, tenant_id=tenant.id)
    if formulario.is_valid():
        salvo = formulario.save(commit=False)
        salvo.tenant = tenant
        salvo.save()
        criados.append(salvo.id)
        conferir('pelo formulario', salvo.full_name, 'CARLA MENDES')
    else:
        print(f'      (formulario recusou: {dict(formulario.errors)})')
        conferir('o formulario aceitou o cadastro', True, False)

    print('\n4. O nome da mae acompanha -- sai na mesma receita')
    com_mae = criar('pedro alves', mother_name='joana  alves')
    conferir('mae normalizada', com_mae.mother_name, 'JOANA ALVES')

    print('\n5. O contato do proprio paciente acompanha; o do parente, nao')
    proprio = PatientContact.objects.create(
        tenant=tenant, patient=com_mae, name=com_mae.full_name,
        relationship=SELF_RELATIONSHIP, phone='11999990000',
    )
    parente = PatientContact.objects.create(
        tenant=tenant, patient=com_mae, name='Joana Alves',
        relationship='Mãe', phone='11999990001',
    )
    contatos += [proprio.id, parente.id]

    from patients.contacts import sync_self_contact_name

    com_mae.full_name = 'pedro henrique alves'
    com_mae.save()
    com_mae.refresh_from_db()
    sync_self_contact_name(com_mae)
    proprio.refresh_from_db()
    parente.refresh_from_db()
    conferir('o contato do proprio paciente seguiu', proprio.name, 'PEDRO HENRIQUE ALVES')
    conferir('e o do parente ficou como estava', parente.name, 'Joana Alves')

    print('\n6. A busca continua achando quem digita minuscula')
    achados = {p.id for p in busca_rapida(ctx, 'joão carlos')}
    conferir('busca rapida por minuscula acha', direto.id in achados or
             direto.id in {p.id for p in busca_rapida(ctx, 'joao c')}, True)
    pagina = list_patients(ctx, query='pedro henrique')
    conferir('lista de pacientes por minuscula acha',
             com_mae.id in {p.id for p in pagina.object_list}, True)
    pagina_alta = list_patients(ctx, query='PEDRO HENRIQUE')
    conferir('e por maiuscula tambem',
             com_mae.id in {p.id for p in pagina_alta.object_list}, True)

    print('\n7. Nenhuma ficha antiga ficou fora do padrao')
    # A migracao passou por todas. Se alguma escapou, ela aparece aqui --
    # e e justamente a que vai destoar na lista da secretaria.
    fora = [
        (p.id, p.full_name) for p in Patient.objects.filter(tenant=tenant)
        .only('id', 'full_name')
        if p.full_name != normalizar_nome(p.full_name)
    ]
    for _, nome in fora[:5]:
        print(f'      fora do padrao: {nome!r}')
    conferir('fichas fora do padrao', len(fora), 0)

finally:
    PatientContact.objects.filter(id__in=contatos).delete()
    n = Patient.objects.filter(id__in=criados).delete()[0]
    print(f'\n  limpeza: {n} objeto(s) de paciente removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o nome entra em caixa alta por todos os caminhos, o acento fica,')
print('    a busca continua achando e o nome do parente nao foi reescrito.')
