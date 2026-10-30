"""A receita eletrônica do SNCR a partir do atendimento.

Tenta quebrar. As perguntas são:

- a Conduta dos **dois** tipos de atendimento mostra "Receita controlada
  (SNCR)" com a integração ligada, e **não** mostra com ela desligada?
- o link abre o formulário já em "Receita" e no formato eletrônico — e o
  mesmo pedido, com a integração desligada ou com um formato inventado,
  abre na receita simples, sem erro?
- o formulário mostra os números livres **do médico logado**, por tipo, e
  aponta o pedido de bloco quando falta?
- a secretária não vê o botão?
- o pedido de bloco (`/app/sncr/pedir/`) responde com a página que abre o
  Gov.br por link, e nunca com redirecionamento para fora — a CSP de
  produção (`form-action 'self'`) recusaria o salto no navegador?
"""
from django.conf import settings as dj_settings
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import PhysicianProfile, User
from clinical.models import Encounter, EncounterKind, EncounterStatus
from patients.models import Patient, RegistrationStage
from sncr.models import BlocoNumeracao, Configuracao, NumeroSncr, PedidoNumeracao
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


tenant = Tenant.objects.get(slug='demo-clinica-a')
user = User.objects.get(email='doctor-a@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
vinculo = Membership.objects.get(tenant=tenant, user=user)
medico = PhysicianProfile.objects.get(user=user)
config = Configuracao.carregar()
original = (config.ativo, config.ambiente, config.cnpj_mantenedora)
CNPJ = '11222333000181'
criados = {'pacientes': [], 'atendimentos': [], 'pedidos': []}


def cliente(u=user):
    c = Client()
    c.force_login(u)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def ligar(ativo):
    config.ativo, config.cnpj_mantenedora, config.ambiente = ativo, CNPJ, 'homologacao'
    config.save()


try:
    pac = Patient.objects.create(
        tenant=tenant, full_name='PACIENTE RECEITA PRONTUARIO', registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['pacientes'].append(pac.id)
    atendimentos = {}
    for kind in (EncounterKind.STRUCTURED, EncounterKind.FREE_TEXT):
        e = Encounter.objects.create(
            tenant=tenant, patient=pac, physician_membership=vinculo, occurred_at=timezone.now(),
            status=EncounterStatus.IN_PROGRESS, kind=kind, chief_complaint='Insônia.',
            free_text='Texto livre.' if kind == EncounterKind.FREE_TEXT else '',
        )
        criados['atendimentos'].append(e.id)
        atendimentos[kind] = e

    print('=== 1. o botão na Conduta ===')
    ligar(True)
    for kind, e in atendimentos.items():
        html = cliente().get(f'/app/clinical/{e.id}/').content.decode()
        conferir(f'ligada: {kind} mostra "Receita controlada (SNCR)"',
                 'data-nd-receita-sncr' in html and f'/medical/new/?receita=sncr_rce' in html)
    html = cliente(secretaria).get(f'/app/clinical/{atendimentos[EncounterKind.STRUCTURED].id}/')
    conferir('a secretária não vê o botão', b'data-nd-receita-sncr' not in html.content, html.status_code)
    ligar(False)
    for kind, e in atendimentos.items():
        html = cliente().get(f'/app/clinical/{e.id}/').content.decode()
        conferir(f'desligada: {kind} sem o botão', 'data-nd-receita-sncr' not in html)

    print('=== 2. o formulário já no formato ===')
    e = atendimentos[EncounterKind.STRUCTURED]
    url = f'/app/documents/encounters/{e.id}/medical/new/'
    ligar(True)
    html = cliente().get(url, {'receita': 'sncr_rce'}).content.decode()
    conferir('abre em Receita', 'value="prescription" selected' in html)
    conferir('e no formato eletrônico da RCE', 'value="sncr_rce" selected' in html)
    html = cliente().get(url, {'receita': 'inventado'}).content.decode()
    conferir('formato inventado cai na receita simples', 'value="simple" selected' in html)
    ligar(False)
    html = cliente().get(url, {'receita': 'sncr_rce'}).content.decode()
    conferir('desligada: o mesmo link abre na receita simples, sem a opção eletrônica',
             'value="simple" selected' in html and 'value="sncr_rce"' not in html)
    html = cliente().get(url).content.decode()
    conferir('sem o parâmetro, nada vem escolhido além do padrão', 'value="prescription" selected' not in html)

    print('=== 3. o saldo do médico na tela ===')
    ligar(True)
    html = cliente().get(url, {'receita': 'sncr_rce'}).content.decode()
    conferir('o saldo aparece, por tipo', 'data-nd-sncr-saldo' in html and 'RCE 0' in html and 'RET 0' in html)
    conferir('sem número, aponta o pedido de bloco', 'Pedir bloco com o Gov.br' in html)

    print('=== 4. o pedido de bloco não redireciona para fora ===')
    r = cliente().post('/app/sncr/pedir/RCE/')
    pedido = PedidoNumeracao.objects.filter(medico=medico).order_by('-created_at').first()
    if pedido:
        criados['pedidos'].append(pedido.id)
    location = r.get('Location', '')
    conferir('nenhum redirecionamento para a Anvisa na resposta do POST',
             'anvisa.gov.br' not in location, location)
    if r.status_code == 200:
        conferir('a página traz o link do Gov.br', b'data-nd-sncr-govbr' in r.content)
    else:
        # Médico da demonstração com algum impedimento (CRM não validado):
        # a recusa volta ao painel, o que também não sai do site.
        conferir('a recusa volta ao painel', r.status_code == 302 and location.endswith('/app/sncr/'), location)

    print('=== 5. uso contínuo e a busca do medicamento ===')
    from catalogs.models import MedicationProduct
    from sncr import receita as sncr_receita

    html = cliente().get(url, {'receita': 'sncr_rce'}).content.decode()
    conferir('cada medicamento tem a marca de uso contínuo', 'name="item1_uso_continuo"' in html
             and 'name="item3_uso_continuo"' in html)
    conferir('o nome busca na CMED, preenchendo a mesma linha',
             'data-nd-med-grupo' in html and 'name="item1_nome"' in html and 'data-nd-med-url=' in html
             and 'data-nd-med-forma=' in html and 'data-nd-med-nome="substancia"' in html)
    itens = sncr_receita.itens_do_formulario({
        'item1_nome': 'Levetiracetam', 'item1_concentracao': '500 mg', 'item1_forma': 'comprimido',
        'item1_quantidade': '60 comprimidos', 'item1_posologia': '1 comprimido 12/12h', 'item1_uso_continuo': True,
        'item2_nome': 'Sertralina', 'item2_concentracao': '50 mg', 'item2_forma': 'comprimido',
        'item2_quantidade': '30 comprimidos', 'item2_posologia': '1 comprimido ao dia',
    })
    conferir('o uso contínuo é lido por item', [i['uso_continuo'] for i in itens] == [True, False])
    pac.cpf, pac.street, pac.city, pac.state = '52998224725', 'Rua A, 1', 'São Paulo', 'SP'
    pac.save(update_fields=['cpf', 'street', 'city', 'state'])
    conteudo = sncr_receita.preparar({
        'prescription_format': 'sncr_rce', 'item1_nome': 'Levetiracetam', 'item1_concentracao': '500 mg',
        'item1_forma': 'comprimido', 'item1_quantidade': '60 comprimidos', 'item1_posologia': '1 cp 12/12h',
        'item1_uso_continuo': True,
    }, pac, confirmada=True)
    quantidade = conteudo['itens'][0]['quantidade']
    conferir('a quantidade sai com o extenso e o uso contínuo, sem perder o número',
             quantidade == '60 (sessenta) comprimidos — uso contínuo', quantidade)
    try:
        sncr_receita.preparar({
            'prescription_format': 'sncr_rce', 'item1_nome': 'Levetiracetam', 'item1_concentracao': '500 mg',
            'item1_forma': 'comprimido', 'item1_quantidade': 'uso contínuo', 'item1_posologia': '1 cp 12/12h',
            'item1_uso_continuo': True,
        }, pac, confirmada=True)
        conferir('uso contínuo sem número é recusado (a norma exige a quantidade)', False)
    except sncr_receita.ReceitaInvalida:
        conferir('uso contínuo sem número é recusado (a norma exige a quantidade)', True)
    amostras = {
        'COM REV CT BL AL PLAS PVC X 30': 'comprimido revestido',
        '500 MG COM REV LIB PROL CT BL X 30': 'comprimido revestido de liberação prolongada',
        '2 MG COM CT BL AL PLAS INC X 30': 'comprimido',
        '100 MG CAP DURA CT BL X 30': 'cápsula dura',
        '2,5 MG/ML SOL OR CT FR GOT X 20 ML': 'solução oral',
        'CT BL AL PLAS X 30': '',
    }
    erradas = {a: MedicationProduct(presentation=a).forma_farmaceutica() for a in amostras
               if MedicationProduct(presentation=a).forma_farmaceutica() != amostras[a]}
    conferir('a forma farmacêutica sai por extenso das abreviaturas da CMED', not erradas, erradas)
    from django.urls import reverse

    resultados = cliente().get(reverse('catalogs:medicamento-search'), {'q': 'sertralina'}).json()['results']
    conferir('a busca da CMED devolve substância, dosagem e forma',
             bool(resultados) and all(k in resultados[0] for k in ('substancia', 'dosagem', 'forma'))
             and any(r['forma'] for r in resultados), resultados[:1])
finally:
    print('=== limpeza ===')
    NumeroSncr.objects.filter(bloco__pedido_id__in=criados['pedidos']).delete()
    BlocoNumeracao.objects.filter(pedido_id__in=criados['pedidos']).delete()
    PedidoNumeracao.objects.filter(id__in=criados['pedidos']).delete()
    Encounter.objects.filter(id__in=criados['atendimentos']).delete()
    Patient.objects.filter(id__in=criados['pacientes']).delete()
    config.ativo, config.ambiente, config.cnpj_mantenedora = original
    config.save()
    print('  atendimentos, paciente e pedidos do roteiro removidos; configuração restaurada')

if falhas:
    print('\nFALHAS:')
    for f in falhas:
        print(f'  - {f}')
    raise SystemExit(1)
print('\nOK: receita do SNCR no atendimento — botão na Conduta só ligada, formulário no formato,')
print('    saldo do médico à vista e o pedido de bloco sem redirecionar para fora.')
