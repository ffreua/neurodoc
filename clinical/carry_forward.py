"""Copia da consulta anterior: conduta, impressões e hipóteses (CID).

RF-03.04: copy only `plan_text` (conduta), `impressions` and diagnoses
(hipóteses) from
the physician's own last finalized encounter for this patient — never exam
findings, never chief complaint/HPI, and never auto-generated prescriptions
or requests. An alternative source encounter must be passed explicitly by
the caller (never inferred), matching the "seleção explícita autorizada"
requirement.
"""
from django.db import transaction

from .models import CarryForwardItem, Encounter, EncounterStatus


def default_source_encounter(target_encounter):
    return (
        Encounter.objects
        .filter(
            tenant_id=target_encounter.tenant_id, patient_id=target_encounter.patient_id,
            physician_membership_id=target_encounter.physician_membership_id,
            status=EncounterStatus.FINALIZED, occurred_at__lt=target_encounter.occurred_at,
        )
        .exclude(id=target_encounter.id)
        .order_by('-occurred_at')
        .first()
    )


@transaction.atomic
def carry_forward(context, target_encounter, source_encounter=None):
    if source_encounter is None:
        source_encounter = default_source_encounter(target_encounter)
    if source_encounter is None:
        return []

    items = []
    # Conduta e impressões: os dois campos de texto que se leva adiante, e
    # os dois existem nos **dois** tipos de atendimento. É o que faz a
    # conduta de um texto livre chegar num estruturado e vice-versa — a
    # cópia é por campo, e o campo é o mesmo nos dois.
    versao = source_encounter.content_hash or source_encounter.compute_content_hash()
    for campo in ('plan_text', 'impressions'):
        valor = getattr(source_encounter, campo, '')
        if not valor:
            continue
        item, _ = CarryForwardItem.objects.update_or_create(
            tenant_id=context.tenant_id, target_encounter=target_encounter, field_path=campo,
            defaults={
                'source_encounter': source_encounter,
                'source_version_hash': versao,
                'copied_value': {'text': valor},
            },
        )
        items.append(item)

    for diagnosis in source_encounter.diagnoses.all():
        item, _ = CarryForwardItem.objects.update_or_create(
            tenant_id=context.tenant_id, target_encounter=target_encounter,
            field_path=f'diagnosis:{diagnosis.id}',
            defaults={
                'source_encounter': source_encounter,
                'source_version_hash': source_encounter.content_hash or source_encounter.compute_content_hash(),
                'copied_value': {
                    'code_snapshot': diagnosis.code_snapshot,
                    'description_snapshot': diagnosis.description_snapshot,
                    'certainty': diagnosis.certainty,
                    'rank': diagnosis.rank,
                },
            },
        )
        items.append(item)
    return items


def has_pending_review(target_encounter):
    from .models import ReviewAction
    return CarryForwardItem.objects.filter(
        target_encounter=target_encounter, review_action=ReviewAction.PENDING,
    ).exists()


#: Rótulo de cada campo copiado, para a tela não exibir `plan_text` nem
#: `diagnosis:a192554a-…`. O que aparece é o nome do campo no prontuário.
FIELD_LABELS = {
    'plan_text': 'Conduta da consulta anterior',
    'impressions': 'Impressões da consulta anterior',
}
DIAGNOSIS_LABEL = 'Hipótese da consulta anterior'


def describe_item(item):
    """Rótulo e valor legíveis de um item trazido da consulta anterior.

    A tela mostrava o caminho interno e o dicionário cru — `plan_text` com
    `{'text': 'TPM 100mg'}` ao lado, e a hipótese como
    `diagnosis:<uuid>` com `{'rank': 1, 'certainty': 'suspected', …}`. Quem
    precisa decidir se aceita ou rejeita não tem por que ler o formato de
    armazenamento; precisa ler o que está sendo copiado.
    """
    from .models import DiagnosisCertainty

    value = item.copied_value or {}
    if item.field_path in FIELD_LABELS:
        return {'label': FIELD_LABELS[item.field_path], 'value': value.get('text', ''), 'detail': ''}
    if item.field_path.startswith('diagnosis:'):
        code = value.get('code_snapshot') or ''
        description = value.get('description_snapshot') or ''
        certainty = value.get('certainty') or ''
        label = DIAGNOSIS_LABEL
        text = f'{code} — {description}' if code else description
        detail = DiagnosisCertainty(certainty).label if certainty in DiagnosisCertainty.values else ''
        if value.get('rank'):
            detail = f'{detail} · ordem {value["rank"]}'.strip(' ·')
        return {'label': label, 'value': text, 'detail': detail}
    # Campo novo, copiado por uma versão mais recente do sistema: mostra o
    # caminho em vez de esconder que existe algo a revisar.
    return {'label': FIELD_LABELS.get(item.field_path, item.field_path), 'value': str(value), 'detail': ''}


@transaction.atomic
def review_carry_forward_item(item, action, actor_membership_id):
    from django.utils import timezone

    from .models import EncounterDiagnosis, ReviewAction

    item.review_action = action
    item.reviewed_at = timezone.now()
    item.reviewed_by_id = actor_membership_id
    item.full_clean()
    item.save()

    if action != ReviewAction.ACCEPTED:
        return item

    encounter = item.target_encounter
    value = item.copied_value or {}
    # Os campos de texto são aplicados pelo nome: acrescentar um campo
    # copiável (as impressões foram o segundo) passa a funcionar aqui sem
    # um `elif` novo — e um `elif` esquecido deixaria o item marcado como
    # aceito sem nada ter sido copiado, que foi o defeito que a hipótese
    # teve antes.
    if item.field_path in FIELD_LABELS:
        setattr(encounter, item.field_path, value.get('text', ''))
        encounter.save(update_fields=[item.field_path])
    elif item.field_path.startswith('diagnosis:'):
        # Aceitar uma hipótese não fazia nada: o item ficava marcado como
        # aceito e a hipótese não entrava no atendimento. O aceite existe
        # justamente para trazê-la.
        EncounterDiagnosis.objects.get_or_create(
            tenant_id=encounter.tenant_id, encounter=encounter,
            code_snapshot=value.get('code_snapshot', ''),
            description_snapshot=value.get('description_snapshot', ''),
            defaults={
                'certainty': value.get('certainty') or 'suspected',
                'rank': value.get('rank') or (encounter.diagnoses.count() + 1),
                'physician_note': 'Trazida da consulta anterior e revisada.',
            },
        )
    return item
