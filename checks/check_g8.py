"""G8: compactacao trimestral e guarda legal de 20 anos.

O que se prova aqui, acima de tudo: o arquivo comprimido devolve os MESMOS
bytes. Documento assinado com um byte diferente e a assinatura deixa de
conferir.
"""
import hashlib
from pathlib import Path

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
from clinical.models import Encounter, EncounterStatus
from documents import archive, retention
from documents.models import Attachment, AttachmentScanStatus, MedicalDocument, MedicalDocumentKind
from documents.storage import is_compressed, local_path, read_bytes, store_generated_attachment
from patients.models import Patient
from tenancy.models import Membership, Tenant

failures = []
criados = []
tenant = Tenant.objects.get(slug='demo-clinica-a')
doctor_m = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant=tenant)
paciente = Patient.objects.filter(tenant=tenant).exclude(street='').first()

print('=== 1. arquivo grande o bastante e antigo o bastante ===')
# PDF sintetico de ~200 KB, com texto repetido para comprimir de verdade.
corpo = (b'%PDF-1.4\n' + b'% conteudo de teste do arquivo morto. ' * 5000 + b'\n%%EOF\n')
sha_original = hashlib.sha256(corpo).hexdigest()
att = store_generated_attachment(
    tenant, paciente, doctor_m.user, corpo, 'arquivo_morto_teste.pdf')
criados.append(att)
print('  tamanho:', len(corpo), 'bytes | sha256:', sha_original[:16])

# Envelhece o registro para ele entrar na janela de compactacao.
antigo = timezone.now() - timezone.timedelta(days=archive.COMPACT_AFTER_DAYS + 10)
Attachment.objects.filter(id=att.id).update(created_at=antigo)
att.refresh_from_db()

elegiveis = list(archive.eligible(tenant_id=tenant.id).values_list('id', flat=True))
print('  entra na lista de elegiveis:', att.id in elegiveis)
if att.id not in elegiveis:
    failures.append('o anexo antigo nao entrou na lista de elegiveis')

print('=== 2. simulacao nao toca no disco ===')
caminho_antes = att.storage_key
resumo = archive.compact(tenant_id=tenant.id, dry_run=True)
att.refresh_from_db()
print('  considerados:', resumo['considerados'], '| compactados:', resumo['compactados'])
print('  caminho inalterado:', att.storage_key == caminho_antes)
print('  arquivo ainda no disco:', Path(caminho_antes).is_file())
if att.storage_key != caminho_antes or not Path(caminho_antes).is_file():
    failures.append('a simulacao alterou o disco')
if resumo['compactados'] != 0:
    failures.append('a simulacao relatou arquivos compactados')

print('=== 3. compactacao real ===')
resumo = archive.compact(tenant_id=tenant.id, dry_run=False)
att.refresh_from_db()
economia = resumo['antes'] - resumo['depois']
print('  compactados:', resumo['compactados'])
print(f'  {resumo["antes"]} -> {resumo["depois"]} bytes '
      f'({economia / resumo["antes"] * 100:.0f}% de economia)' if resumo['antes'] else '')
print('  caminho agora:', Path(att.storage_key).name)
print('  original removido:', not Path(caminho_antes).is_file())
if not is_compressed(att):
    failures.append('o anexo nao ficou marcado como comprimido')
if Path(caminho_antes).is_file():
    failures.append('o arquivo original nao foi removido')
if resumo['depois'] >= resumo['antes']:
    failures.append('a compactacao nao reduziu o tamanho')

print('=== 4. OS BYTES VOLTAM IDENTICOS ===')
lidos = read_bytes(att)
sha_lido = hashlib.sha256(lidos).hexdigest()
print('  sha256 original:', sha_original[:32])
print('  sha256 lido    :', sha_lido[:32])
print('  identicos:', lidos == corpo)
if lidos != corpo:
    failures.append('OS BYTES MUDARAM na ida e volta da compactacao')
if sha_lido != att.sha256:
    failures.append('o sha256 lido nao confere com o registrado')

print('=== 5. leitura por caminho tambem funciona ===')
with local_path(att) as caminho:
    do_caminho = Path(caminho).read_bytes()
    print('  caminho temporario:', caminho != att.storage_key)
    print('  bytes identicos:', do_caminho == corpo)
    temporario = caminho
if do_caminho != corpo:
    failures.append('a leitura por caminho devolveu bytes diferentes')
print('  temporario removido apos o bloco:', not Path(temporario).exists())
if Path(temporario).exists():
    failures.append('o arquivo temporario nao foi removido')

