"""Formulario de documento medico: campos por tipo, e retificacao dos 4 tipos."""
import re

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import Encounter, EncounterStatus
from documents import issuance
from documents.models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from patients.models import Patient
from tenancy.models import Membership, Tenant

TENANT = 'demo-clinica-a'
failures = []

tenant = Tenant.objects.get(slug=TENANT)
doctor_m = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant=tenant)
def paciente_com_endereco(tenant):
    """Um paciente com endereco preenchido, criando a condicao se preciso.

    O roteiro precisa de endereco porque o documento medico o imprime no
    cabecalho. `seed_demo` **nao** preenche endereco, entao procurar um e
    usar o resultado era depender de sobra de outra execucao: num banco
    recem-semeado a busca devolvia `None`, e o `Encounter.objects.create`
    abaixo estourava com "patient_id nao pode ser nulo" -- um erro que
    aponta para o encontro quando a causa e o paciente, tres linhas antes.

    Preparar a condicao aqui e o certo: isto e montagem, nao afirmacao. O
    que o roteiro julga vem depois, e continua intacto.
    """
    achado = Patient.objects.filter(tenant=tenant).exclude(street='').first()
    if achado is not None:
        return achado
    achado = Patient.objects.filter(tenant=tenant).order_by('record_number').first()
    if achado is None:
        raise SystemExit('FALHA: a clinica de demonstracao esta sem pacientes; rode seed_demo.')
    achado.street, achado.number = 'Rua das Acácias', '100'
    achado.district, achado.city, achado.state = 'Centro', 'São Paulo', 'SP'
    achado.save(update_fields=['street', 'number', 'district', 'city', 'state'])
    return achado


patient = paciente_com_endereco(tenant)
encounter = Encounter.objects.filter(tenant=tenant, patient=patient).first()
if encounter is None:
    encounter = Encounter.objects.create(
        tenant=tenant, patient=patient, physician_membership=doctor_m,
        occurred_at=timezone.now(), status=EncounterStatus.DRAFT, chief_complaint='x')

c = Client()
c.force_login(User.objects.get(email='doctor-a@demo.neurodoc.local'))
s = c.session
s['tenant_id'] = str(tenant.id)
s.save()

created = []

print('=== 1. o formulario agrupa os campos por tipo ===')
r = c.get(f'/app/documents/encounters/{encounter.id}/medical/new/')
body = r.content.decode()
grupos = re.findall(r'data-nd-doc-kind="([a-z_]+)"', body)
print('  grupos declarados:', grupos)
for esperado in ['prescription', 'report', 'request', 'referral']:
    if esperado not in grupos:
        failures.append(f'grupo {esperado} ausente do formulario')
print('  carrega o JS que esconde os demais:', 'medical_form.js' in body)
if 'medical_form.js' not in body:
    failures.append('o formulario nao carrega o script que filtra os campos')
print('  formato da receita esta no grupo da receita:',
      body.index('prescription_format') > body.index('data-nd-doc-kind="prescription"')
      and body.index('prescription_format') < body.index('data-nd-doc-kind="report"'))

print('=== 2. campo obrigatorio do tipo escolhido e apontado no campo ===')
r = c.post(f'/app/documents/encounters/{encounter.id}/medical/new/', {
    'kind': 'prescription', 'prescription_text': '', 'prescription_format': 'simple',
})
body = r.content.decode()
print('  recusou:', r.status_code == 200 and 'obrigatório para o tipo escolhido' in body)
if 'obrigatório para o tipo escolhido' not in body:
    failures.append('campo faltando nao foi apontado no proprio campo')

print('=== 3. cria e retifica os quatro tipos ===')
CASOS = {
    'prescription': ({'prescription_text': 'Dipirona 500mg', 'special_instructions': '',
                      'prescription_format': 'simple'},
                     {'prescription_text': 'Dipirona 1g', 'special_instructions': '',
                      'prescription_format': 'special_control'}),
    'report': ({'report_text': 'Relatorio v1'}, {'report_text': 'Relatorio v2'}),
    'request': ({'requested_procedure': 'RM cranio', 'justification': 'Cefaleia'},
                {'requested_procedure': 'TC cranio', 'justification': 'Cefaleia aguda'}),
    'referral': ({'referral_specialty': 'Neurocirurgia', 'reason': 'Avaliacao'},
                 {'referral_specialty': 'Neurocirurgia', 'reason': 'Avaliacao urgente'}),
}

