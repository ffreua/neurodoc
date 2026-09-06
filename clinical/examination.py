"""Item catalogs and validated upsert for the non-cranial-nerve exam domains.

Each catalog entry documents whether the item is lateralized (has a
meaningful left/right side) so the service can reject a side that does not
apply, and any item-specific qualifier vocabulary (e.g. the plantar
response, which is never just "normal"/"altered").
"""
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import ExaminationDomain, ExaminationFinding, ExaminationState, Side

COGNITIVE_ITEMS = {
    'consciousness': 'Estado de consciência',
    'orientation': 'Orientação',
    'language': 'Linguagem',
    'attention': 'Atenção',
    'memory': 'Memória',
    'executive_function': 'Funções executivas',
    'praxis_gnosis': 'Praxia/gnosia',
}

STRENGTH_ITEMS = {
    'shoulder_abduction': 'Abdução do ombro',
    'elbow_flexion': 'Flexão do cotovelo',
    'elbow_extension': 'Extensão do cotovelo',
    'wrist_extension': 'Extensão do punho',
    'finger_flexion': 'Flexão dos dedos',
    'hip_flexion': 'Flexão do quadril',
    'knee_extension': 'Extensão do joelho',
    'knee_flexion': 'Flexão do joelho',
    'ankle_dorsiflexion': 'Dorsiflexão do tornozelo',
    'ankle_plantarflexion': 'Flexão plantar do tornozelo',
}

TONE_ITEMS = {
    'upper_limb': 'Tônus — membro superior',
    'lower_limb': 'Tônus — membro inferior',
}

SENSORY_SUPERFICIAL_ITEMS = {
    'tactile': 'Tátil',
    'pain': 'Dolorosa',
    'thermal': 'Térmica',
}

SENSORY_DEEP_ITEMS = {
    'vibratory': 'Vibratória',
    'proprioceptive': 'Proprioceptiva',
}

REFLEX_MYOTATIC_ITEMS = {
    'biceps': 'Bicipital',
    'triceps': 'Tricipital',
    'brachioradialis': 'Braquiorradial',
    'patellar': 'Patelar',
    'achilles': 'Aquileu',
    'clonus': 'Clônus',
}

REFLEX_CUTANEOUS_ITEMS = {
    'plantar': 'Cutâneo-plantar',
    'abdominal': 'Cutâneo-abdominal',
}
PLANTAR_QUALIFIERS = {'flexor', 'extensor', 'indifferent'}

COORDINATION_AXIAL_ITEMS = {
    'sitting_balance': 'Equilíbrio sentado',
    'standing_balance': 'Equilíbrio em pé',
    'trunk_control': 'Controle de tronco',
}

COORDINATION_APPENDICULAR_ITEMS = {
    'finger_nose': 'Índex-nariz',
    'heel_knee': 'Calcanhar-joelho',
    'diadochokinesia': 'Diadococinesia',
}

GAIT_ITEMS = {
    'base': 'Base',
    'pattern': 'Padrão de marcha',
    'tandem': 'Marcha em tandem',
    'romberg': 'Romberg',
    'assistance': 'Auxílio necessário',
}

NOT_LATERALIZED_DOMAINS = {ExaminationDomain.COGNITIVE, ExaminationDomain.GAIT}
NOT_LATERALIZED_ITEMS = {'sitting_balance', 'standing_balance', 'trunk_control'}

CATALOG_BY_DOMAIN = {
    ExaminationDomain.COGNITIVE: COGNITIVE_ITEMS,
    ExaminationDomain.STRENGTH: STRENGTH_ITEMS,
    ExaminationDomain.TONE: TONE_ITEMS,
    ExaminationDomain.SENSORY_SUPERFICIAL: SENSORY_SUPERFICIAL_ITEMS,
    ExaminationDomain.SENSORY_DEEP: SENSORY_DEEP_ITEMS,
    ExaminationDomain.REFLEX_MYOTATIC: REFLEX_MYOTATIC_ITEMS,
    ExaminationDomain.REFLEX_CUTANEOUS: REFLEX_CUTANEOUS_ITEMS,
    ExaminationDomain.COORDINATION_AXIAL: COORDINATION_AXIAL_ITEMS,
    ExaminationDomain.COORDINATION_APPENDICULAR: COORDINATION_APPENDICULAR_ITEMS,
    ExaminationDomain.GAIT: GAIT_ITEMS,
}


