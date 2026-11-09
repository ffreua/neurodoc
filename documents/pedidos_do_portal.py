"""O pedido do portal ligado ao resto do sistema.

O pedido nasce no portal público e termina num documento médico. Até
2026-11-09 o caminho entre os dois era um atalho próprio: a tela de atender
desenhava só um texto livre, e o pedido de receita de controle especial não
chegava à receita eletrônica do SNCR — o médico escolhia o formato da
Anvisa, o servidor exigia os itens estruturados que a tela não mostrava, e a
recusa voltava como "Confira o conteúdo" sem campo marcado. O pedido de
relatório, por sua vez, não chegava ao relatório com apoio de IA, que é como
o resto do sistema escreve relatório.

A regra deste módulo é que o pedido **entra** pelos caminhos que já existem,
em vez de ter os seus: a receita pelos mesmos campos e pela mesma
`issuance.create_draft`, o relatório pelo mesmo `ai.services.
request_patient_report`. O que é do pedido mora aqui: o que ele sugere como
ponto de partida e o registro de que foi atendido, que agora tem duas portas
(o rascunho direto e o relatório da IA aprovado) e por isso um lugar só.
"""

import uuid

from django.utils import timezone

from audit.services import record_audit_event

from .models import DocumentRequest, DocumentRequestKind, DocumentRequestStatus

#: A finalidade do relatório com IA (`ai.relatorio.FINALIDADES`) que cada
#: finalidade do portal (`portal_views.REPORT_PURPOSES`) sugere. As terapias
#: vão para a livre: o destinatário é um profissional de saúde que não é
#: médico, e nenhum dos modelos é escrito para ele — o texto do pedido diz
#: para quem é. O médico troca a escolha na tela da IA.
FINALIDADE_DA_IA = {
    'INSS / benefício / perícia': 'inss',
    'Convênio / plano de saúde': 'plano_saude',
    'Trabalho / afastamento / adaptação': 'escola_trabalho',
    'Escola / universidade': 'escola_trabalho',
}


def pedido_aberto(tenant_id, patient_id, pedido_id, kind=None):
    """O pedido ainda aberto deste paciente, ou `None`.

    O id chega de fora — da URL ou de um campo escondido —, então é
    conferido por inteiro: id mal formado, outra clínica, outro paciente,
    outro tipo ou pedido já respondido valem `None`, e quem chama segue sem o
    vínculo em vez de quebrar.
    """
    try:
        pedido_id = uuid.UUID(str(pedido_id))
    except (ValueError, TypeError, AttributeError):
        return None
    filtro = {
        'tenant_id': tenant_id, 'patient_id': patient_id, 'id': pedido_id,
        'status__in': [DocumentRequestStatus.RECEIVED, DocumentRequestStatus.IN_REVIEW],
    }
    if kind is not None:
        filtro['kind'] = kind
    return DocumentRequest.objects.filter(**filtro).first()


def medicacoes(pedido):
    return [m for m in (pedido.payload or {}).get('medicacoes', []) if (m.get('nome') or '').strip()]


def instrucao_para_ia(pedido):
    """A finalidade sugerida e o pedido do relatório, escritos do que o paciente pediu.

    Vai para a caixa da tela da IA, **aberta para o médico reescrever**: é
    ele quem pede o relatório ao modelo, e o que o paciente escreveu é o
    ponto de partida, não a ordem. O texto passa pela desidentificação antes
    de ir ao provedor, como o resto do pedido (`ai.services`).
    """
    payload = pedido.payload or {}
    finalidade = (payload.get('finalidade') or '').strip()
    conteudo = (payload.get('conteudo') or '').strip()
    linhas = [
        f'Relatório pedido pelo paciente no portal em '
        f'{timezone.localtime(pedido.created_at):%d/%m/%Y}.',
    ]
    if finalidade:
        linhas.append(f'Finalidade informada: {finalidade}.')
    if conteudo:
        linhas.append(f'O que o paciente pediu que conste: {conteudo}')
    return FINALIDADE_DA_IA.get(finalidade, 'livre'), '\n'.join(linhas)


def marcar_em_revisao(pedido, actor_id):
    """O relatório do pedido começou a ser escrito pela IA.

    `IN_REVIEW` continua aberto (`is_open`): se o rascunho for descartado, o
    pedido segue na fila para outro caminho. O que muda é a fila dizer que
    alguém já está nele.
    """
    atualizados = DocumentRequest.objects.filter(
        id=pedido.id, status=DocumentRequestStatus.RECEIVED,
    ).update(status=DocumentRequestStatus.IN_REVIEW)
    if atualizados:
        record_audit_event(
            actor_id, pedido.tenant_id, 'documents.portal_request_ai_started',
            object_type='document_request', object_id=pedido.id, outcome='success',
        )


def marcar_atendido(pedido, documento, physician, actor_id, alterado, via_ia=False):
    """O pedido virou este documento.

    As duas portas passam por aqui: o rascunho criado na tela do pedido e o
    relatório da IA aprovado. A linha é relida com trava e conferida aberta
    — entre a tela e o clique cabe outro médico recusar o pedido, e um pedido
    recusado não pode aparecer depois como atendido.

    Devolve `False` quando o pedido já não estava aberto: o documento existe
    do mesmo jeito, só não fica pendurado num pedido que teve outro
    desfecho.
    """
    travado = (
        DocumentRequest.objects.select_for_update()
        .filter(id=pedido.id, tenant_id=documento.tenant_id, patient_id=documento.patient_id)
        .first()
    )
    if travado is None or not travado.is_open:
        return False
    travado.status = DocumentRequestStatus.FULFILLED
    travado.resulting_document = documento
    travado.reviewed_by = physician
    travado.reviewed_at = timezone.now()
    travado.save(update_fields=['status', 'resulting_document', 'reviewed_by', 'reviewed_at'])
    # Registra **se** o médico reescreveu, nunca o quê: o conteúdo é clínico
    # e a trilha não guarda texto de prontuário.
    metadados = {'document': str(documento.id), 'edited_by_physician': bool(alterado)}
    if via_ia:
        metadados['via_ia'] = True
    record_audit_event(
        actor_id, travado.tenant_id, 'documents.portal_request_drafted',
        object_type='document_request', object_id=travado.id, outcome='success',
        integrity_metadata=metadados,
    )
    return True


def relatorios_da_ia(pedido):
    """Os relatórios com IA pedidos a partir deste pedido, do mais recente."""
    if pedido.kind != DocumentRequestKind.REPORT:
        return []
    from ai.models import AIJob, AIJobKind

    return list(
        AIJob.objects.filter(
            tenant_id=pedido.tenant_id, patient_id=pedido.patient_id,
            kind=AIJobKind.PATIENT_REPORT, target_ref__pedido_portal=str(pedido.id),
        ).order_by('-created_at')[:5]
    )
