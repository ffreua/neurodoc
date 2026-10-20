"""A busca acha o paciente pelas palavras do nome, em qualquer ordem e sem acento.

Relatado em uso real (2026-10-20): ao marcar um horário, "a paciente não
aparece". A busca era `full_name__icontains=<o que foi digitado>` — o
trecho exato e contíguo, com os acentos certos. Quem procura uma paciente
de quatro nomes digita o primeiro e o último, e quem digita no balcão não
digita acento. As três buscas (a da agenda, a rápida do topo e a lista de
pacientes) passaram a perguntar a mesma coisa: cada palavra no nome.

As perguntas são:
  1. primeiro e último nome, pulando o meio, acham?
  2. a ordem das palavras não importa?
  3. sem acento acha o nome gravado com acento, e com acento também?
  4. palavra que não está no nome tira o paciente da lista (é E, não OU)?
  5. o número do prontuário continua achando, com e sem os zeros?
  6. nada de outra clínica, e o arquivado fica fora da agenda?
  7. as três portas — agenda, busca rápida e lista — respondem igual?
"""
import datetime
import uuid

from django.conf import settings
from django.test import Client

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']
settings.SECURE_SSL_REDIRECT = False

from patients.models import Patient, PatientStatus
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def conferir(condicao, rotulo):
    print(('ok    ' if condicao else 'FALHA ') + rotulo)
    if not condicao:
        falhas.append(rotulo)


tenant = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.get(slug='demo-clinica-b')
secretaria = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.SECRETARY],
).select_related('user').first()
if secretaria is None:
    print('PULADO: demonstração sem secretária')
    raise SystemExit(0)

marca = uuid.uuid4().hex[:5].upper()
criados = []


def paciente(t, nome, status=PatientStatus.ACTIVE):
    p = Patient.objects.create(
        tenant=t, full_name=nome, birth_date=datetime.date(1970, 1, 1), status=status,
    )
    criados.append(p)
    return p


cliente = Client()
cliente.force_login(secretaria.user)
s = cliente.session
s['tenant_id'] = str(tenant.id)
s.save()


def agenda(q):
    r = cliente.get('/app/patients/autocomplete/', {'q': q})
    return {item['id'] for item in r.json()['results']}


def rapida(q):
    r = cliente.get('/app/patients/busca-rapida/', {'q': q})
    return {str(item.get('id')) for item in r.json()['resultados']}


def lista(q):
    return cliente.get('/app/patients/', {'q': q}).content.decode()


try:
    jose = paciente(tenant, f'JOSÉ ANTÔNIO DA CONCEIÇÃO {marca}')
    alvo = str(jose.id)
    paciente(outra, f'JOSÉ ANTÔNIO DA CONCEIÇÃO {marca}')
    arquivado = paciente(tenant, f'MARIA ARQUIVADA SILVEIRA {marca}', PatientStatus.ARCHIVED)

    print('=== 1. primeiro e último, pulando o meio ===')
    conferir(alvo in agenda(f'jose {marca}'), 'primeiro nome e o último acham')
    conferir(alvo in agenda(f'antonio conceicao {marca}'), 'dois do meio, sem acento, acham')

    print('=== 2. em qualquer ordem ===')
    conferir(alvo in agenda(f'{marca} conceição josé'), 'de trás para frente acha')

    print('=== 3. acento ===')
    conferir(alvo in agenda(f'jose antonio {marca}'), 'sem acento acha o nome com acento')
    conferir(alvo in agenda(f'JOSÉ ANTÔNIO {marca}'), 'com acento também acha')
    conferir(alvo in agenda(f'Conceicao {marca}'), 'ç digitado como c acha')

    print('=== 4. é E, não OU ===')
    conferir(alvo not in agenda(f'jose pereira {marca}'), 'palavra que não está no nome tira o paciente')

    print('=== 5. número do prontuário ===')
    numero = jose.record_number
    conferir(alvo in agenda(numero), f'o número inteiro acha ({numero})')
    conferir(alvo in agenda(numero.lstrip('0')), 'sem os zeros também')

    print('=== 6. fronteiras ===')
    ids = agenda(f'jose conceicao {marca}')
    conferir(ids == {alvo}, f'só o desta clínica volta (vieram {len(ids)})')
    conferir(str(arquivado.id) not in agenda(f'maria silveira {marca}'),
             'o arquivado não aparece para marcar horário')

    print('=== 7. as três portas ===')
    conferir(alvo in rapida(f'jose conceicao {marca}'),
             'a busca rápida do topo acha pelas palavras')
    conferir(f'JOSÉ ANTÔNIO DA CONCEIÇÃO {marca}' in lista(f'conceicao jose {marca}'),
             'a lista de pacientes acha pelas palavras')
    conferir(cliente.get('/app/patients/autocomplete/', {'q': '12345'}).status_code == 200,
             'só dígitos não quebra a busca')
finally:
    Patient.objects.filter(id__in=[p.id for p in criados]).delete()

if falhas:
    print(f'\nFALHA: {len(falhas)} item(ns): ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: a busca acha o paciente pelas palavras do nome, em qualquer ordem e sem acento.')
