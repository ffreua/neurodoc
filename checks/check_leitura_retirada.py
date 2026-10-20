"""A leitura de laudo pela IA saiu por inteiro, e o resto da IA ficou.

Na 1.18 a leitura do PDF anexado ao resultado de exame foi retirada: em uso
real falhou mais do que leu (de cinco pedidos em produção, três falharam e
nenhum valor chegou ao prontuário). Retirar um recurso é onde se quebra o
que fica, por isso o roteiro tenta as duas coisas:

- **que ela saiu de todos os caminhos**: a caixa do formulário, o botão, as
  rotas `ler-laudo/` e `rascunho/`, as tarefas no grafo, a criação do job, e
  os dois caminhos por onde um job antigo ainda chegaria ao worker — a
  mensagem velha na fila (`prepare_document_and_run`) e a retomada de job
  parado. Esses dois **cancelam com a explicação**, em vez de falhar no
  provedor ou ficar "na fila" por um dia;
- **que o resto da IA ficou**: resumo, apoio diagnóstico e relatório no
  grafo, o registro do exame com PDF funcionando sem a IA, a aba de exames
  abrindo.

As duas varreduras do antigo `check_leitura_laudo` que valem para toda
tarefa de IA vieram junto: todo esquema herda a normalização de forma, e
todo prompt declara o tipo de cada campo.
"""
import re
import uuid

from django.conf import settings as dj_settings
from django.test import Client
from django.urls import NoReverseMatch, reverse

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from ai import services, tasks
from ai.graphs import STRUCTURED_OUTPUT_TASKS, TASKS
from ai.models import AIArtifact, AIJob, AIJobKind, AIJobStatus, TIPOS_APOSENTADOS
from ai.schemas import ArtifactModel
from clinical.forms import ExamResultForm
from clinical.models import Encounter, EncounterStatus, ExamResult
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        falhas.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = next((
    m for m in Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).select_related('user') if m.can_practice_clinically()
), None)
aberto = Encounter.objects.filter(
    tenant=tenant, physician_membership=medico,
).exclude(status=EncounterStatus.FINALIZED).first() if medico else None
if medico is None or aberto is None:
    print('PULADO: demonstração sem médico verificado e atendimento aberto')
    raise SystemExit(0)

ctx = AccessContext(
    user_id=medico.user_id, tenant_id=tenant.id, membership_id=medico.id,
    permissions=frozenset(), request_id=uuid.uuid4(),
)
cliente = Client()
cliente.force_login(medico.user)
sessao = cliente.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()
criados_jobs, criados_exames = [], []

print('=== 1. a tela não oferece mais a leitura ===')
confere('run_extraction' not in ExamResultForm.base_fields,
        'o formulário do exame não tem a caixa "Pedir à IA para ler o laudo"')
for nome in ('clinical:extract-exam-result', 'clinical:review-exam-draft'):
    try:
        reverse(nome, args=[aberto.id, uuid.uuid4()])
        existe = True
    except NoReverseMatch:
        existe = False
    confere(not existe, f'a rota {nome} não existe mais')
r = cliente.get(reverse('clinical:detail', args=[aberto.id]))
html = r.content.decode('utf-8', 'replace')
confere(r.status_code == 200, 'o atendimento abre', r.status_code)
for texto in ('Ler laudo com IA', 'Pedir à IA para ler', 'ler-laudo', 'Ler de novo'):
    confere(texto not in html, f'o atendimento não mostra "{texto}"')
confere('Resultados de exames' in html or 'tab-exames' in html, 'a aba de exames continua lá')
for url in (f'/app/clinical/{aberto.id}/exames/{uuid.uuid4()}/ler-laudo/',
            f'/app/clinical/{aberto.id}/exames/{uuid.uuid4()}/rascunho/'):
    confere(cliente.post(url).status_code == 404, f'POST antigo em {url.rsplit("/", 2)[-2]}/ dá 404')

print('=== 2. registrar exame com PDF segue funcionando, sem IA ===')
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch

pdf = SimpleUploadedFile('laudo-roteiro.pdf', b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n',
                         content_type='application/pdf')
antes_jobs = AIJob.objects.filter(tenant=tenant).count()
with patch('documents.tasks.scan_attachment.delay'):
    r = cliente.post(reverse('clinical:add-exam-result', args=[aberto.id]), {
        'category': 'laboratory', 'name': 'Hemograma do roteiro de retirada',
        'report_file': pdf, 'run_extraction': 'on',
    })
exame = ExamResult.objects.filter(encounter=aberto, name='Hemograma do roteiro de retirada').first()
if exame:
    criados_exames.append(exame)
confere(r.status_code in (302, 303) and exame is not None, 'o exame com PDF foi registrado',
        r.status_code)
