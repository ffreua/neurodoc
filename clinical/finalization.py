from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from events.models import OutboxEvent, OutboxEventStatus

from .carry_forward import has_pending_review
from .models import EncounterKind, CarryForwardItem, ClinicalAmendment, Encounter, EncounterStatus

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

    # O requisito é o mesmo nos dois tipos — "há registro do que houve na
    # consulta?" —, mas o campo onde esse registro mora não é.
    #
    # O atendimento de texto livre não tem queixa nem história: tem o corpo
    # escrito de uma vez. Exigir os campos do estruturado aqui obrigaria a
    # escrever uma justificativa de finalização em TODA consulta de texto
    # livre — e uma trava que se dispara sempre deixa de ser lida e passa a
    # ser contornada por reflexo.
    #
    # As âncoras também mudam: a tela de texto livre não tem abas, e mandar
    # alguém para "a aba História" ali é mandá-lo procurar o que não existe.
    if encounter.kind == EncounterKind.FREE_TEXT:
        if not (encounter.free_text or justified):
            pending.append({
                'texto': 'Escrever o texto do atendimento.',
                'aba': 'Texto livre', 'ancora': 'id_free_text', 'justificavel': True,
            })
        if not (encounter.plan_text or justified):
            pending.append({
                'texto': 'Preencher a conduta.',
                'aba': 'Impressões e conduta', 'ancora': 'id_plan_text', 'justificavel': True,
            })
        return pending

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
    """Fecha o atendimento e devolve a linha **como ela está no banco**.

    Relido sob trava, e gravando só os campos da finalização. Gravava a
    instância que a view tinha carregado, inteira: se o autosave do último
    parágrafo chegava junto com o clique em "Finalizar" -- que é
    exatamente quando ele chega --, a finalização escrevia por cima o
    texto de antes, e o hash selava a versão velha (auditoria de
    2026-10-09, ND-1121-002). O autosave trava a mesma linha, então os
    dois agora se enfileiram: ou o texto entra antes e é ele que se
    finaliza, ou chega depois e encontra o atendimento fechado.
    """
    encounter = type(encounter).objects.select_for_update().get(id=encounter.id)
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
    encounter.save(update_fields=[
        'status', 'finalized_at', 'finalized_by', 'content_hash', 'row_version', 'updated_at',
    ])
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


def discard_summary(encounter):
    """O que se perde ao descartar este atendimento.

    A tela mostra isto **antes** de confirmar. Descartar um atendimento
    aberto por engano é operação legítima; descartar um em que já se
    escreveu meia consulta, sem saber que havia conteúdo, não é.
    """
    return {
        'tem_historia': bool(encounter.chief_complaint or encounter.hpi
                             or encounter.personal_history or encounter.family_history
                             or encounter.habits_history),
        'tem_conduta': bool(encounter.plan_text),
        'tem_exame_texto': bool(encounter.neurological_exam_text),
        # O corpo do atendimento de texto livre, e as impressões. Ficavam
        # de fora: um rascunho com a evolução inteira escrita era
        # descartado como "vazio", sem pedir motivo e sem guardar na trilha
        # o que havia (auditoria de 2026-10-09, ND-1121-013).
        'tem_texto_livre': bool((encounter.free_text or '').strip()),
        'tem_impressoes': bool((encounter.impressions or '').strip()),
        'exame': encounter.examination_findings.count(),
        'medicacoes': encounter.medications.count(),
        'exames': encounter.exam_results.count(),
        'hipoteses': encounter.diagnoses.count(),
    }


def has_content(encounter):
    resumo = discard_summary(encounter)
    return bool(
        resumo['tem_historia'] or resumo['tem_conduta'] or resumo['tem_exame_texto']
        or resumo['tem_texto_livre'] or resumo['tem_impressoes']
        or resumo['exame'] or resumo['medicacoes'] or resumo['exames'] or resumo['hipoteses']
    )


