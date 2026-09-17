"""Habitos, confirmacao por e-mail, pedido editavel, receita e superadmin.

O que este teste tenta quebrar: habito sumindo do resumo, botao de e-mail
escondido de paciente que tem e-mail, medico emitindo o texto do paciente
sem revisao registrada, secretaria alcancando o console da instalacao, e
superusuario sem MFA entrando nele.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from datetime import date

from django.contrib.messages import get_messages
from django.template import Context, Template
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import Encounter, EncounterKind
from communications.services import confirmation_contacts
from documents.models import (
    DocumentRequest, DocumentRequestKind, DocumentRequestStatus, MedicalDocument,
)
from patients.models import Patient, PatientContact
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
falhas = []
criados = {'contatos': [], 'pedidos': [], 'documentos': []}


def note(r):
    itens = [str(m) for m in get_messages(r.wsgi_request)]
    return itens[-1] if itens else '(sem aviso)'


def client_for(email, slug=TENANT):
    user = User.objects.get(email=email)
    membership = Membership.objects.get(user=user, tenant__slug=slug)
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(membership.tenant_id)
    s.save()
    return c, membership


dono, m_dono = client_for('doctor-a@demo.neurodoc.local')
secretaria, m_sec = client_for('secretary-a@demo.neurodoc.local')

print('=' * 66)
print('3. HABITOS E VICIOS NO PRONTUARIO')
print('=' * 66)

# Habitos e vicios sao campos do prontuario **estruturado**: o atendimento
# em texto livre nao os tem, de proposito. Sem filtrar por tipo, este
# roteiro escolhia o primeiro atendimento aberto que aparecesse e acusava
# ausencia do campo quando calhava de ser um texto livre — falha do sorteio,
# nao do sistema. A ordem tambem e explicita: `first()` sem `order_by` deixa
# a escolha por conta do plano de consulta do Postgres.
enc = (
    Encounter.objects
    .filter(tenant__slug=TENANT, kind=EncounterKind.STRUCTURED)
    .exclude(status='finalized')
    .order_by('occurred_at')
    .first()
)
if enc is None:
    print('  (sem atendimento aberto na demonstracao)')
else:
    r = dono.get(f'/app/clinical/{enc.id}/')
    tem_campo = 'habits_history' in r.content.decode()
    print('  campo na aba Historia ->', 'presente' if tem_campo else 'AUSENTE')
    if not tem_campo:
        falhas.append('o campo de habitos nao aparece na aba Historia')

    # Comparar o hash antes e depois do POST falharia na segunda rodada, em
    # que o campo ja tem o mesmo texto e nada muda. Compara-se o hash com o
    # campo vazio contra o mesmo objeto com o campo preenchido — que e a
    # pergunta de fato: `habits_history` participa do hash?
    original_habitos = enc.habits_history
    enc.habits_history = ''
    hash_sem = enc.compute_content_hash()
    enc.habits_history = 'valor qualquer para o hash'
    hash_com = enc.compute_content_hash()
    enc.habits_history = original_habitos

    r = dono.post(f'/app/clinical/{enc.id}/autosave/', {
        'chief_complaint': enc.chief_complaint, 'hpi': enc.hpi,
        'personal_history': enc.personal_history, 'family_history': enc.family_history,
        'habits_history': 'Tabagismo 20 macos/ano. Alcool social. Sono fragmentado.',
        'consanguinity_state': enc.consanguinity_state,
        'consanguinity_details': enc.consanguinity_details,
        'plan_text': enc.plan_text, 'row_version': enc.row_version,
    }, follow=True)
    enc.refresh_from_db()
    gravado = 'Tabagismo' in (enc.habits_history or '')
    print('  gravar habitos ->', 'gravado' if gravado else f'NAO GRAVOU ({note(r)})')
    if not gravado:
        falhas.append('o campo de habitos nao gravou')

    # O habito precisa entrar no hash: campo fora dele muda sem que a
    # versao do atendimento mude, e a assinatura do resumo deixa de cobri-lo.
    if hash_sem == hash_com:
        falhas.append('habits_history nao entra no hash de conteudo do atendimento')
    else:
        print('  entra no hash do atendimento -> sim')

    r = dono.get(f'/app/clinical/{enc.id}/resumo/')
    if r.status_code == 200:
        no_resumo = 'Habitos' in r.content.decode() or 'Hábitos' in r.content.decode()
        print('  aparece no resumo imprimivel ->', 'sim' if no_resumo else 'NAO')
        if not no_resumo:
            falhas.append('habitos nao aparece no resumo imprimivel')

print()
print('=' * 66)
print('4. CONFIRMACAO POR E-MAIL NA AGENDA')
print('=' * 66)

# Um paciente com telefone no primeiro contato e e-mail no segundo. Era
# exatamente esta a forma que escondia o botao de e-mail.
paciente = Patient.objects.filter(tenant__slug=TENANT, status='active').first()
if paciente is None:
    print('  (sem paciente)')
else:
    PatientContact.objects.filter(patient=paciente).update(email='')
    c1 = PatientContact.objects.filter(patient=paciente).first()
    if c1 is None:
        c1 = PatientContact.objects.create(
            tenant=paciente.tenant, patient=paciente, name='Titular',
            relationship='proprio', phone='11988887777',
        )
        criados['contatos'].append(c1.id)
    else:
        c1.phone = c1.phone or '11988887777'
        c1.email = ''
        c1.save()
    c2 = PatientContact.objects.create(
        tenant=paciente.tenant, patient=paciente, name='Filha',
        relationship='filha', email='filha@exemplo.invalido',
    )
    criados['contatos'].append(c2.id)

    paciente.refresh_from_db()
    render = Template(
        '{% load nd %}{% with c=p|nd_confirmation_contacts %}{{ c.phone }}|{{ c.email }}{% endwith %}'
    ).render(Context({'p': paciente}))
    telefone, _, email = render.partition('|')
    print(f'  filtro devolve -> telefone="{telefone}" email="{email}"')
    if not email:
        falhas.append('o filtro nao achou o e-mail do segundo contato — o botao ficaria escondido')
    if not telefone:
        falhas.append('o filtro perdeu o telefone do primeiro contato')

    # A tela tem de concordar com o servidor: o que o botao mostra e o que
    # `confirmation_contacts` aceitaria enviar.
    from communications.models import DeliveryChannel

    # `confirmation_contacts` so olha `appointment.patient.contacts`; um
    # objeto minimo basta e evita depender de haver horario marcado.
    class _Fake:
        patient = paciente

    servidor_email = bool(confirmation_contacts(_Fake(), DeliveryChannel.EMAIL))
    print('  servidor aceitaria enviar e-mail ->', servidor_email)
    if bool(email) != servidor_email:
        falhas.append('a tela e o servidor discordam sobre haver e-mail utilizavel')

print()
print('=' * 66)
print('5. PEDIDO DO PORTAL EDITAVEL ANTES DE VIRAR RASCUNHO')
print('=' * 66)

alvo = Patient.objects.filter(tenant__slug=TENANT, status='active').first()
pedido = DocumentRequest.objects.create(
    tenant=alvo.tenant, patient=alvo, kind=DocumentRequestKind.PRESCRIPTION_SIMPLE,
    requester_name=alvo.full_name, requester_is_patient=True,
    payload={'medicacoes': [{'nome': 'Keppra 250mg', 'dose': '1cp', 'uso': '2x/dia'}]},
    status=DocumentRequestStatus.RECEIVED,
    privacy_ack_at=timezone.now(), privacy_notice_version='2026-09-v1',
)
criados['pedidos'].append(pedido.id)

r = dono.get(f'/app/documents/solicitacoes/{pedido.id}/')
corpo = r.content.decode()
tem_form = 'prescription_text' in corpo and 'conteudo_revisado' in corpo
tem_texto = 'Keppra' in corpo
print('  formulario editavel na tela ->', 'presente' if tem_form else 'AUSENTE')
print('  ja vem com o texto do paciente ->', 'sim' if tem_texto else 'NAO')
if not tem_form:
    falhas.append('a tela do pedido nao traz o conteudo editavel')
if not tem_texto:
    falhas.append('o conteudo editavel nao veio preenchido com o pedido')

r = dono.post(f'/app/documents/solicitacoes/{pedido.id}/rascunho/', {
    'conteudo_revisado': '1',
    'prescription_text': 'Levetiracetam 500 mg — 1 comprimido de 12/12h, uso continuo.',
    'special_instructions': 'Retorno em 60 dias com hemograma.',
    'prescription_format': 'simple',
}, follow=True)
pedido.refresh_from_db()
doc = pedido.resulting_document
print('  gerar rascunho revisado ->', note(r))
if doc is None:
    falhas.append('o rascunho nao foi criado')
else:
    criados['documentos'].append(doc.id)
    texto = (doc.content_snapshot or {}).get('prescription_text', '')
    print('  conteudo do rascunho ->', texto[:60])
    if 'Levetiracetam' not in texto:
        falhas.append('o rascunho saiu com o texto do paciente, e nao com o texto revisado')
    if 'Keppra' in texto:
        falhas.append('o texto original do paciente sobreviveu no rascunho revisado')
    # O pedido do paciente nao muda: e o registro do que foi pedido.
    if pedido.payload.get('medicacoes', [{}])[0].get('nome') != 'Keppra 250mg':
        falhas.append('o pedido do paciente foi reescrito — ele e a prova do que foi pedido')
    else:
        print('  pedido do paciente preservado -> sim')
    evento = AuditEvent.objects.filter(
        action='documents.portal_request_drafted', object_id=pedido.id,
    ).order_by('-created_at').first()
    editado = (evento.integrity_metadata or {}).get('edited_by_physician') if evento else None
    print('  auditoria registra revisao ->', editado)
    if editado is not True:
        falhas.append('a auditoria nao registrou que o medico reescreveu o conteudo')

print()
print('=' * 66)
print('6. RECEITA DE CONTROLE ESPECIAL: COMPRADOR E FORNECEDOR')
print('=' * 66)

from documents.pdf import render_medical_document_pdf

alvo_end = Patient.objects.filter(
    tenant__slug=TENANT, status='active',
).exclude(street='').exclude(city='').first()
if alvo_end is None:
    print('  (nenhum paciente com endereco completo — controle especial exige)')
else:
    enc2 = Encounter.objects.filter(tenant__slug=TENANT, patient=alvo_end).first()
    if enc2 is None:
        enc2 = Encounter.objects.filter(tenant__slug=TENANT).first()
    from documents import issuance
    from tenancy.models import Tenant

    medico = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local',
                                    tenant__slug=TENANT)
    try:
        doc2 = issuance.create_draft(
            Tenant.objects.get(slug=TENANT), alvo_end, enc2, medico, medico.user_id,
            'prescription',
            {'prescription_text': 'Clonazepam 2 mg — 1 comprimido a noite.',
             'special_instructions': '', 'prescription_format': 'special_control'},
        )
        criados['documentos'].append(doc2.id)
        pdf = render_medical_document_pdf(doc2)
        from pypdf import PdfReader
        import io as _io

        leitor = PdfReader(_io.BytesIO(pdf))
        paginas = [p.extract_text() for p in leitor.pages]
        print('  paginas ->', len(paginas))
        if len(paginas) != 2:
            falhas.append(f'controle especial saiu com {len(paginas)} pagina(s), esperado 2')
        for i, texto in enumerate(paginas, 1):
            tem_comprador = 'COMPRADOR' in texto.upper()
            tem_fornecedor = 'FORNECEDOR' in texto.upper()
            campos = all(x in texto for x in ['Nome:', 'Ident.:', 'End.:', 'Cidade:', 'Telefone:'])
            print(f'  via {i}: comprador={tem_comprador} fornecedor={tem_fornecedor} campos={campos}')
            if not (tem_comprador and tem_fornecedor and campos):
                falhas.append(f'a via {i} nao trouxe o quadro completo de identificacao')
    except Exception as exc:                                # noqa: BLE001
        print('  ERRO ao gerar:', exc)
        falhas.append(f'a receita de controle especial nao pode ser gerada: {exc}')

    # A receita simples NAO leva o quadro: ele e do controle especial.
    doc3 = issuance.create_draft(
        Tenant.objects.get(slug=TENANT), alvo_end, enc2, medico, medico.user_id,
        'prescription',
        {'prescription_text': 'Dipirona 500 mg se dor.', 'special_instructions': '',
         'prescription_format': 'simple'},
    )
    criados['documentos'].append(doc3.id)
    from pypdf import PdfReader
    import io as _io

    texto3 = PdfReader(_io.BytesIO(render_medical_document_pdf(doc3))).pages[0].extract_text()
    tem = 'COMPRADOR' in texto3.upper()
    print('  receita simples tem o quadro ->', tem, '(esperado False)')
    if tem:
        falhas.append('a receita simples saiu com o quadro do controle especial')

print()
print('=' * 66)
print('7. CONSOLE DA INSTALACAO')
print('=' * 66)

for rotulo, c in [('dono da clinica', dono), ('secretaria', secretaria)]:
    r = c.get('/instalacao/')
    print(f'  {rotulo:18} abre console -> {r.status_code}')
    if r.status_code != 404:
        falhas.append(f'{rotulo} alcancou o console da instalacao (HTTP {r.status_code})')

# Superusuario sem MFA verificada tambem nao entra.
def superadmin_descartavel():
    """Um superadministrador **do roteiro**, nunca a conta de uma pessoa.

    `force_login` grava `last_login`, e `last_login` entra no hash de
    `default_token_generator`: logar numa conta invalida o link de
    definicao de senha pendente dela. Pegar "o primeiro superusuario"
    funcionava enquanto havia contas de teste no banco; num banco limpo,
    a unica conta com `is_superuser` e a de quem opera o sistema -- e o
    roteiro passava a derrubar o link dessa pessoa.
    """
    from accounts.models import User as _User
    from django.utils import timezone as _tz

    conta, criada = _User.objects.get_or_create(
        email='check-superadmin@example.invalid',
        defaults={'is_active': True, 'is_staff': True, 'is_superuser': True},
    )
    if criada:
        conta.set_password('CheckS3nha!2026')
    conta.is_staff = True
    conta.is_superuser = True
    conta.is_active = True
    conta.email_verified_at = conta.email_verified_at or _tz.now()
    conta.save()
    return conta


su = superadmin_descartavel()
if su is not None:
    cs = Client()
    cs.force_login(su)
    for rota in ['/instalacao/', '/instalacao/usuarios/', '/instalacao/auditoria/',
                 '/instalacao/organizacoes/']:
        r = cs.get(rota)
        print(f'  superusuario SEM MFA em {rota} -> {r.status_code}')
        if r.status_code != 404:
            falhas.append(f'superusuario sem MFA entrou em {rota} (HTTP {r.status_code})')

# ---------------------------------------------------------------- limpeza
MedicalDocument.objects.filter(id__in=criados['documentos']).delete()
DocumentRequest.objects.filter(id__in=criados['pedidos']).delete()
PatientContact.objects.filter(id__in=criados['contatos']).delete()
print()
print('limpeza:', len(criados['documentos']), 'documentos,', len(criados['pedidos']),
      'pedidos,', len(criados['contatos']), 'contatos removidos')

print('---')
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK.')
