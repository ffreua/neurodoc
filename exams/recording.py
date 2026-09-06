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