def discard_blockers(encounter):
    """Motivos que impedem o descarte, em linguagem de quem usa a tela.

    Não é cascata: documento médico emitido, cobrança lançada e dado já
    trazido para outra consulta são registros de outras naturezas que
    apontam para este atendimento. Apagar o atendimento por baixo deles
    deixaria uma receita assinada referindo uma consulta que não existe.
    Melhor recusar e dizer o porquê.
    """
    blockers = []
    issued = encounter.medical_documents.exclude(status__in=['draft', 'ready_to_sign']).count()
    if issued:
        blockers.append(
            f'{issued} documento(s) médico(s) já emitido(s) a partir deste atendimento. '
            'Documento assinado não pode referenciar uma consulta descartada.'
        )
    receivables = encounter.receivables.count()
    if receivables:
        blockers.append(
            f'{receivables} cobrança(s) lançada(s) para este atendimento. '
            'Cancele no Financeiro antes de descartar.'
        )
    derived = CarryForwardItem.objects.filter(source_encounter=encounter).count()
    if derived:
        blockers.append(
            f'{derived} dado(s) deste atendimento foram levados para outra consulta.'
        )
    return blockers


@transaction.atomic
def discard_encounter(context, encounter, actor_membership, reason=''):
    """Descarta um atendimento que **não** foi finalizado.

    Atendimento finalizado é registro clínico e não se apaga — nem com
    justificativa: correção lá entra como adendo identificado. Antes da
    finalização o que existe é rascunho, e um atendimento aberto por engano
    tem de poder sair da linha do tempo do paciente.

    O que garante que isso não é uma porta para apagar prontuário:

    - só passa quando `is_editable()`, isto é, rascunho ou em andamento;
    - recusa quando há documento emitido, cobrança ou dado já levado para
      outra consulta (ver `discard_blockers`);
    - exige justificativa quando já há conteúdo escrito;
    - registra no log de auditoria **o que havia** no momento do descarte,
      com a justificativa. A linha desaparece do prontuário, não do log.
    """
    if encounter.status == EncounterStatus.FINALIZED:
        raise FinalizationError(
            'Atendimento finalizado não pode ser descartado: o registro é imutável. '
            'Use um adendo para corrigir.'
        )
    if not encounter.is_editable():
        raise FinalizationError('Este atendimento não pode mais ser descartado.')

    blockers = discard_blockers(encounter)
    if blockers:
        raise FinalizationError('Não é possível descartar: ' + ' '.join(blockers))

    resumo = discard_summary(encounter)
    if has_content(encounter) and not reason.strip():
        raise FinalizationError(
            'Este atendimento já tem conteúdo registrado. Escreva o motivo do descarte.'
        )

    record_audit_event(
        actor_membership.user_id, context.tenant_id, 'clinical.encounter_discarded',
        object_type='encounter', object_id=encounter.id, outcome='success',
        integrity_metadata={
            'patient_id': str(encounter.patient_id),
            'occurred_at': encounter.occurred_at.isoformat(),
            'status': encounter.status,
            'reason': reason.strip()[:255],
            'conteudo': resumo,
        },
    )

    # As linhas-filhas saem com o atendimento. A ordem importa: `Encounter`
    # é referenciado por PROTECT em várias delas, então apagar o pai antes
    # levantaria ProtectedError.
    encounter.carry_forward_items.all().delete()
    encounter.examination_findings.all().delete()
    encounter.diagnoses.all().delete()
    encounter.amendments.all().delete()
    encounter.medications.all().delete()
    for result in encounter.exam_results.all():
        result.lab_values.all().delete()
        # O anexo fica: ele é documento do paciente, com retenção própria.
        # Descartar o registro do exame não é motivo para descartar o laudo.
        result.attachment = None
        result.save(update_fields=['attachment'])
    encounter.exam_results.all().delete()
    # Rascunho de documento médico e trabalho de IA são derivados deste
    # atendimento e não existem sem ele.
    encounter.medical_documents.all().delete()
    for job in encounter.ai_jobs.all():
        job.artifacts.all().delete()
    encounter.ai_jobs.all().delete()
    # O anexo enviado aqui continua no prontuário do paciente, só perde o
    # vínculo com a consulta descartada (a FK é SET_NULL).
    encounter.delete()
    return resumo


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
