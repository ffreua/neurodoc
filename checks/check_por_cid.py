"""Buscar paciente por diagnostico: a fronteira, o codigo e o refutado.

"Chegou droga nova para esclerose multipla, quantos pacientes meus se
beneficiariam?" era pergunta que so a memoria respondia, e memoria de
carteira de mil pacientes nao existe.

O que este roteiro cobra, e onde da errado:

- **a tela e clinica, e a secretaria nao entra.** Este e o ponto: a lista
  de pacientes do menu administrativo e aberta aos quatro papeis, e deve
  ser. Um filtro por CID *ali* entregaria "quem aqui tem B24" a qualquer
  pessoa com acesso a agenda. A separacao e o recurso, e uma asercao que
  a comprove vale mais que todas as outras juntas;
- **o codigo casa por prefixo, e o ponto nao conta.** "G40" tem de trazer
  G40.2; "G402" e "G40.2" sao a mesma coisa; e "G40.2" nao pode trazer
  G40.1;
- **o refutado nao conta, e filtrar por certeza nao basta.** Se a hipotese
  foi levantada numa consulta e descartada na seguinte, o registro antigo
  continua dizendo "suspeita". Vale a ultima palavra sobre aquele codigo
  -- o contrario e convidar para estudo de esclerose multipla quem foi
  informado de que nao tem;
- **e a recíproca tambem:** refutada antes, confirmada depois, conta;
- **o acento e dispensavel.** "esclerose multipla" acha G35 pelo catalogo;
- **o diagnostico anotado a mao e achado.** Nem todo diagnostico tem
  codigo do catalogo, e uma busca so por codigo os perderia em silencio;
- **a fronteira entre clinicas.** Paciente da clinica B nao aparece para a
  clinica A, nem com o mesmo CID.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from clinical.models import (
    DiagnosisCertainty, Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus,
)
from clinical.por_cid import ATIVAS, CONFIRMADAS, REFUTADAS, buscar
from patients.models import Patient, PatientStatus, RegistrationStage
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
atendimentos = []
diagnosticos = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:60} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


def contexto_de(tenant, vinculo):
    return AccessContext(
        user_id=vinculo.user_id, tenant_id=tenant.id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles or []), request_id=None,
        tenant_status=tenant.status, capabilities=frozenset(),
    )


def medico_de(tenant, papel='doctor'):
    return Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').first()


tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.exclude(id=tenant_a.id).filter(
    membership__status=MembershipStatus.ACTIVE,
).distinct().first()
medico_a = medico_de(tenant_a)
ctx_a = contexto_de(tenant_a, medico_a)

hoje = timezone.now()


def anotar(tenant, vinculo, paciente, codigo, descricao, certeza, dias_atras=0):
    """Um atendimento com um diagnostico, na data pedida."""
    atendimento = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=vinculo,
        occurred_at=hoje - timezone.timedelta(days=dias_atras),
        status=EncounterStatus.FINALIZED, kind=EncounterKind.FREE_TEXT,
        free_text='Roteiro de verificacao da busca por CID.',
        plan_text='Roteiro.',
    )
    atendimentos.append(atendimento.id)
    diagnostico = EncounterDiagnosis.objects.create(
        tenant=tenant, encounter=atendimento, code_snapshot=codigo,
        description_snapshot=descricao, certainty=certeza, rank=1,
    )
    diagnosticos.append(diagnostico.id)
    return atendimento


def achou(termo, **kwargs):
    pagina = buscar(ctx_a, termo, **kwargs)
    if pagina is None:
        return set()
    return {linha['patient'].id for linha in pagina.object_list}


pacientes_criados = []


def paciente(nome, status=PatientStatus.ACTIVE, estagio=RegistrationStage.COMPLETE, tenant=None):
    p = Patient.objects.create(
        tenant=tenant or tenant_a, full_name=nome, status=status,
        registration_stage=estagio,
    )
    pacientes_criados.append(p.id)
    return p


try:
    print('\n1. A fronteira: a secretaria nao abre esta tela')
    # A assercao que mais importa. A lista de pacientes do menu
    # administrativo e aberta aos quatro papeis; esta nao pode ser.
    url = reverse('clinical:por-cid')
    secretaria = medico_de(tenant_a, 'secretary')
    conferir('a semeadura tem uma secretaria', secretaria is not None, True)

    def sessao_de(vinculo, tenant):
        c = Client()
        c.force_login(vinculo.user)
        s = c.session
        s['tenant_id'] = str(tenant.id)
        s.save()
        return c

    resposta_secretaria = sessao_de(secretaria, tenant_a).get(url)
    conferir('secretaria recebe recusa', resposta_secretaria.status_code in (403, 404), True)
    corpo_secretaria = resposta_secretaria.content.decode()
    conferir('e a recusa nao vaza nome de paciente',
             'G35' in corpo_secretaria or 'Esclerose' in corpo_secretaria, False)

    cliente_medico = sessao_de(medico_a, tenant_a)
    conferir('o medico abre', cliente_medico.get(url).status_code, 200)

    gestor = medico_de(tenant_a, 'manager')
    if gestor is not None:
        conferir('gestor (sem papel medico) tambem nao entra',
                 sessao_de(gestor, tenant_a).get(url).status_code in (403, 404), True)

    print('\n2. O codigo casa por prefixo, e o ponto e pontuacao')
    epileptico = paciente('Roteiro CID Epilepsia')
    anotar(tenant_a, medico_a, epileptico, 'G40.2',
           'Epilepsia e sindromes epilepticas sintomaticas', DiagnosisCertainty.CONFIRMED)
    outro_g40 = paciente('Roteiro CID Epilepsia Outra')
    anotar(tenant_a, medico_a, outro_g40, 'G40.1',
           'Epilepsia parcial sintomatica', DiagnosisCertainty.CONFIRMED)

    conferir('G40 traz os dois subitens', achou('G40') >= {epileptico.id, outro_g40.id}, True)
    conferir('G40.2 traz so o G40.2', epileptico.id in achou('G40.2'), True)
    conferir('e G40.2 nao traz o G40.1', outro_g40.id in achou('G40.2'), False)
    conferir('G402 sem ponto acha o mesmo', epileptico.id in achou('G402'), True)
    conferir('minuscula acha igual', epileptico.id in achou('g40.2'), True)

    print('\n3. O refutado nao conta -- e a ultima palavra e que vale')
    # Suspeita numa consulta, descartada na seguinte. O registro antigo
    # continua no prontuario dizendo "suspeita": uma busca que olhasse cada
    # linha isoladamente devolveria este paciente como se ele tivesse a
    # doenca.
    descartado = paciente('Roteiro CID Descartado')
    anotar(tenant_a, medico_a, descartado, 'G35', 'Esclerose multipla',
           DiagnosisCertainty.SUSPECTED, dias_atras=90)
    anotar(tenant_a, medico_a, descartado, 'G35', 'Esclerose multipla',
           DiagnosisCertainty.REFUTED, dias_atras=10)
    conferir('suspeita antiga + refutada recente -> fora da busca',
             descartado.id in achou('G35'), False)
    conferir('mas aparece na leitura de refutadas',
             descartado.id in achou('G35', leitura=REFUTADAS), True)

    # A reciproca: afastada antes, confirmada depois. Tem de contar.
    confirmado_depois = paciente('Roteiro CID Confirmado Depois')
    anotar(tenant_a, medico_a, confirmado_depois, 'G35', 'Esclerose multipla',
           DiagnosisCertainty.REFUTED, dias_atras=200)
    anotar(tenant_a, medico_a, confirmado_depois, 'G35', 'Esclerose multipla',
           DiagnosisCertainty.CONFIRMED, dias_atras=5)
    conferir('refutada antiga + confirmada recente -> entra',
             confirmado_depois.id in achou('G35'), True)
    conferir('e nao aparece entre as refutadas',
             confirmado_depois.id in achou('G35', leitura=REFUTADAS), False)

    print('\n4. Confirmada e suspeita, e o filtro entre elas')
    suspeito = paciente('Roteiro CID Suspeito')
    anotar(tenant_a, medico_a, suspeito, 'G35', 'Esclerose multipla',
           DiagnosisCertainty.SUSPECTED)
    conferir('o padrao traz confirmada e suspeita',
             {confirmado_depois.id, suspeito.id} <= achou('G35'), True)
    conferir('"so confirmadas" deixa a suspeita de fora',
             suspeito.id in achou('G35', leitura=CONFIRMADAS), False)
    conferir('e mantem a confirmada',
             confirmado_depois.id in achou('G35', leitura=CONFIRMADAS), True)

    print('\n5. Acento dispensavel, e o diagnostico anotado a mao')
    conferir('"esclerose multipla" sem acento acha o G35',
             confirmado_depois.id in achou('esclerose multipla'), True)

    # Diagnostico sem codigo do catalogo: o medico digitou o texto. Uma
    # busca so por codigo o perderia, e ninguem notaria a falta.
    mao = paciente('Roteiro CID Anotado A Mao')
    anotar(tenant_a, medico_a, mao, '', 'Cefaleia em salvas refrataria',
           DiagnosisCertainty.CONFIRMED)
    conferir('acha pelo texto gravado, sem codigo',
             mao.id in achou('salvas'), True)

    print('\n6. O que a lista nao mostra')
    arquivado = paciente('Roteiro CID Arquivado', status=PatientStatus.ARCHIVED)
    anotar(tenant_a, medico_a, arquivado, 'G35', 'Esclerose multipla',
           DiagnosisCertainty.CONFIRMED)
    conferir('arquivado fica de fora por padrao', arquivado.id in achou('G35'), False)
    conferir('e entra quando se pede',
             arquivado.id in achou('G35', incluir_arquivados=True), True)

    preliminar = paciente('Roteiro CID Precadastro', estagio=RegistrationStage.PRELIMINARY)
    anotar(tenant_a, medico_a, preliminar, 'G35', 'Esclerose multipla',
           DiagnosisCertainty.CONFIRMED)
    conferir('pre-cadastro nao aparece', preliminar.id in achou('G35'), False)

    print('\n7. A fronteira entre clinicas')
    if tenant_b is not None:
        medico_b = medico_de(tenant_b)
        if medico_b is not None:
            de_outra = paciente('Roteiro CID Outra Clinica', tenant=tenant_b)
            anotar(tenant_b, medico_b, de_outra, 'G35', 'Esclerose multipla',
                   DiagnosisCertainty.CONFIRMED)
            conferir('paciente da clinica B nao aparece para a A',
                     de_outra.id in achou('G35'), False)
            ctx_b = contexto_de(tenant_b, medico_b)
            vistos_b = {l['patient'].id for l in buscar(ctx_b, 'G35').object_list}
            conferir('e o da A nao aparece para a B',
                     confirmado_depois.id in vistos_b, False)
            conferir('a B ve o proprio', de_outra.id in vistos_b, True)

    print('\n8. Termo curto nao varre o catalogo inteiro')
    conferir('termo vazio nao busca', buscar(ctx_a, ''), None)
    conferir('uma letra so nao busca', buscar(ctx_a, 'G'), None)
    conferir('duas ja buscam', buscar(ctx_a, 'G4') is not None, True)

    print('\n9. A tela responde e mostra o que achou')
    pagina = cliente_medico.get(url, {'q': 'G40'})
    conferir('a busca pela tela responde', pagina.status_code, 200)
    html = pagina.content.decode()
    conferir('o paciente aparece', 'Roteiro CID Epilepsia' in html, True)
    conferir('a tela avisa sobre o refutado',
             'hipótese afastada' in html or 'afastada depois' in html, True)
    vazio = cliente_medico.get(url).content.decode()
    conferir('sem termo, a tela explica em vez de listar',
             'Digite um código' in vazio, True)

finally:
    EncounterDiagnosis.objects.filter(id__in=diagnosticos).delete()
    Encounter.objects.filter(id__in=atendimentos).delete()
    n = Patient.objects.filter(id__in=pacientes_criados).delete()[0]
    print(f'\n  limpeza: {len(diagnosticos)} diagnostico(s), '
          f'{len(atendimentos)} atendimento(s) e {n} objeto(s) de paciente removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: a tela e clinica e a secretaria nao entra, o codigo casa por prefixo,')
print('    e o diagnostico descartado depois nao volta como se fosse doenca.')
