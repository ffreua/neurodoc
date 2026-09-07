from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from events.models import OutboxEvent, OutboxEventStatus

from .carry_forward import has_pending_review
from .models import ClinicalAmendment, Encounter, EncounterStatus

ENCOUNTER_FINALIZED_TOPIC = 'clinical.encounter_finalized'


class FinalizationError(Exception):
    pass


def missing_requirements(encounter):
    """Tudo o que falta para finalizar, de uma vez.

    Existe porque a verificação em cascata era hostil: cada tentativa
    apontava um requisito, e só o próximo aparecia depois de resolver
    aquele. Quem estava fechando a consulta descobria a lista aos poucos, um
    erro por clique. Agora a tela mostra a lista inteira **antes** do clique,
    e a recusa, se acontecer, também vem completa.

    Cada item traz `aba` e `ancora` para a tela poder levar direto ao campo
    que falta.
    """
    pending = []
    if has_pending_review(encounter):
        count = encounter.carry_forward_items.filter(review_action='pending').count()
        pending.append({
            'texto': f'Revisar os {count} dado(s) trazidos da consulta anterior '
                     '— aceitar ou rejeitar cada um.',
            'aba': 'História', 'ancora': 'tab-historia', 'justificavel': False,
        })
    justified = bool(encounter.finalization_justification)
    if not (encounter.chief_complaint or encounter.hpi or justified):
        pending.append({
            'texto': 'Preencher a queixa principal ou a história da doença atual.',
            'aba': 'História', 'ancora': 'tab-historia', 'justificavel': True,
        })
    if not (encounter.plan_text or justified):
        pending.append({
            'texto': 'Preencher a conduta.',
            'aba': 'Conduta', 'ancora': 'tab-conduta', 'justificavel': True,
        })
    return pending


@transaction.atomic
def finalize_encounter(context, encounter, actor_membership):
    if encounter.status == EncounterStatus.FINALIZED:
        raise FinalizationError('Este atendimento já está finalizado.')

    pending = missing_requirements(encounter)
    if pending:
        itens = ' '.join(f'({index}) {item["texto"]}' for index, item in enumerate(pending, 1))
        extra = ''
        if any(item['justificavel'] for item in pending):
            extra = (
                ' Se algo aí não se aplica a esta consulta, escreva o motivo em '
                '"Justificativa da finalização", na aba Conduta.'
            )
        raise FinalizationError(f'Falta para finalizar: {itens}{extra}')

    encounter.status = EncounterStatus.FINALIZED
    encounter.finalized_at = timezone.now()
    encounter.finalized_by = actor_membership
    encounter.content_hash = encounter.compute_content_hash()
    encounter.row_version += 1
    encounter.full_clean()
    encounter.save()
    record_audit_event(
        actor_membership.user_id, context.tenant_id, 'clinical.encounter_finalized',
        object_type='encounter', object_id=encounter.id, outcome='success',
        integrity_metadata={'content_hash': encounter.content_hash},
    )
    OutboxEvent.objects.get_or_create(
        tenant_id=encounter.tenant_id, topic=ENCOUNTER_FINALIZED_TOPIC, aggregate_type='encounter',
        aggregate_id=encounter.id, event_version=encounter.row_version,
        defaults={
            'payload_minimal': {'encounter_id': str(encounter.id), 'patient_id': str(encounter.patient_id)},
            'available_at': timezone.now(),
            'status': OutboxEventStatus.PENDING,
        },
    )
    return encounter


@transaction.atomic
def add_amendment(context, encounter, author_membership, reason, text):
    if encounter.status != EncounterStatus.FINALIZED:
        raise FinalizationError('Adendo só se aplica a atendimento finalizado.')
    amendment = ClinicalAmendment.objects.create(
        tenant_id=context.tenant_id, encounter=encounter, author=author_membership,
        reason=reason, text=text, authored_at=timezone.now(),
    )
    record_audit_event(
        author_membership.user_id, context.tenant_id, 'clinical.amendment_added',
        object_type='encounter', object_id=encounter.id, outcome='success',
    )
    return amendment