print('=== 6. o download continua funcionando ===')
c = Client()
c.force_login(User.objects.get(email='doctor-a@demo.neurodoc.local'))
s = c.session
s['tenant_id'] = str(tenant.id)
s.save()
r = c.get(f'/app/documents/{att.id}/download/')
print('  HTTP:', r.status_code, '| bytes identicos:', r.content == corpo)
if r.status_code != 200 or r.content != corpo:
    failures.append('o download de um anexo comprimido nao devolveu o original')

print('=== 7. compactar duas vezes nao faz nada ===')
antes_key = att.storage_key
resumo = archive.compact(tenant_id=tenant.id, dry_run=False)
att.refresh_from_db()
print('  compactados na segunda passada:', resumo['compactados'])
print('  caminho inalterado:', att.storage_key == antes_key)
if att.storage_key != antes_key:
    failures.append('a segunda passada alterou um arquivo ja comprimido')

print('=== 8. arquivo divergente do sha registrado e recusado ===')
corpo2 = b'%PDF-1.4\n' + b'outro conteudo para o teste de divergencia. ' * 5000
att2 = store_generated_attachment(
    tenant, paciente, doctor_m.user, corpo2, 'divergente_teste.pdf')
criados.append(att2)
Attachment.objects.filter(id=att2.id).update(created_at=antigo, sha256='0' * 64)
att2.refresh_from_db()
caminho2 = att2.storage_key
try:
    archive.compact_attachment(att2)
    failures.append('compactou um arquivo que nao confere com o sha registrado')
    print('  ACEITOU (nao deveria)')
except archive.CompactionFailed as exc:
    print('  ->', str(exc)[:80])
att2.refresh_from_db()
print('  original intacto:', Path(caminho2).is_file() and att2.storage_key == caminho2)
if not Path(caminho2).is_file():
    failures.append('a falha de conferencia apagou o original')
if list(Path(caminho2).parent.glob('*.incoming')):
    failures.append('sobrou arquivo temporario apos a falha')

print('=== 9. guarda legal: 20 anos do ULTIMO registro ===')
print('  RETENTION_YEARS:', retention.RETENTION_YEARS)
if retention.RETENTION_YEARS != 20:
    failures.append(f'a guarda legal esta em {retention.RETENTION_YEARS} anos, esperava 20')

ultimo = retention.last_record_at(paciente)
expira = retention.retention_expires_at(paciente)
print('  ultimo registro:', ultimo.strftime('%d/%m/%Y') if ultimo else None)
print('  guarda ate:', expira.strftime('%d/%m/%Y') if expira else None)
if expira is None:
    failures.append('paciente com registros nao tem prazo de guarda calculado')
else:
    anos = (expira - ultimo).days / 365
    print('  intervalo em anos:', round(anos))
    if round(anos) != 20:
        failures.append(f'o prazo calculado deu {anos:.1f} anos')

print('=== 10. o anexo recente empurra o prazo ===')
# O anexo criado agora e o registro mais novo; o prazo tem de contar dele.
recente = store_generated_attachment(
    tenant, paciente, doctor_m.user, b'%PDF-1.4 recente\n', 'recente_teste.pdf')
criados.append(recente)
novo_ultimo = retention.last_record_at(paciente)
print('  ultimo registro agora:', novo_ultimo.strftime('%d/%m/%Y %H:%M'))
if novo_ultimo < recente.created_at:
    failures.append('o anexo mais recente nao foi considerado no ultimo registro')

print('=== 11. nada esta vencido, e a lista de expurgo esta vazia ===')
candidatos = retention.purge_candidates(tenant.id)
print('  prontuarios com prazo vencido:', len(candidatos))
if candidatos:
    failures.append(f'{len(candidatos)} prontuario(s) apareceram como vencidos hoje')

print('=== 12. cadastro sem registro clinico nao tem prazo ===')
vazio = Patient.objects.create(
    tenant=tenant, full_name='Paciente Sem Registro G8',
    birth_date_unknown_reason='teste')
criados.append(vazio)
print('  ultimo registro:', retention.last_record_at(vazio))
print('  prazo:', retention.retention_expires_at(vazio))
if retention.retention_expires_at(vazio) is not None:
    failures.append('cadastro sem prontuario recebeu prazo de guarda')

print('=== 13. relatorio de retencao roda ===')
linhas = retention.retention_report(tenant.id)
com_prazo = [x for x in linhas if x['expires_at']]
print('  prontuarios no relatorio:', len(linhas), '| com prazo:', len(com_prazo))
if not linhas:
    failures.append('o relatorio de retencao veio vazio')

# limpeza
for obj in criados:
    if isinstance(obj, Attachment):
        if obj.storage_key:
            Path(obj.storage_key).unlink(missing_ok=True)
        Attachment.objects.filter(id=obj.id).delete()
    elif isinstance(obj, Patient):
        Patient.objects.filter(id=obj.id).delete()

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: G8 completo.')
