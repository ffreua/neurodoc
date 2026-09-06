"""Gravação dos itens do roteiro como achados do atendimento.

Recebe o POST de um eixo inteiro e grava só o que foi preenchido: item
deixado em branco não cria linha, e por isso nunca aparece como normal.
Item que já tinha valor e foi esvaziado é apagado — é assim que o médico
desfaz um registro feito por engano.
"""
from django.db import transaction

from clinical.models import ExaminationFinding, ExaminationState, Side

from .models import ExamInputType, ExamNode, ExamNodeType

SIDES_FOR_LATERAL = (Side.LEFT, Side.RIGHT)
VALID_STATES = {choice for choice, _ in ExaminationState.choices}


def field_name(node, side):
    """Nome do campo no formulário: `no__<caminho>__<lado>`."""
    return f'no__{node.path}__{side}'


def _sides(node):
    return SIDES_FOR_LATERAL if node.lateralized else (Side.NOT_APPLICABLE,)


def _extract(node, data, prefix):
    """Valor tipado de um nó a partir do POST, ou None quando em branco."""
    if node.node_type == ExamNodeType.SCALE:
        scores = {}
        for item in node.scale.items.all():
            raw = (data.get(f'{prefix}__{item.code}') or '').strip()
            if raw:
                try:
                    scores[item.code] = int(raw)
                except ValueError:
                    continue
        if not scores:
            return None
        total = sum(scores.values())
        rendered = ', '.join(f'{code}={value}' for code, value in sorted(scores.items()))
        return {
            'value_json': {'scale': node.scale.code, 'scores': scores, 'total': total},
            'qualifier': f'{node.scale.code} = {total} ({rendered})'[:255],
            'numeric_value': total,
            'state': ExaminationState.NOT_ASSESSED,
        }

    if node.input_type == ExamInputType.STATE:
        raw = (data.get(prefix) or '').strip()
        if raw not in VALID_STATES or raw == ExaminationState.NOT_ASSESSED:
            return None
        return {'value_json': {}, 'qualifier': '', 'numeric_value': None, 'state': raw}

    if node.input_type == ExamInputType.NUMBER:
        raw = (data.get(prefix) or '').strip()
        if not raw:
            return None
        try:
            number = float(raw.replace(',', '.'))
        except ValueError:
            return None
        return {
            'value_json': {'number': number, 'unit': node.unit},
            'qualifier': f'{raw}{" " + node.unit if node.unit else ""}'[:255],
            'numeric_value': number,
            'state': ExaminationState.NOT_ASSESSED,
        }

    if node.input_type == ExamInputType.BOOLEAN:
        raw = (data.get(prefix) or '').strip()
        if raw not in ('presente', 'ausente'):
            return None
        return {
            'value_json': {'boolean': raw == 'presente'},
            'qualifier': 'Presente' if raw == 'presente' else 'Ausente',
            'numeric_value': None,
            'state': ExaminationState.NOT_ASSESSED,
        }

    if node.input_type == ExamInputType.MULTICHOICE:
        chosen = [value for value in data.getlist(prefix) if value]
        if not chosen:
            return None
        return {
            'value_json': {'choices': chosen},
            'qualifier': ', '.join(chosen)[:255],
            'numeric_value': None,
            'state': ExaminationState.NOT_ASSESSED,
        }

    # choice e text
    raw = (data.get(prefix) or '').strip()
    if not raw:
        return None
    key = 'choice' if node.input_type == ExamInputType.CHOICE else 'text'
    return {
        'value_json': {key: raw},
        'qualifier': raw[:255],
        'numeric_value': None,
        'state': ExaminationState.NOT_ASSESSED,
    }