def upsert_finding(
    context, encounter, domain, item_code, side=Side.NOT_APPLICABLE, body_site='',
    state=ExaminationState.NOT_ASSESSED, numeric_value=None, qualifier='', note='',
):
    catalog = CATALOG_BY_DOMAIN.get(domain)
    if catalog is None or item_code not in catalog:
        raise ValidationError(f'Unknown item {item_code!r} for domain {domain!r}')
    lateralized = domain not in NOT_LATERALIZED_DOMAINS and item_code not in NOT_LATERALIZED_ITEMS
    if not lateralized and side not in (Side.NOT_APPLICABLE, Side.BILATERAL):
        raise ValidationError(f'{item_code} is not lateralized')
    if lateralized and side == Side.NOT_APPLICABLE:
        raise ValidationError(f'{item_code} requires a side')
    if domain == ExaminationDomain.STRENGTH and numeric_value is not None:
        if numeric_value not in (0, 1, 2, 3, 4, 5):
            raise ValidationError('Strength grade must be an integer 0-5, no arbitrary fractions')
    if item_code == 'plantar' and state in (ExaminationState.NORMAL, ExaminationState.ALTERED):
        if qualifier not in PLANTAR_QUALIFIERS:
            raise ValidationError('Plantar response requires a flexor/extensor/indifferent qualifier')

    finding, _ = ExaminationFinding.objects.update_or_create(
        tenant_id=context.tenant_id, encounter=encounter, item_code=item_code, side=side, body_site=body_site,
        defaults={
            'domain': domain, 'state': state, 'numeric_value': numeric_value,
            'qualifier': qualifier, 'note': note,
        },
    )
    return finding


def mark_section_normal(context, encounter, domain, actor_side_map):
    """Explicit, deliberate 'normal in every item of this section' action.

    Never triggered implicitly and never pre-selected; the caller must pass
    the exact set of (item_code, side) pairs the clinician chose to mark, so
    nothing beyond what was reviewed becomes 'normal'.
    """
    created = []
    for item_code, side in actor_side_map:
        created.append(upsert_finding(context, encounter, domain, item_code, side, state=ExaminationState.NORMAL))
    return created


DOMAIN_LABELS = {
    # eixos do roteiro estruturado
    ExaminationDomain.AXIS_CONSCIOUSNESS: 'Nível de consciência',
    ExaminationDomain.AXIS_COGNITIVE: 'Cognitivo',
    ExaminationDomain.AXIS_SOMATIC: 'Somático',
    ExaminationDomain.AXIS_CRANIAL_NERVES: 'Nervos cranianos',
    # catálogo legado
    ExaminationDomain.COGNITIVE: 'Cognitivo (avulso)',
    ExaminationDomain.STRENGTH: 'Força',
    ExaminationDomain.TONE: 'Tônus',
    ExaminationDomain.SENSORY_SUPERFICIAL: 'Sensibilidade superficial',
    ExaminationDomain.SENSORY_DEEP: 'Sensibilidade profunda',
    ExaminationDomain.REFLEX_MYOTATIC: 'Reflexos miotáticos',
    ExaminationDomain.REFLEX_CUTANEOUS: 'Reflexos cutâneos',
    ExaminationDomain.COORDINATION_APPENDICULAR: 'Coordenação apendicular',
    ExaminationDomain.COORDINATION_AXIAL: 'Coordenação axial',
    ExaminationDomain.GAIT: 'Marcha e equilíbrio',
    ExaminationDomain.CRANIAL_NERVE: 'Nervos cranianos',
}

