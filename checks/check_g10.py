"""G10: portal de solicitacoes do paciente.

O que este teste tenta quebrar, e nao o que ele tenta confirmar:
identificacao como oraculo de CPF, sessao valendo entre clinicas, pedido
virando documento sem medico, e pedido de uma clinica visivel na outra.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from datetime import date

from django.contrib.messages import get_messages
from django.utils import timezone

from accounts.models import User
from clinical.models import Encounter
from documents import portal
from documents.models import DocumentRequest, DocumentRequestStatus, MedicalDocument
from patients.models import Patient, PatientStatus
from tenancy.models import ClinicProfile, Tenant

failures = []
criados = []
tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
perfil = ClinicProfile.objects.get_or_create(tenant=tenant)[0]
perfil_b = ClinicProfile.objects.get_or_create(tenant=tenant_b)[0]
estado = (perfil.patient_portal_enabled, perfil.patient_portal_notice,
          perfil_b.patient_portal_enabled)


def note(r):
    itens = [str(m) for m in get_messages(r.wsgi_request)]
    return itens[-1] if itens else '(sem aviso)'


def client_for(email, t=tenant):
    c = Client()
    c.force_login(User.objects.get(email=email))
    s = c.session
    s['tenant_id'] = str(t.id)
    s.save()
    return c


# Paciente com CPF e data conhecidos, so para o teste.
# `exclude(cpf='')` sozinho NAO tira os nulos (NULL <> '' e NULL em SQL), e
# a ordem sem `order_by` varia entre execucoes: numa rodada isto pegava a
# Ana, na seguinte um cadastro sem CPF nem data.
paciente = (
    Patient.objects
    .filter(tenant=tenant, status=PatientStatus.ACTIVE,
            cpf__isnull=False, birth_date__isnull=False)
    .exclude(cpf='').order_by('created_at').first()
)
if paciente is None:
    print('sem paciente com CPF na clinica A')
    raise SystemExit(1)
CPF = paciente.cpf
NASC = paciente.birth_date
print('paciente de teste:', paciente.full_name, '| nasc', NASC)

print('=== 1. portal desligado responde como inexistente ===')
perfil.patient_portal_enabled = False
perfil.save()
anon = Client()
code = anon.get(f'/solicitacoes/{tenant.slug}/').status_code
print('  GET com portal desligado -> HTTP', code)
if code != 404:
    failures.append(f'portal desligado respondeu {code}, deveria ser 404')

print('=== 2. o dono publica o portal pela tela da clinica ===')
owner = client_for('doctor-a@demo.neurodoc.local')
r = owner.post('/app/org/clinica/portal/', {
    'patient_portal_enabled': '1',
    'patient_portal_notice': 'Pedidos respondidos em ate 3 dias uteis.',
    # O prazo de retorno entrou no mesmo formulario: a tela o renderiza
    # sempre, e um POST sem ele e formulario invalido -- o portal nao
    # chegava a ser publicado, e as doze secoes seguintes viam 404.
    'patient_portal_max_months': '18',
}, follow=True)
perfil.refresh_from_db()
print('  ->', note(r))
print('  publicado:', perfil.patient_portal_enabled)
if not perfil.patient_portal_enabled:
    failures.append('o dono nao conseguiu publicar o portal')

print('=== 3. secretaria NAO publica nem despublica ===')
secretaria = client_for('secretary-a@demo.neurodoc.local')
code = secretaria.post('/app/org/clinica/portal/', {'patient_portal_enabled': ''}).status_code
perfil.refresh_from_db()
print('  secretaria -> HTTP', code, '| ainda publicado:', perfil.patient_portal_enabled)
if code != 404 or not perfil.patient_portal_enabled:
    failures.append('a secretaria alterou a publicacao do portal')

print('=== 4. o formulario abre e mostra o aviso da clinica ===')
anon = Client()
r = anon.get(f'/solicitacoes/{tenant.slug}/')
corpo = r.content.decode()
print('  HTTP', r.status_code, '| mostra o aviso:', '3 dias uteis' in corpo)
print('  exige aceite de privacidade:', 'privacy_ack' in corpo)
if r.status_code != 200 or 'privacy_ack' not in corpo:
    failures.append('o formulario nao abriu com o aceite de privacidade')

print('=== 5. sem aceite, nao passa ===')
r = anon.post(f'/solicitacoes/{tenant.slug}/', {
    'cpf': CPF, 'birth_date': NASC.isoformat(),
})
print('  HTTP', r.status_code, '|', 'confirme a ciência' in r.content.decode())
if r.status_code != 400:
    failures.append('passou da identificacao sem aceite de privacidade')

from django.core.cache import cache


def zera_balde():
    """O balde e por IP, e aqui todos os clientes sao 127.0.0.1.

    Sem isto um passo herda o bloqueio provocado pelo anterior — e pior,
    a verificacao de "resposta identica" passaria trivialmente, com os
    tres casos respondendo 429 em vez do 404 que se quer comparar.
    """
    cache.delete('portal:lookup:127.0.0.1')
    cache.delete('portal:submit:127.0.0.1')


print('=== 6. a resposta e a MESMA para CPF de fora e data errada ===')
zera_balde()
respostas = set()
for rotulo, cpf, nasc in [
    ('cpf inexistente', '52998224725', NASC.isoformat()),
    ('data errada', CPF, '1900-01-01'),
    ('cpf invalido', '11111111111', NASC.isoformat()),
]:
    c = Client()
    r = c.post(f'/solicitacoes/{tenant.slug}/', {
        'cpf': cpf, 'birth_date': nasc, 'privacy_ack': '1'})
    corpo = r.content.decode()
    # A pagina inteira varia (csrf), entao compara so a mensagem de erro.
    import re
    msg = re.search(r'alert-warning[^>]*>(.*?)</div>', corpo, re.S)
    respostas.add((r.status_code, (msg.group(1).strip() if msg else '')[:80]))
    print(f'  {rotulo:17} -> HTTP {r.status_code}')
print('  respostas distintas:', len(respostas))
if len(respostas) != 1:
    failures.append('a identificacao distingue os casos e vira oraculo de CPF')
# Sem isto, tres respostas 429 iguais passariam como se fossem a
# uniformidade que se quer provar.
if {code for code, _ in respostas} != {404}:
    failures.append('os tres casos nao chegaram a ser avaliados (nao vieram 404)')

print('=== 7. limite de tentativas por IP ===')
zera_balde()
c = Client()
codes = []
for _ in range(portal.LOOKUP_MAX_ATTEMPTS + 3):
    codes.append(c.post(f'/solicitacoes/{tenant.slug}/', {
        'cpf': '52998224725', 'birth_date': '1980-01-01', 'privacy_ack': '1'}).status_code)
print('  codigos:', codes)
print('  passou de 404 para 429 no meio:', 404 in codes and 429 in codes)
if 429 not in codes:
    failures.append('varredura de CPF nao foi barrada (nenhum 429)')
if 404 not in codes:
    failures.append('o balde ja estava cheio — o teste nao provou o bloqueio')
zera_balde()

print('=== 8. identificacao correta abre a etapa 2 ===')
# O portal so aceita quem consultou dentro da janela de retorno
# (`documents/portal_retorno.py`). A precondicao e garantida aqui, e nao
# herdada do `seed_demo`: um banco semeado ha mais de seis meses faria
# este roteiro acusar o portal de nao abrir a etapa 2 quando o que houve
# foi a regra funcionando.
from datetime import timedelta as _timedelta

from clinical.models import Encounter as _Encounter

_ultimo = _Encounter.objects.filter(tenant=tenant, patient=paciente).order_by('-occurred_at').first()
if _ultimo is not None:
    _ultimo.occurred_at = timezone.now() - _timedelta(days=20)
    _ultimo.save(update_fields=['occurred_at'])
    print(f'  ultima consulta ajustada para ha 20 dias ({_ultimo.occurred_at:%d/%m/%Y})')
paciente_c = Client()
r = paciente_c.post(f'/solicitacoes/{tenant.slug}/', {
    'cpf': CPF, 'birth_date': NASC.isoformat(), 'privacy_ack': '1'}, follow=True)
corpo = r.content.decode()
print('  chegou em solicitar:', '/solicitar/' in r.request['PATH_INFO'] or 'O que você precisa' in corpo)
if 'O que você precisa' not in corpo:
    failures.append('a identificacao correta nao abriu a etapa 2')

print('=== 9. a sessao NAO vale no portal da outra clinica ===')
perfil_b.patient_portal_enabled = True
perfil_b.save()
r = paciente_c.get(f'/solicitacoes/{tenant_b.slug}/solicitar/', follow=True)
corpo = r.content.decode()
print('  clinica B pediu identificacao de novo:', 'Data de nascimento' in corpo)
if 'Data de nascimento' not in corpo:
    failures.append('a sessao de uma clinica valeu no portal da outra')

print('=== 10. envio sem conteudo e recusado ===')
r = paciente_c.post(f'/solicitacoes/{tenant.slug}/solicitar/', {
    'kind': 'prescription_simple', 'requester': 'self',
    'med_name': '', 'med_dose': '', 'med_usage': ''})
print('  HTTP', r.status_code, '|', 'Adicione ao menos uma medicação' in r.content.decode())
if r.status_code != 400:
    failures.append('aceitou pedido de receita sem medicacao')

print('=== 11. medicacao pela metade e recusada ===')
r = paciente_c.post(f'/solicitacoes/{tenant.slug}/solicitar/', {
    'kind': 'prescription_simple', 'requester': 'self',
    'med_name': 'Levetiracetam', 'med_dose': '', 'med_usage': '1 cp'})
print('  HTTP', r.status_code)
if r.status_code != 400:
    failures.append('aceitou medicacao sem a dose')

print('=== 12. pedido completo entra na fila ===')
r = paciente_c.post(f'/solicitacoes/{tenant.slug}/solicitar/', {
    'kind': 'prescription_simple', 'requester': 'other',
    'requester_name': 'Filha do paciente (teste G10)',
    'med_name': ['Levetiracetam', 'Acido valproico'],
    'med_dose': ['500 mg', '250 mg'],
    'med_usage': ['1 cp 12/12h', '1 cp a noite'],
}, follow=True)
pedido = DocumentRequest.objects.filter(
    tenant=tenant, requester_name__startswith='Filha do paciente').order_by('-created_at').first()
criados.append(pedido)
print('  pedido criado:', pedido is not None)
if pedido is None:
    failures.append('o pedido nao foi registrado')
    raise SystemExit(1)
print('  medicacoes:', len(pedido.payload.get('medicacoes', [])))
print('  aceite gravado:', pedido.privacy_ack_at is not None, '| versao:', pedido.privacy_notice_version)
print('  IP protegido (nao e o IP em claro):', pedido.origin_ip_protected[:12], '...')
if len(pedido.payload.get('medicacoes', [])) != 2:
    failures.append('as medicacoes nao foram gravadas')
if not pedido.privacy_notice_version:
    failures.append('o pedido nao gravou a versao do aviso aceito')
if '127.0.0.1' in pedido.origin_ip_protected:
    failures.append('o IP de origem foi gravado em claro')

print('=== 13. a sessao e encerrada apos enviar ===')
r = paciente_c.get(f'/solicitacoes/{tenant.slug}/solicitar/', follow=True)
print('  pede identificacao de novo:', 'Data de nascimento' in r.content.decode())
if 'Data de nascimento' not in r.content.decode():
    failures.append('a sessao continuou aberta depois do envio')

print('=== 14. a fila e clinica: secretaria nao ve ===')
for label, c, esperado in [('medico', owner, 200), ('secretaria', secretaria, 404)]:
    code = c.get('/app/documents/solicitacoes/').status_code
    print(f'  {label:11} -> {code}')
    if code != esperado:
        failures.append(f'{label} na fila: esperava {esperado}, veio {code}')

print('=== 15. a fila mostra o pedido e o alerta de procedencia ===')
corpo = owner.get(f'/app/documents/solicitacoes/{pedido.id}/').content.decode()
print('  mostra a medicacao:', 'Levetiracetam' in corpo)
print('  avisa quem escreveu o texto:', 'escrito pelo paciente' in corpo)
print('  marca que quem pediu foi terceiro:', 'terceiro' in corpo)
if 'escrito pelo paciente' not in corpo:
    failures.append('a tela nao avisa que o texto e do paciente')

print('=== 16. o pedido de uma clinica NAO aparece na outra ===')
owner_b = client_for('doctor-a@demo.neurodoc.local', tenant_b)
corpo_b = owner_b.get('/app/documents/solicitacoes/').content.decode()
print('  clinica B ve o pedido da A:', 'Filha do paciente' in corpo_b)
code = owner_b.get(f'/app/documents/solicitacoes/{pedido.id}/').status_code
print('  abrir o pedido da A pela clinica B -> HTTP', code)
if 'Filha do paciente' in corpo_b or code != 404:
    failures.append('o pedido vazou entre organizacoes')

print('=== 17. recusa sem motivo e barrada ===')
r = owner.post(f'/app/documents/solicitacoes/{pedido.id}/recusar/', {'note': ''}, follow=True)
pedido.refresh_from_db()
print('  ->', note(r), '| status:', pedido.status)
if pedido.status != DocumentRequestStatus.RECEIVED:
    failures.append('recusou o pedido sem motivo registrado')

print('=== 18. o pedido vira RASCUNHO, nunca documento emitido ===')
antes = MedicalDocument.objects.filter(tenant=tenant).count()
r = owner.post(f'/app/documents/solicitacoes/{pedido.id}/rascunho/', {}, follow=True)
pedido.refresh_from_db()
print('  ->', note(r)[:90])
doc = pedido.resulting_document
print('  documento gerado:', doc.document_number or '(sem numero)', '| status:', doc.status if doc else None)
criados.append(doc)
if doc is None:
    failures.append('o rascunho nao foi criado')
elif doc.status != 'draft':
    failures.append(f'o pedido gerou documento com status {doc.status}, nao rascunho')
elif doc.document_number:
    failures.append('o rascunho ja nasceu com numero de documento emitido')
if pedido.status != DocumentRequestStatus.FULFILLED:
    failures.append('o pedido nao foi marcado como atendido')

print('=== 19. o texto do paciente foi para o rascunho, sem invencao ===')
texto = (doc.content_snapshot or {}).get('prescription_text', '')
print('  texto:', repr(texto[:70]))
print('  contem as duas medicacoes:', 'Levetiracetam' in texto and 'Acido valproico' in texto)
if 'Levetiracetam' not in texto:
    failures.append('o texto do paciente nao chegou ao rascunho')

print('=== 20. o mesmo pedido nao pode ser atendido duas vezes ===')
antes = MedicalDocument.objects.filter(tenant=tenant).count()
r = owner.post(f'/app/documents/solicitacoes/{pedido.id}/rascunho/', {}, follow=True)
depois = MedicalDocument.objects.filter(tenant=tenant).count()
print('  ->', note(r)[:70], '| documentos antes/depois:', antes, depois)
if depois != antes:
    failures.append('atender de novo gerou um segundo documento')

print('=== 21. despublicar nao apaga o que ja chegou ===')
perfil.patient_portal_enabled = False
perfil.save()
print('  pedido continua na base:', DocumentRequest.objects.filter(id=pedido.id).exists())
print('  portal fechado -> HTTP', Client().get(f'/solicitacoes/{tenant.slug}/').status_code)
if not DocumentRequest.objects.filter(id=pedido.id).exists():
    failures.append('despublicar apagou pedidos ja recebidos')

# limpeza
for obj in criados:
    if obj is None:
        continue
    if isinstance(obj, DocumentRequest):
        DocumentRequest.objects.filter(id=obj.id).update(resulting_document=None)
for obj in criados:
    if isinstance(obj, MedicalDocument):
        from documents.models import Attachment
        anexos = [obj.pdf_attachment_id, obj.signed_pdf_attachment_id]
        MedicalDocument.objects.filter(id=obj.id).delete()
        Attachment.objects.filter(id__in=[a for a in anexos if a]).delete()
DocumentRequest.objects.filter(id__in=[o.id for o in criados if isinstance(o, DocumentRequest)]).delete()
# Os atendimentos que este roteiro abriu -- e o que estiver pendurado neles.
#
# A limpeza era um `delete()` direto, e bastava uma execucao interrompida
# para o atendimento sobrar no banco. Um roteiro posterior que pegue "o
# primeiro atendimento do paciente" acrescenta um achado de exame nele, e a
# partir dai a limpeza deste falha para sempre com `ProtectedError` --
# porque `ExaminationFinding.encounter` e PROTECT. O roteiro passa a
# quebrar por causa do proprio lixo, e a mensagem nao diz isso.
abertos = Encounter.objects.filter(
    tenant=tenant, chief_complaint__startswith='Registro aberto a partir de pedido')
from clinical.models import ExaminationFinding

ExaminationFinding.objects.filter(encounter__in=abertos).delete()
abertos.delete()
perfil.patient_portal_enabled, perfil.patient_portal_notice = estado[0], estado[1]
perfil.save()
perfil_b.patient_portal_enabled = estado[2]
perfil_b.save()

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: G10 completo.')