@transaction.atomic
def save_axis(context, encounter, template, axis, data):
    """Grava um eixo inteiro do roteiro. Devolve (gravados, removidos)."""
    nodes = list(
        ExamNode.objects
        .filter(template=template, axis=axis, active=True)
        .exclude(node_type=ExamNodeType.GROUP)
        .select_related('scale')
        .prefetch_related('scale__items')
    )
    saved = 0
    removed = 0
    for node in nodes:
        for side in _sides(node):
            prefix = field_name(node, side)
            note = (data.get(f'{prefix}__nota') or '').strip()
            payload = _extract(node, data, prefix)

            if payload is None and not note:
                deleted, _ = ExaminationFinding.objects.filter(
                    tenant_id=context.tenant_id, encounter=encounter,
                    item_code=node.path, side=side,
                ).delete()
                removed += deleted
                continue

            payload = payload or {
                'value_json': {}, 'qualifier': '', 'numeric_value': None,
                'state': ExaminationState.NOT_ASSESSED,
            }
            ExaminationFinding.objects.update_or_create(
                tenant_id=context.tenant_id, encounter=encounter,
                item_code=node.path, side=side, body_site='',
                defaults={
                    'domain': node.axis,
                    'template_node': node,
                    'template_version': template.version,
                    'note': note[:2000],
                    'schema_version': str(template.version),
                    **payload,
                },
            )
            saved += 1
    return saved, removed


def state_items_under(template, path):
    """Itens do tipo estado sob um nó, incluindo o próprio.

    Só item de estado pode ser "normal": um item de escolha ("Padrão da
    resposta motora") não tem normalidade definida, e um item numérico
    (força em MRC) só teria se o sistema inventasse a medida — que é
    exatamente o que um prontuário não pode fazer.
    """
    from django.db.models import Q

    return ExamNode.objects.filter(
        template=template, active=True,
        node_type=ExamNodeType.ITEM, input_type=ExamInputType.STATE,
    ).filter(Q(path=path) | Q(path__startswith=f'{path}.'))


@transaction.atomic
def mark_group_normal(context, encounter, template, path):
    """Marca como normal os itens de estado de um grupo. Ação deliberada.

    Regras que tornam isso seguro num prontuário (PRD 11.1):

    - **nunca sobrescreve registro manual.** Item que o médico já preencheu
      fica como está e entra na contagem de ignorados; só é marcado o que
      estava em branco ou o que já viera desta mesma ação em bloco;
    - **só item de estado** — ver `state_items_under`;
    - **fica marcado como ação em bloco** (`value_json['bulk']`), o que
      permite desfazer exatamente o que foi criado assim, sem tocar no que
      foi digitado à mão.

    Devolve (marcados, ignorados).
    """
    nodes = list(state_items_under(template, path))
    existing = {
        (finding.item_code, finding.side): finding
        for finding in ExaminationFinding.objects.filter(
            tenant_id=context.tenant_id, encounter=encounter,
            item_code__in=[node.path for node in nodes],
        )
    }
    marked = 0
    skipped = 0
    for node in nodes:
        for side in _sides(node):
            current = existing.get((node.path, side))
            if current is not None and not current.value_json.get('bulk'):
                skipped += 1
                continue
            ExaminationFinding.objects.update_or_create(
                tenant_id=context.tenant_id, encounter=encounter,
                item_code=node.path, side=side, body_site='',
                defaults={
                    'domain': node.axis,
                    'template_node': node,
                    'template_version': template.version,
                    'state': ExaminationState.NORMAL,
                    'numeric_value': None,
                    'qualifier': '',
                    'note': current.note if current is not None else '',
                    'value_json': {'bulk': True},
                    'schema_version': str(template.version),
                },
            )
            marked += 1
    return marked, skipped


@transaction.atomic
def undo_group_normal(context, encounter, template, path):
    """Desfaz a marcação em bloco de um grupo, antes da finalização.

    Remove apenas o que foi criado pela ação em bloco e continua sem
    observação escrita — o que o médico ajustou ou comentou depois
    permanece.
    """
    paths = [node.path for node in state_items_under(template, path)]
    removed = 0
    for finding in ExaminationFinding.objects.filter(
        tenant_id=context.tenant_id, encounter=encounter, item_code__in=paths,
        state=ExaminationState.NORMAL,
    ):
        if finding.value_json.get('bulk') and not finding.note:
            finding.delete()
            removed += 1
    return removed