confere(exame is not None and exame.attachment_id is not None, 'o PDF ficou anexado ao exame')
confere(AIJob.objects.filter(tenant=tenant).count() == antes_jobs,
        'nenhum job de IA nasceu, nem com "run_extraction" forjado no POST')

print('=== 3. a IA não cria nem roda mais a leitura ===')
for kind in TIPOS_APOSENTADOS:
    confere(kind not in TASKS, f'{kind} saiu do grafo')
confere(not STRUCTURED_OUTPUT_TASKS, 'nenhuma tarefa pede esquema estruturado ao provedor')
for kind in (AIJobKind.ENCOUNTER_SUMMARY, AIJobKind.DIAGNOSTIC_SUPPORT, AIJobKind.PATIENT_REPORT):
    confere(kind in TASKS, f'{kind} continua no grafo')
try:
    services.create_job(ctx, AIJobKind.LAB_EXTRACTION, 'roteiro', patient_id=aberto.patient_id,
                        encounter_id=aberto.id, target_ref={'exam_result_id': str(uuid.uuid4())})
    recusou = False
except ValueError:
    recusou = True
confere(recusou, 'create_job recusa o tipo aposentado')


def job_antigo(chave):
    job = AIJob.objects.create(
        tenant=tenant, user=medico.user, membership=medico,
        patient=aberto.patient, encounter=aberto, kind=AIJobKind.LAB_EXTRACTION,
        source_version=0, purpose='roteiro', status=AIJobStatus.QUEUED,
        limits={}, idempotency_key=f'roteiro-retirada-{chave}-{uuid.uuid4()}',
    )
    criados_jobs.append(job)
    return job


j1 = job_antigo('worker')
tasks.run_ai_job(str(j1.id))
j1.refresh_from_db()
confere(j1.status == AIJobStatus.CANCELLED and 'retirada' in j1.status_detail,
        'job antigo que chega ao worker é cancelado com a explicação', f'{j1.status} {j1.status_detail}')

j2 = job_antigo('fila')
tasks.prepare_document_and_run(str(j2.id))
j2.refresh_from_db()
confere(j2.status == AIJobStatus.CANCELLED, 'a mensagem velha da fila (prepare_document_and_run) cancela',
        j2.status)

from django.utils import timezone
j3 = job_antigo('parado')
AIJob.objects.filter(id=j3.id).update(updated_at=timezone.now() - timezone.timedelta(hours=2))
with patch('ai.tasks.run_ai_job.delay') as publicado:
    tasks.retomar_jobs_parados()
j3.refresh_from_db()
confere(j3.status == AIJobStatus.CANCELLED and not any(
    str(j3.id) in str(c) for c in publicado.call_args_list),
    'a retomada de job parado cancela a leitura em vez de republicar', j3.status)

print('=== 4. todo esquema de saída herda a normalização ===')
import ai.schemas as _schemas
from pydantic import BaseModel as _BaseModel

orfaos = [
    nome for nome, obj in vars(_schemas).items()
    if isinstance(obj, type) and issubclass(obj, _BaseModel)
    and obj not in (_BaseModel, ArtifactModel)
    and obj.__module__ == 'ai.schemas'
    and not issubclass(obj, ArtifactModel)
]
confere(not orfaos, 'nenhum esquema de ai.schemas ficou fora de ArtifactModel', ', '.join(orfaos))
for nome in ('LabExtractionArtifact', 'ReportTranscriptionArtifact', 'ExtractedAnalyte'):
    confere(not hasattr(_schemas, nome), f'{nome} saiu dos esquemas')

print('=== 5. os prompts declaram o tipo de cada campo ===')
# O prompt sem tipo foi metade da causa do defeito de 05/10/2026, e a
# varredura vale para toda tarefa que restou.
for kind, (template, esquema) in sorted(TASKS.items()):
    trecho = template.split('Campos:', 1)[-1]
    campos_citados = set(re.findall(r'"([a-z_]+)"', trecho))
    sem_tipo = sorted(
        nome for nome in campos_citados
        if nome in esquema.model_fields and not re.search(rf'"{nome}"\s*\(', trecho)
    )
    confere(not sem_tipo, f'{kind}: todo campo citado traz o tipo entre parênteses',
            ', '.join(sem_tipo))

AIArtifact.objects.filter(job__in=criados_jobs).delete()
AIJob.objects.filter(id__in=[j.id for j in criados_jobs]).delete()
for exame in criados_exames:
    anexo = exame.attachment
    exame.delete()
    if anexo is not None:
        anexo.delete()

print('---')
if falhas:
    for falha in falhas:
        print('FALHA:', falha)
    raise SystemExit(1)
print('OK: a leitura de laudo saiu de todos os caminhos e o resto da IA ficou.')