# Ordem de apresentação do exame na tela, do geral para o focal — a mesma
# sequência em que o exame é feito à beira do leito.
DOMAIN_ORDER = [
    ExaminationDomain.AXIS_CONSCIOUSNESS,
    ExaminationDomain.AXIS_COGNITIVE,
    ExaminationDomain.AXIS_SOMATIC,
    ExaminationDomain.AXIS_CRANIAL_NERVES,
    ExaminationDomain.COGNITIVE,
    ExaminationDomain.CRANIAL_NERVE,
    ExaminationDomain.STRENGTH,
    ExaminationDomain.TONE,
    ExaminationDomain.REFLEX_MYOTATIC,
    ExaminationDomain.REFLEX_CUTANEOUS,
    ExaminationDomain.SENSORY_SUPERFICIAL,
    ExaminationDomain.SENSORY_DEEP,
    ExaminationDomain.COORDINATION_APPENDICULAR,
    ExaminationDomain.COORDINATION_AXIAL,
    ExaminationDomain.GAIT,
]


def item_label(domain, item_code):
    """Rótulo em português de um item, para a tela não mostrar o código cru."""
    from .cranial_nerves import CRANIAL_NERVE_ITEMS

    if domain == ExaminationDomain.CRANIAL_NERVE:
        return CRANIAL_NERVE_ITEMS.get(item_code, item_code)
    return CATALOG_BY_DOMAIN.get(domain, {}).get(item_code, item_code)


def grouped_item_choices():
    """Escolhas agrupadas por domínio para um <select> com <optgroup>.

    O valor carrega domínio e item (`dominio:item`) porque o mesmo código de
    item pode existir em domínios diferentes, e a tela não deve obrigar
    ninguém a digitar `sensory_superficial` à mão.
    """
    from .cranial_nerves import CRANIAL_NERVE_ITEMS

    groups = []
    for domain in DOMAIN_ORDER:
        if domain == ExaminationDomain.CRANIAL_NERVE:
            catalog = CRANIAL_NERVE_ITEMS
        else:
            catalog = CATALOG_BY_DOMAIN.get(domain, {})
        options = [(f'{domain}:{code}', label) for code, label in catalog.items()]
        if options:
            groups.append((DOMAIN_LABELS[domain], options))
    return groups


def is_lateralized(domain, item_code):
    from .cranial_nerves import CRANIAL_NERVE_ITEMS, NOT_LATERALIZED_ITEMS as CN_NOT_LATERALIZED

    if domain == ExaminationDomain.CRANIAL_NERVE:
        return item_code in CRANIAL_NERVE_ITEMS and item_code not in CN_NOT_LATERALIZED
    return domain not in NOT_LATERALIZED_DOMAINS and item_code not in NOT_LATERALIZED_ITEMS


def group_findings_by_domain(findings):
    """Agrupa os achados por domínio na ordem de exame, com rótulo legível."""
    buckets = {}
    for finding in findings:
        # Rótulo legível anexado ao próprio achado: a tela nunca deve exibir
        # o identificador cru (`cn3_4_6_ocular_motility` no catálogo antigo,
        # `somatico.motricidade.manobras_deficitarias.bracos_estendidos` no
        # roteiro). Quando o achado vem do roteiro, o nó já traz o rótulo e a
        # trilha dos grupos acima dele.
        node = finding.template_node
        if node is not None:
            finding.label = node.label
            finding.breadcrumb = node.breadcrumb
        else:
            finding.label = item_label(finding.domain, finding.item_code)
            finding.breadcrumb = ''
        buckets.setdefault(finding.domain, []).append(finding)
    ordered = []
    for domain in DOMAIN_ORDER:
        items = buckets.pop(domain, [])
        if items:
            ordered.append({'domain': domain, 'label': DOMAIN_LABELS[domain], 'findings': items})
    for domain, items in buckets.items():
        ordered.append({'domain': domain, 'label': DOMAIN_LABELS.get(domain, domain), 'findings': items})
    return ordered
