"""Catalog and validated upsert for the twelve cranial nerves, each with its
own identified item(s) — never a single undifferentiated field for all
nerves (11.1)."""
from django.core.exceptions import ValidationError

from .models import ExaminationDomain, ExaminationFinding, ExaminationState, Side

CRANIAL_NERVE_ITEMS = {
    'cn1_olfaction': 'I — Olfação',
    'cn2_visual_acuity': 'II — Acuidade visual',
    'cn2_visual_field': 'II — Campo visual',
    'cn2_fundoscopy': 'II — Fundoscopia',
    'cn3_4_6_ocular_motility': 'III/IV/VI — Motilidade ocular',
    'cn3_4_6_diplopia_nystagmus': 'III/IV/VI — Diplopia/nistagmo',
    'cn3_pupils': 'III — Pupilas',
    'cn5_facial_sensation': 'V — Sensibilidade facial',
    'cn5_mastication_motor': 'V — Motricidade mastigatória',
    'cn5_reflexes': 'V — Reflexos',
    'cn7_facial_motor': 'VII — Motricidade facial',
    'cn8_hearing': 'VIII — Audição',
    'cn8_vestibular': 'VIII — Vestibular',
    'cn9_10_voice_palate': 'IX/X — Voz e palato',
    'cn9_10_swallowing_reflex': 'IX/X — Deglutição/reflexos',
    'cn11_sternocleidomastoid_trapezius': 'XI — Esternocleidomastóideo/trapézio',
    'cn12_tongue': 'XII — Língua',
}

NOT_LATERALIZED_ITEMS = {
    'cn3_4_6_diplopia_nystagmus', 'cn9_10_voice_palate', 'cn9_10_swallowing_reflex',
}


def upsert_cranial_nerve_finding(
    context, encounter, item_code, side=Side.NOT_APPLICABLE, body_site='',
    state=ExaminationState.NOT_ASSESSED, qualifier='', note='',
):
    # Mensagens em português e nomeando o nervo como o roteiro o escreve —
    # ver o comentário equivalente em `examination.upsert_finding`.
    if item_code not in CRANIAL_NERVE_ITEMS:
        raise ValidationError(f'Item {item_code!r} não existe no exame dos nervos cranianos.')
    rotulo = CRANIAL_NERVE_ITEMS[item_code]
    lateralized = item_code not in NOT_LATERALIZED_ITEMS
    if not lateralized and side not in (Side.NOT_APPLICABLE, Side.BILATERAL):
        raise ValidationError(
            f'“{rotulo}” não é lateralizado: deixe o lado em branco ou marque bilateral.'
        )
    if lateralized and side == Side.NOT_APPLICABLE:
        raise ValidationError(
            f'Escolha o lado de “{rotulo}”: direito, esquerdo ou bilateral.'
        )
    finding, _ = ExaminationFinding.objects.update_or_create(
        tenant_id=context.tenant_id, encounter=encounter, item_code=item_code, side=side, body_site=body_site,
        defaults={
            'domain': ExaminationDomain.CRANIAL_NERVE, 'state': state,
            'qualifier': qualifier, 'note': note, 'numeric_value': None,
        },
    )
    return finding


def nerve_group_items(prefix):
    return {code: label for code, label in CRANIAL_NERVE_ITEMS.items() if code.startswith(prefix)}
