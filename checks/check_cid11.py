"""A CID-11 ao lado da CID-10 (1.44).

Pedido do Dr. Fernando em 2026-11-10: além da CID-10, que está nas
hipóteses, na busca de paciente por diagnóstico e na busca de códigos, o
sistema passa a oferecer a CID-11 -- **sem tirar a CID-10 de lugar
nenhum**.

O roteiro tenta quebrar as duas metades da promessa:

- que a CID-11 exista inteira e do jeito que a OMS publicou (a planilha
  conferida por SHA-256, a leitura estrita, o que ficou de fora de
  propósito);
- que nada da CID-10 tenha mudado: a busca sem dizer o sistema continua
  devolvendo só CID-10, e código de uma não aparece na busca da outra.

E a peça em que o desenho todo se apoia: **o código diz de qual
classificação é** -- não há coluna nova no prontuário.

Tudo dentro de pacientes e atendimentos criados e apagados aqui.
"""
import tempfile
from pathlib import Path

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.template import Context, Template
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from catalogs import cid
from catalogs.models import CatalogRelease, CatalogReleaseStatus, DiagnosisCode
from catalogs.selectors import active_release, search_diagnosis_codes
from clinical.forms import DiagnosisForm
from clinical.models import (
    DiagnosisCertainty, Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus,
)
from clinical.por_cid import buscar
from patients.models import Patient, RegistrationStage
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'atendimentos': [], 'pacientes': []}


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:60} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo_de(papel, clinica=tenant):
    return Membership.objects.filter(
        tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').order_by('user__email').first()


medico = vinculo_de('doctor')
secretaria = vinculo_de('secretary')
medico_b = vinculo_de('doctor', tenant_b)


def cliente(vinculo, clinica=tenant):
    c = Client()
    c.force_login(vinculo.user)
    sessao = c.session
    sessao['tenant_id'] = str(clinica.id)
    sessao.save()
    return c


def paciente(nome):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome, registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['pacientes'].append(p.id)
    return p


def atendimento(pac, status=EncounterStatus.DRAFT, kind=EncounterKind.FREE_TEXT):
    a = Encounter.objects.create(
        tenant=tenant, patient=pac, physician_membership=medico, occurred_at=timezone.now(),
        status=status, kind=kind, free_text='Roteiro de verificacao da CID-11.', plan_text='Roteiro.',
    )
    criados['atendimentos'].append(a.id)
    return a


def codigos(termo, **kw):
    return [linha['code'] for linha in search_diagnosis_codes(termo, **kw)]


try:
    print('\n1. O código diz de qual classificação é')
    for codigo, esperado in (
        ('G40', 'CID10'), ('g40.2', 'CID10'), ('F03', 'CID10'),
        ('8A60', 'CID11'), ('8a60.0', 'CID11'), ('BA00.1', 'CID11'), ('MG40', 'CID11'),
        ('8A00.0&XK9J', 'CID11'), ('1A36.0Y', 'CID11'),
        ('', ''), ('8A', ''), ('Epilepsia', ''), ('Élan', ''), ('—', ''),
    ):
        conferir(f'{codigo!r}', cid.sistema_do_codigo(codigo), esperado)
    conferir('hipótese com código da CID-11 imprime "CID-11"',
             cid.rotulo_da_hipotese('8A40 — Esclerose múltipla'), 'CID-11')
    conferir('  com código da CID-10 imprime "CID-10"',
             cid.rotulo_da_hipotese('G35 — Esclerose múltipla'), 'CID-10')
    conferir('  só com a descrição fica como o papel sempre disse',
             cid.rotulo_da_hipotese('Epilepsia focal a esclarecer'), 'CID-10')
    conferir('parâmetro de busca desconhecido é CID-10',
             [cid.sistema_do_pedido(v) for v in ('cid11', 'CID-11', 'CID11', '', None, 'tuss', 'cid10')],
             ['CID11', 'CID11', 'CID11', 'CID10', 'CID10', 'CID10', 'CID10'])

    print('\n2. A CID-11 está carregada, e é a planilha da OMS')
    r11, r10 = active_release('CID11'), active_release('CID10')
    conferir('há CID-11 ativa', bool(r11), True)
    conferir('a CID-10 continua ativa', bool(r10), True)
    total11 = r11.diagnosis_codes.count()
    conferir('mais de 15 mil códigos', total11 > cid.MINIMO_DE_CODIGOS, True)
    conferir('a licença e a fonte gravadas na carga',
             ('CC BY-ND 3.0 IGO' in r11.license_note, 'icd.who.int' in r11.source_url), (True, True))
    conferir('a planilha do repositório é a conferida',
             cid.sha256_do_arquivo(cid.CID11_ARQUIVO), cid.CID11_SHA256)
    conferir('  e é o SHA-256 dela que a carga guarda', r11.content_sha256, cid.CID11_SHA256)
    conferir('nenhum código de extensão (capítulo X)',
             r11.diagnosis_codes.filter(code__startswith='X').count(), 0)
    conferir('todo código da carga é lido como CID-11',
             sum(1 for c in r11.diagnosis_codes.values_list('code', flat=True)
                 if cid.sistema_do_codigo(c) != 'CID11'), 0)
    conferir('todo código da CID-10 é lido como CID-10',
             sum(1 for c in r10.diagnosis_codes.values_list('code', flat=True)
                 if cid.sistema_do_codigo(c) != 'CID10'), 0)
    conferir('nenhum título vazio nem com o traço de indentação',
             r11.diagnosis_codes.filter(description='').count()
             + r11.diagnosis_codes.filter(description__startswith='- ').count(), 0)
    parkinson = r11.diagnosis_codes.get(code='8A00.0')
    conferir('8A00.0 é a doença de Parkinson, filha de 8A00',
             (parkinson.description, parkinson.parent_code), ('Doença de Parkinson', '8A00'))
    conferir('8A00.01 é filha de 8A00.0',
             r11.diagnosis_codes.get(code='8A00.01').parent_code, '8A00.0')
    conferir('o residual sem tradução da OMS entra, com o título dela',
             r11.diagnosis_codes.filter(code='1A36.0Y').exclude(description='').exists(), True)

    print('\n3. A busca: uma classificação por vez, e a CID-10 como sempre')
    conferir('sem dizer o sistema, G40 é a epilepsia da CID-10', codigos('G40')[:1], ['G40'])
    conferir('  e um código da CID-11 não aparece', codigos('8A60'), [])
    conferir('  nem pelo nome vem código da CID-11',
             [c for c in codigos('esclerose multipla') if cid.sistema_do_codigo(c) != 'CID10'], [])
    conferir('na CID-11, pelo código', codigos('8A60', system='CID11')[:2], ['8A60', '8A60.0'])
    conferir('  em minúscula e sem o ponto', codigos('8a600', system='CID11')[:1], ['8A60.0'])
    conferir('  pelo começo do código',
             all(c.startswith('8A6') for c in codigos('8A6', system='CID11')) and bool(codigos('8A6', system='CID11')),
             True)
    conferir('  pelo nome, sem acento', codigos('esclerose multipla', system='CID11')[:1], ['8A40'])
    conferir('  e a busca da CID-11 só devolve CID-11',
             [c for c in codigos('epilepsia', system='CID11') if cid.sistema_do_codigo(c) != 'CID11'], [])
    conferir('cada resultado diz o sistema',
             {linha['system'] for linha in search_diagnosis_codes('enxaqueca', system='CID11')}, {'CID11'})
    conferir('termo curto demais não busca', codigos('8', system='CID11'), [])

    print('\n4. As rotas')
    med, sec = cliente(medico), cliente(secretaria)
    busca = reverse('clinical:cid-lookup')
    r = med.get(busca, {'q': 'esclerose multipla', 'sistema': 'CID11'})
    conferir('o autocomplete da hipótese responde pela CID-11',
             (r.status_code, r.json()['results'][0]['code']), (200, '8A40'))
    r = med.get(busca, {'q': 'G35'})
    conferir('  e, sem o parâmetro, pela CID-10', r.json()['results'][0]['code'], 'G35')
    r = med.get(busca, {'q': 'G35', 'sistema': 'qualquer'})
    conferir('  parâmetro inventado cai na CID-10', r.json()['results'][0]['code'], 'G35')
    apoio = reverse('catalogs:cid-search')
    r = sec.get(apoio, {'q': '8A80', 'sistema': 'cid11'})
    conferir('a busca de códigos (qualquer vínculo) acha a enxaqueca na CID-11',
             (r.status_code, r.json()['results'][0]['code']), (200, '8A80'))
    conferir('  e continua na CID-10 sem o parâmetro',
             sec.get(apoio, {'q': 'G43'}).json()['results'][0]['code'], 'G43')
    pagina = sec.get(reverse('catalogs:search')).content.decode()
    conferir('a tela tem as três abas',
             ('id="aba-cid"' in pagina, 'id="aba-cid11"' in pagina, 'id="aba-tuss"' in pagina), (True, True, True))
    conferir('  abre na CID-10', 'show active" id="aba-cid"' in pagina, True)
    conferir('  a atribuição à OMS e a licença estão escritas', 'CC BY-ND 3.0 IGO' in pagina, True)
    conferir('  e o que ficou de fora também', 'códigos de extensão' in pagina, True)
    pagina = sec.get(reverse('catalogs:search'), {'aba': 'cid11'}).content.decode()
    conferir('?aba=cid11 abre na CID-11', 'show active" id="aba-cid11"' in pagina, True)
    js = open('static/catalogs/search.js', encoding='utf-8').read()
    conferir('o script monta a aba nova', "input: 'nd-cid11-q'" in js, True)

    print('\n5. A hipótese no atendimento')
    pac = paciente('ROTEIRO CID ONZE')
    aberto = atendimento(pac)
    tela = med.get(reverse('clinical:detail', args=[aberto.id])).content.decode()
    conferir('o formulário oferece a classificação', 'name="cid_sistema"' in tela, True)
    conferir('  com a CID-10 escolhida',
             '<option value="CID10" selected>CID-10</option>' in tela, True)
    form = DiagnosisForm()
    conferir('o seletor não é obrigatório (o POST antigo, sem ele, vale)',
             form.fields['cid_sistema'].required, False)
    alvo = DiagnosisCode.objects.get(release=r11, code='8A40')
    r = med.post(reverse('clinical:add-diagnosis', args=[aberto.id]), {
        'diagnosis_code_id': str(alvo.id), 'code_snapshot': '8A40',
        'description_snapshot': alvo.description, 'certainty': DiagnosisCertainty.CONFIRMED,
        'rank': 1, 'cid_sistema': 'CID11',
    })
    d11 = EncounterDiagnosis.objects.filter(encounter=aberto, code_snapshot='8A40').first()
    conferir('a hipótese da CID-11 é gravada', (r.status_code, bool(d11)), (302, True))
    conferir('  ligada ao código do catálogo', d11 and d11.diagnosis_code_id, alvo.id)
    antigo = DiagnosisCode.objects.get(release=r10, code='G35')
    r = med.post(reverse('clinical:add-diagnosis', args=[aberto.id]), {
        'diagnosis_code_id': str(antigo.id), 'code_snapshot': 'G35',
        'description_snapshot': antigo.description, 'certainty': DiagnosisCertainty.CONFIRMED, 'rank': 2,
    })
    conferir('a da CID-10, sem o campo novo, continua sendo gravada',
             (r.status_code, EncounterDiagnosis.objects.filter(encounter=aberto, code_snapshot='G35').count()),
             (302, 1))
    r = med.post(reverse('clinical:add-diagnosis', args=[aberto.id]), {
        'code_snapshot': '8A00.0&XK9J', 'description_snapshot': 'Doença de Parkinson, à direita',
        'certainty': DiagnosisCertainty.SUSPECTED, 'rank': 3, 'cid_sistema': 'CID11',
    })
    conferir('o agrupamento escrito à mão é aceito',
             EncounterDiagnosis.objects.filter(encounter=aberto, code_snapshot='8A00.0&XK9J').count(), 1)
    r = med.post(reverse('clinical:add-diagnosis', args=[aberto.id]), {
        'code_snapshot': '8A40', 'description_snapshot': 'x', 'certainty': DiagnosisCertainty.SUSPECTED,
        'rank': 4, 'cid_sistema': 'CID12',
    })
    conferir('classificação inventada é recusada, sem gravar',
             EncounterDiagnosis.objects.filter(encounter=aberto).count(), 3)
    tela = med.get(reverse('clinical:detail', args=[aberto.id])).content.decode()
    conferir('a tela marca a hipótese da CID-11', tela.count('>CID-11</span>'), 2)
    molde = Template('{% load nd %}{% if codigo|nd_cid11 %}onze{% else %}nao{% endif %}')
    conferir('o filtro da tela: 8A40, G35 e vazio',
             [molde.render(Context({'codigo': c})) for c in ('8A40', 'G35', '')], ['onze', 'nao', 'nao'])

    estruturado = atendimento(paciente('ROTEIRO CID ONZE ESTRUTURADO'), kind=EncounterKind.STRUCTURED)
    tela = med.get(reverse('clinical:detail', args=[estruturado.id])).content.decode()
    conferir('o estruturado também oferece a classificação', 'name="cid_sistema"' in tela, True)
    EncounterDiagnosis.objects.create(
        tenant=tenant, encounter=estruturado, code_snapshot='8A80.0',
        description_snapshot='Enxaqueca sem aura', certainty=DiagnosisCertainty.CONFIRMED, rank=1,
    )
    tela = med.get(reverse('clinical:detail', args=[estruturado.id])).content.decode()
    conferir('  e marca a hipótese da CID-11', '>CID-11</span>' in tela, True)
    resumo = med.get(reverse('clinical:summary', args=[aberto.id])).content.decode()
    conferir('o resumo do caso diz qual é da CID-11', resumo.count('(CID-11)'), 2)
    conferir('  e não marca a da CID-10', 'G35' in resumo, True)
    js = open('static/clinical/cid.js', encoding='utf-8').read()
    conferir('o autocomplete manda o sistema escolhido', "'&sistema=' + sistema()" in js, True)
    conferir('  e não usa confirm/alert', 'window.confirm' in js or 'alert(' in js, False)

    print('\n6. Pacientes por diagnóstico: as duas classificações')
    ctx = AccessContext(
        user_id=medico.user_id, tenant_id=tenant.id, membership_id=medico.id,
        permissions=frozenset(medico.roles or []), request_id=None,
        tenant_status=tenant.status, capabilities=frozenset(),
    )

    def achou(termo):
        pagina = buscar(ctx, termo)
        return set() if pagina is None else {linha['patient'].id for linha in pagina.object_list}

    so11 = paciente('ROTEIRO CID SO ONZE')
    a = atendimento(so11, status=EncounterStatus.FINALIZED)
    EncounterDiagnosis.objects.create(
        tenant=tenant, encounter=a, code_snapshot='8A40.0',
        description_snapshot='Esclerose múltipla recorrente-remitente',
        certainty=DiagnosisCertainty.CONFIRMED, rank=1,
    )
    so10 = paciente('ROTEIRO CID SO DEZ')
    a = atendimento(so10, status=EncounterStatus.FINALIZED)
    EncounterDiagnosis.objects.create(
        tenant=tenant, encounter=a, code_snapshot='G35', description_snapshot='Esclerose múltipla',
        certainty=DiagnosisCertainty.CONFIRMED, rank=1,
    )
    conferir('pelo código da CID-11', so11.id in achou('8A40'), True)
    conferir('  sem o ponto', so11.id in achou('8A400'), True)
    conferir('  e não traz quem só tem a CID-10', so10.id in achou('8A40'), False)
    conferir('pelo código da CID-10, como antes', (so10.id in achou('G35'), so11.id in achou('G35')), (True, False))
    nome = achou('esclerose multipla')
    conferir('pelo nome, acha os dois', (so10.id in nome, so11.id in nome), (True, True))
    conferir('a tela explica as duas',
             'da CID-10 ou da CID-11' in med.get(reverse('clinical:por-cid')).content.decode(), True)
    conferir('a secretária continua sem abrir', sec.get(reverse('clinical:por-cid')).status_code in (403, 404), True)
    conferir('outra clínica não abre o atendimento',
             cliente(medico_b, tenant_b).get(reverse('clinical:detail', args=[aberto.id])).status_code, 404)

    print('\n7. O documento imprime o rótulo do código')
    emissao = open('modelos/emissao.py', encoding='utf-8').read()
    pedido = open('documents/pdf/exam_request.py', encoding='utf-8').read()
    conferir('a conduta e o PDF do pedido não fixam mais "CID-10:"',
             ("f'CID-10:" in emissao, 'CID-10:</b>' in pedido), (False, False))
    conferir('  e usam o rótulo lido do código',
             (emissao.count('rotulo_da_hipotese(cid)'), pedido.count('rotulo_da_hipotese(cid)')), (2, 1))

    print('\n8. A leitura da planilha é estrita')
    import openpyxl

    def planilha(linhas, cabecalho=('Code', 'TitleEN', 'Title', 'ClassKind', 'ChapterNo')):
        livro = openpyxl.Workbook()
        folha = livro.active
        folha.append(list(cabecalho))
        for linha in linhas:
            folha.append(list(linha))
        caminho = Path(tempfile.mkdtemp()) / 'cid11.xlsx'
        livro.save(caminho)
        return caminho

    def recusa(caminho, **kw):
        antes = (CatalogRelease.objects.count(), DiagnosisCode.objects.count())
        try:
            cid.importar(caminho, 'roteiro-cid11', '', **kw)
        except cid.PlanilhaInvalida as exc:
            return str(exc)[:45], (CatalogRelease.objects.count(), DiagnosisCode.objects.count()) == antes
        return 'gravou', False

    boa = [('8A00', 'Parkinsonism', '- Parkinsonismo', 'category', '08')]
    conferir('planilha curta não grava', recusa(planilha(boa))[1], True)
    conferir('  e diz por quê', 'trouxe 1 códigos' in recusa(planilha(boa))[0], True)
    sem_titulo = recusa(planilha([('8A00', 'x', 'category', '08')], ('Code', 'TitleEN', 'ClassKind', 'ChapterNo')))
    conferir('coluna faltando não grava, e a recusa diz qual',
             (sem_titulo[0].startswith('Colunas ausentes'), sem_titulo[1]), (True, True))
    conferir('código fora da forma não grava',
             recusa(planilha(boa + [('G40', 'Epilepsy', '- Epilepsia', 'category', '08')]))[1], True)
    conferir('código repetido não grava', recusa(planilha(boa + boa))[1], True)
    try:
        cid.importar(planilha(boa), 'roteiro-cid11')
        desfecho = 'gravou'
    except cid.PlanilhaInvalida as exc:
        desfecho = str(exc)
    conferir('outro arquivo no lugar da planilha conferida: SHA-256 diferente', 'SHA-256 diferente' in desfecho, True)
    linhas = cid.ler_planilha(cid.CID11_ARQUIVO)
    conferir('a planilha da OMS relida dá o mesmo número da carga', len(linhas), total11)
    conferir('nenhuma release de roteiro ficou',
             CatalogRelease.objects.filter(version='roteiro-cid11').count(), 0)

    print('\n9. A subida não sobrepõe nem derruba')
    conferir('com a CID-11 ativa, a subida não faz nada', cid.ensure_cid11(), None)
    conferir('  e continua havendo uma ativa só',
             CatalogRelease.objects.filter(system='CID11', status=CatalogReleaseStatus.ACTIVE).count(), 1)
    conferir('planilha ausente não levanta', cid.ensure_cid11(caminho=Path('/nao/existe.xlsx')), None)
    conferir('a CID-10 não foi tocada',
             (active_release('CID10').id, active_release('CID10').diagnosis_codes.count()),
             (r10.id, r10.diagnosis_codes.count()))
    runtime = open('ops/runtime.py', encoding='utf-8').read()
    conferir('a subida chama as duas cargas',
             ('ensure_cid10()' in runtime, 'ensure_cid11()' in runtime), (True, True))
finally:
    EncounterDiagnosis.objects.filter(encounter_id__in=criados['atendimentos']).delete()
    Encounter.objects.filter(id__in=criados['atendimentos']).delete()
    n = Patient.objects.filter(id__in=criados['pacientes']).delete()[0]
    CatalogRelease.objects.filter(version='roteiro-cid11').delete()
    print(f'\n  limpeza: {n} objeto(s) de paciente removidos')

if falhas:
    print(f'\n{len(falhas)} falha(s):')
    for f in falhas:
        print('FALHA: ' + f)
    raise SystemExit(1)
print('\nTudo certo.')
