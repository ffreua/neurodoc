"""Cópia da consulta anterior: conduta, impressões, hipóteses (CID) e medicação.

RF-03.04: copiar do último atendimento **finalizado do próprio médico**
para aquele paciente, e só o que é decisão clínica que continua valendo —
conduta, impressões, hipóteses e a medicação em uso. Nunca achados do
exame, nunca queixa e história (aquilo é do dia), e nunca documento emitido.

Nada é aplicado sozinho: cada item vira um `CarryForwardItem` pendente, que
o médico aceita ou recusa um a um. É a diferença entre trazer a consulta
anterior e assinar a consulta anterior.

Um atendimento de origem diferente do último pode ser passado pelo chamador,
sempre de forma explícita e nunca inferido — a "seleção explícita
autorizada" do requisito.
"""
from django.db import transaction

from .models import CarryForwardItem, Encounter, EncounterStatus, MedicationStatus


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

    # Medicação em uso. O próprio `Medication` já dizia que a lista da
    # consulta seguinte vem por aqui — a lista pertence ao atendimento, e não
    # ao paciente, justamente para que o registro de ontem não mude quando o
    # tratamento de hoje muda. Sem esta cópia, a promessa do modelo não
    # existia: o médico redigitava tudo a cada retorno, que é como uma lista
    # de medicação deixa de ser confiável.
    #
    # Só o que está **em uso**. Suspenso e concluído são decisões já tomadas
    # na consulta anterior; trazê-los faria o médico recusar as mesmas linhas
    # todo retorno, e uma revisão que se rejeita sempre deixa de ser lida.
    for medication in source_encounter.medications.filter(status=MedicationStatus.IN_USE):
        item, _ = CarryForwardItem.objects.update_or_create(
            tenant_id=context.tenant_id, target_encounter=target_encounter,
            field_path=f'medication:{medication.id}',
            defaults={
                'source_encounter': source_encounter,
                'source_version_hash': versao,
                'copied_value': {
                    'name': medication.name,
                    'dose': medication.dose,
                    'route': medication.route,
                    'frequency': medication.frequency,
                    'started_on': medication.started_on.isoformat() if medication.started_on else None,
                    'indication': medication.indication,
                    'prescriber': medication.prescriber,
                    'notes': medication.notes,
                },
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
MEDICATION_LABEL = 'Medicação da consulta anterior'


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
    if item.field_path.startswith('medication:'):
        # Posologia numa linha só, como se lê numa receita: o que se decide
        # aqui é se aquele remédio continua, e para isso é preciso ver dose e
        # frequência junto do nome, não um dicionário ao lado.
        posologia = ' · '.join(
            parte for parte in (value.get('dose'), value.get('frequency')) if parte
        )
        detalhe = ' · '.join(parte for parte in (posologia, value.get('indication')) if parte)
        return {'label': MEDICATION_LABEL, 'value': value.get('name') or '', 'detail': detalhe}
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

    from .models import EncounterDiagnosis, Medication, MedicationRoute, ReviewAction

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
    elif item.field_path.startswith('medication:'):
        # `get_or_create` pela identidade que o olho usa — nome e dose. Aceitar
        # duas vezes (a tela recarregada, o clique repetido) não pode deixar o
        # mesmo remédio duas vezes na lista do atendimento.
        Medication.objects.get_or_create(
            tenant_id=encounter.tenant_id, encounter=encounter,
            name=value.get('name', ''), dose=value.get('dose', ''),
            defaults={
                'route': value.get('route') or MedicationRoute.ORAL,
                'frequency': value.get('frequency') or '',
                'started_on': value.get('started_on') or None,
                'indication': value.get('indication') or '',
                'prescriber': value.get('prescriber') or '',
                'notes': value.get('notes') or '',
                # Só o que estava em uso é copiado, e aceitar é dizer que
                # continua em uso.
                'status': MedicationStatus.IN_USE,
            },
        )
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
