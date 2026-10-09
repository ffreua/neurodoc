import uuid

from django.conf import settings
from django.db import transaction

from clinical.models import Encounter
from tenancy.context import AccessContext
from tenancy.plans import has_clinical_ai

from . import services
from .models import AIJobKind, AIJobStatus
from .tasks import run_ai_job


def handle_encounter_finalized(event):
    """RF-11.01: analysis only runs when both the platform (AI_ENABLED)
    and the tenant (Tenant.settings['ai_encounter_summary_enabled']) opt
    in -- neither alone is enough. A tenant that never turned this on gets
    no AIJob at all, not a disabled one.
    """
    if not settings.AI_ENABLED:
        return
    encounter = Encounter.objects.filter(id=event.payload_minimal['encounter_id']).first()
    if encounter is None or encounter.finalized_by_id is None:
        return
    tenant = encounter.tenant
    if not (tenant.settings or {}).get('ai_encounter_summary_enabled', False):
        return
    # Plano sem IA sai por `return`, e nao pela excecao de
    # `build_ai_authorization` -- que tambem recusaria, mais abaixo.
    #
    # A diferenca importa porque isto e um consumidor de evento: excecao
    # aqui faz o despachante reentregar com recuo e, esgotadas as
    # tentativas, marcar o evento como FAILED (`events/dispatcher.py`).
    # Mas nada falhou -- a clinica simplesmente nao contratou o recurso, e
    # o evento foi processado corretamente ao nao fazer nada. Deixar isso
    # virar falha encheria a caixa de eventos de falha falsa a cada
    # atendimento finalizado, escondendo a falha de verdade quando viesse.
    #
    # Mesma forma dos dois `return` acima, pela mesma razao.
    if not has_clinical_ai(tenant.plan):
        return

    fake_context = AccessContext(
        user_id=encounter.finalized_by.user_id, tenant_id=tenant.id,
        membership_id=encounter.finalized_by_id, permissions=frozenset(), request_id=uuid.uuid4(),
    )
    job = services.create_job(
        fake_context, AIJobKind.ENCOUNTER_SUMMARY, purpose='Resumo automático ao finalizar atendimento',
        patient_id=encounter.patient_id, encounter_id=encounter.id,
    )
    # Para a fila só depois do commit. O despachante já não envolve o
    # consumidor numa transação (ver `events/dispatcher.py`), e então
    # `create_job` confirma o job antes desta linha; `on_commit` é a
    # garantia de que continua assim se alguém chamar isto de dentro de
    # um `atomic`. Publicado antes, o worker podia receber o id de uma
    # linha que ainda não via, falhar sem achar o job, e o job ficar
    # "na fila" para sempre (auditoria de 2026-10-09, A3). Se a
    # publicação se perder mesmo assim, `retomar_jobs_parados` o acha.
    if job.status == AIJobStatus.QUEUED:
        transaction.on_commit(lambda: run_ai_job.delay(str(job.id)))
