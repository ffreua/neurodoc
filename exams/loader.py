"""Carga de roteiros e escalas a partir dos arquivos YAML.

Um roteiro é sempre instalado **dentro de um tenant**, como roteiro oficial
da organização. Não existe biblioteca global compartilhada: cada clínica
recebe a sua cópia e pode editá-la sem afetar as demais, que é o mesmo
princípio de isolamento do resto do produto.

Reinstalar não sobrescreve: gera uma **nova versão** do roteiro. Um
atendimento antigo continua apontando para a versão com que foi
preenchido.
"""
from pathlib import Path

import yaml
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    ExamInputType, ExamNode, ExamNodeType, ExamScale, ExamScaleItem, ExamTemplate,
    ExamTemplateStatus,
)

DATA_DIR = Path(__file__).resolve().parent / 'data'
SCALES_FILE = DATA_DIR / 'escalas.yaml'

# Um item sem tipo declarado registra estado (não avaliado / não informado /
# normal / alterado), que é o padrão do produto.
DEFAULT_INPUT = ExamInputType.STATE

VALID_INPUTS = {choice for choice, _ in ExamInputType.choices}


class TemplateLoadError(Exception):
    pass


def _slug(value):
    return str(value or '').strip()


def _normalize_options(raw):
    """Aceita ["A", "B"] ou [{value, label}] e devolve sempre a forma longa."""
    options = []
    for entry in raw or []:
        if isinstance(entry, dict):
            value = entry.get('value')
            label = entry.get('label', value)
        else:
            value = label = entry
        if value is None:
            continue
        options.append({'value': value, 'label': str(label)})
    return options


def load_scales(tenant_id, path=SCALES_FILE):
    """Cria/atualiza as escalas do tenant. Idempotente pelo `code`."""
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or []
    installed = []
    for entry in data:
        code = _slug(entry.get('code'))
        if not code:
            raise TemplateLoadError('Escala sem `code`')
        scale, _ = ExamScale.objects.update_or_create(
            tenant_id=tenant_id, code=code,
            defaults={
                'name': entry.get('name', code),
                'description': entry.get('description', '') or '',
                'source_note': entry.get('source_note', '') or '',
                'min_score': entry.get('min_score'),
                'max_score': entry.get('max_score'),
                'active': True,
            },
        )
        seen = []
        for order, item in enumerate(entry.get('items') or []):
            item_code = _slug(item.get('code'))
            if not item_code:
                raise TemplateLoadError(f'Item sem `code` na escala {code}')
            ExamScaleItem.objects.update_or_create(
                tenant_id=tenant_id, scale=scale, code=item_code,
                defaults={
                    'order': order,
                    'label': item.get('label', item_code),
                    'options': _normalize_options(item.get('options')),
                },
            )
            seen.append(item_code)
        # Item retirado do arquivo some da escala; nada aponta para um item
        # de escala isoladamente, então remover é seguro.
        ExamScaleItem.objects.filter(tenant_id=tenant_id, scale=scale).exclude(code__in=seen).delete()
        installed.append(scale)
    return installed


def _build_nodes(tenant_id, template, entries, parent, axis, prefix, scales, counters, trail=()):
    for order, entry in enumerate(entries or []):
        code = _slug(entry.get('code'))
        if not code:
            raise TemplateLoadError(f'Nó sem `code` sob {prefix or "raiz"}')
        path = f'{prefix}.{code}' if prefix else code
        if len(path) > 200:
            raise TemplateLoadError(f'Caminho longo demais: {path}')

        children = entry.get('children')
        scale_code = _slug(entry.get('scale'))
        if children:
            node_type = ExamNodeType.GROUP
            input_type = ''
        elif scale_code:
            node_type = ExamNodeType.SCALE
            input_type = ''
        else:
            node_type = ExamNodeType.ITEM
            input_type = _slug(entry.get('input')) or DEFAULT_INPUT
            if input_type not in VALID_INPUTS:
                raise TemplateLoadError(f'Tipo de entrada desconhecido em {path}: {input_type!r}')

        scale = None
        if scale_code:
            scale = scales.get(scale_code)
            if scale is None:
                raise TemplateLoadError(f'Escala {scale_code!r} referenciada em {path} não existe')

        node = ExamNode(
            tenant_id=tenant_id, template=template, parent=parent, order=order,
            code=code, path=path, label=entry.get('label', code),
            help_text=entry.get('help', '') or '',
            node_type=node_type, input_type=input_type,
            options=_normalize_options(entry.get('options')),
            lateralized=bool(entry.get('side')),
            unit=entry.get('unit', '') or '',
            scale=scale, axis=axis or code, active=True,
            breadcrumb=' › '.join(trail)[:400],
        )
        node.full_clean(exclude=['tenant'])
        node.save()
        counters[node_type] = counters.get(node_type, 0) + 1
        if children:
            # O eixo (raiz) não entra na trilha: ele já é o título da seção.
            child_trail = trail if parent is None else trail + (node.label,)
            _build_nodes(
                tenant_id, template, children, node, axis or code, path, scales, counters,
                child_trail,
            )


@transaction.atomic
def install_template(tenant_id, path, status=ExamTemplateStatus.PUBLISHED, make_default=True):
    """Instala (ou versiona) um roteiro no tenant, como roteiro da organização."""
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    code = _slug(data.get('code'))
    if not code:
        raise TemplateLoadError('Roteiro sem `code`')

    scales = {s.code: s for s in load_scales(tenant_id)}

    previous = (
        ExamTemplate.objects
        .filter(tenant_id=tenant_id, code=code, owner_membership__isnull=True)
        .order_by('-version')
        .first()
    )
    version = (previous.version + 1) if previous else 1

    template = ExamTemplate.objects.create(
        tenant_id=tenant_id, code=code, name=data.get('name', code),
        specialty=data.get('specialty', 'neurology'), version=version, status=status,
        description=data.get('description', '') or '',
        source_note=data.get('source_note', '') or '',
        owner_membership=None, based_on=previous, is_default=make_default,
    )

    counters = {}
    try:
        _build_nodes(tenant_id, template, data.get('nodes'), None, '', '', scales, counters)
    except ValidationError as exc:
        raise TemplateLoadError(str(exc)) from exc

    if make_default:
        # Só um roteiro padrão por especialidade — o anterior continua
        # existindo e legível, apenas deixa de ser o oferecido por omissão.
        ExamTemplate.objects.filter(
            tenant_id=tenant_id, specialty=template.specialty, owner_membership__isnull=True,
        ).exclude(pk=template.pk).update(is_default=False)

    return template, counters