for kind, (inicial, corrigido) in CASOS.items():
    doc = issuance.create_draft(tenant, patient, encounter, doctor_m, doctor_m.user_id,
                                kind, inicial)
    created.append(doc)
    # emite (sem assinar de verdade — o que interessa aqui e o fluxo de retificacao)
    doc.status = MedicalDocumentStatus.ISSUED
    doc.document_number = f'X-{kind[:3].upper()}-001'
    doc.issued_at = timezone.now()
    doc.save()

    payload = dict(corrigido)
    payload['kind'] = kind
    payload['correction_reason'] = f'teste de retificacao de {kind}'
    r = c.post(f'/app/documents/medical/{doc.id}/correction/', payload, follow=False)
    nova = MedicalDocument.objects.filter(replaces_document=doc).first()
    if nova:
        created.append(nova)
    ok = nova is not None and nova.version == 2
    print(f'  {kind:14} HTTP={r.status_code} retificado={ok}')
    if not ok:
        failures.append(f'retificacao de {kind} falhou (HTTP {r.status_code})')
        continue
    # o conteudo corrigido tem de estar na nova versao
    for campo, valor in corrigido.items():
        if nova.content_snapshot.get(campo) != valor:
            failures.append(
                f'{kind}: campo {campo} nao foi corrigido '
                f'({nova.content_snapshot.get(campo)!r} != {valor!r})')
    # o motivo tem de estar na auditoria, e nao no conteudo
    evento = AuditEvent.objects.filter(
        action='documents.medicaldocument_corrected', object_id=nova.id).first()
    if evento is None or f'retificacao de {kind}' not in (evento.purpose or ''):
        failures.append(f'{kind}: motivo da correcao nao foi registrado na auditoria')
    if 'correction_reason' in nova.content_snapshot:
        failures.append(f'{kind}: motivo da correcao vazou para o conteudo do documento')

print('=== 4. o motivo da correcao NAO vira o motivo do encaminhamento ===')
enc = [d for d in created if d.kind == 'referral' and d.version == 2]
if enc:
    print('  motivo do encaminhamento:', enc[0].content_snapshot.get('reason'))
    if 'retificacao' in (enc[0].content_snapshot.get('reason') or ''):
        failures.append('o motivo da correcao sobrescreveu o motivo do encaminhamento')

print('=== 5. o tipo nao muda numa retificacao ===')
alvo = [d for d in created if d.kind == 'report' and d.version == 1][0]
r = c.post(f'/app/documents/medical/{alvo.id}/correction/', {
    'kind': 'prescription', 'report_text': 'tentando trocar o tipo',
    'correction_reason': 'teste',
}, follow=False)
novas = MedicalDocument.objects.filter(replaces_document=alvo)
created.extend(novas)
tipos = {d.kind for d in novas}
print('  HTTP:', r.status_code, '| tipos gerados:', tipos)
if tipos and tipos != {'report'}:
    failures.append(f'a retificacao trocou o tipo do documento: {tipos}')

# limpeza
def _remover_anexos_dos_documentos(ids):
    """Tira do banco e do disco os PDFs dos documentos que o roteiro criou.

    Apagar so o `MedicalDocument` deixava o `Attachment` do rascunho (e o
    do assinado, quando havia) orfao no banco e o arquivo no volume de
    midia. Somados os cinco roteiros que emitem documento, eram vinte e
    dois anexos por rodada acumulando na clinica de demonstracao.

    A segunda varredura, por PDF **sem dono**, existe porque nem todo
    documento chega aqui pela lista: um que o proprio roteiro ja apagou,
    ou que foi substituido no meio do caminho, sai da lista e levaria o
    anexo junto para o esquecimento. O nome do arquivo de documento carrega
    o id dele (`<tipo>_<uuid>_draft.pdf`), e um desses que nenhum
    `MedicalDocument` reivindica nao e de ninguem.
    """
    import re
    from pathlib import Path

    from documents.models import Attachment, MedicalDocument

    anexos = []
    for atual in MedicalDocument.objects.filter(id__in=ids).values(
        'pdf_attachment_id', 'signed_pdf_attachment_id',
    ):
        anexos += [v for v in atual.values() if v]
    MedicalDocument.objects.filter(id__in=ids).delete()

    padrao = re.compile(r'^[a-z_]+_[0-9a-f-]{36}_(draft|signed|papel)\.pdf$')
    com_dono = set(
        MedicalDocument.objects.values_list('pdf_attachment_id', flat=True)
    ) | set(
        MedicalDocument.objects.values_list('signed_pdf_attachment_id', flat=True)
    )
    for att in Attachment.objects.exclude(id__in=[i for i in com_dono if i]):
        if padrao.match(att.original_name or ''):
            anexos.append(att.id)

    if not anexos:
        return 0
    for att in Attachment.objects.filter(id__in=anexos):
        if att.storage_key:
            Path(att.storage_key).unlink(missing_ok=True)
    apagados, _ = Attachment.objects.filter(id__in=anexos).delete()
    return apagados


for d in created:
    MedicalDocument.objects.filter(id=d.id).update(replaces_document=None)
print('anexos dos documentos do roteiro removidos:',
      _remover_anexos_dos_documentos([d.id for d in created]))

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: formulario por tipo e retificacao dos quatro tipos.')
