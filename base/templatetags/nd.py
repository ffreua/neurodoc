"""Template filters that bind Django form widgets to Duralux classes.

Rendering forms field by field in every template would duplicate the same
markup 30 times; instead `partials/form_fields.html` renders any form with
the design system's control classes, and these filters decide which class a
given widget needs.
"""
from django import forms
from django import template

register = template.Library()

_CHECKBOX = (forms.CheckboxInput,)
_CHOICE_LIST = (forms.RadioSelect, forms.CheckboxSelectMultiple)
_SELECT = (forms.Select, forms.SelectMultiple, forms.NullBooleanSelect)


def _widget(field):
    return field.field.widget


@register.filter
def nd_is_checkbox(field):
    return isinstance(_widget(field), _CHECKBOX)


@register.filter
def nd_is_choice_list(field):
    # RadioSelect / CheckboxSelectMultiple render their own <ul>; a control
    # class on the outer widget would be applied to every input inside.
    return isinstance(_widget(field), _CHOICE_LIST)


@register.filter
def nd_field(field):
    """Render `field` with the Duralux class matching its widget type."""
    widget = _widget(field)
    if isinstance(widget, _CHECKBOX):
        css = 'form-check-input'
    elif isinstance(widget, _CHOICE_LIST):
        css = ''
    elif isinstance(widget, _SELECT):
        css = 'form-select'
    else:
        css = 'form-control'

    classes = ' '.join(part for part in (widget.attrs.get('class', ''), css) if part)
    if field.errors:
        classes = (classes + ' is-invalid').strip()
    if not classes:
        return field
    return field.as_widget(attrs={'class': classes})


# Every status value the product renders as a badge, mapped to the Duralux
# contextual colour. Unknown values fall back to the neutral tone rather
# than guessing a colour that could imply the wrong clinical meaning.
_BADGE_TONES = {
    # patients
    'active': 'success',
    'archived': 'secondary',
    # scheduling
    'scheduled': 'primary',
    'confirmed': 'info',
    'checked_in': 'warning',
    'in_progress': 'warning',
    'completed': 'success',
    'cancelled': 'danger',
    'no_show': 'danger',
    # clinical
    'draft': 'secondary',
    'finalized': 'success',
    'suspected': 'warning',
    'refuted': 'danger',
    'normal': 'success',
    'altered': 'warning',
    'not_assessed': 'secondary',
    'not_informed': 'secondary',
    'pending': 'warning',
    'accepted': 'success',
    'edited': 'info',
    'rejected': 'danger',
    # documents
    'quarantined': 'warning',
    'available': 'success',
    'ready_to_sign': 'info',
    'signing': 'warning',
    'issued': 'success',
    'failed': 'danger',
    'expired': 'secondary',
    'revoked': 'danger',
    # finance
    'partial': 'warning',
    'paid': 'success',
    # ai / reporting / capture
    'disabled': 'secondary',
    'blocked_privacy': 'danger',
    'queued': 'info',
    'running': 'warning',
    'succeeded': 'success',
    'stale': 'secondary',
    'ready': 'success',
    'approved': 'success',
    'retired': 'secondary',
    'paired': 'success',
    'open': 'primary',
    'closed': 'secondary',
    # communications
    'delivered': 'success',
    'unknown': 'secondary',
    'no_contact': 'warning',
    'needs_reconciliation': 'warning',
}


@register.filter
def nd_tone(value):
    """Duralux contextual colour for a model status value."""
    return _BADGE_TONES.get(str(value), 'secondary')


@register.filter
def nd_in_stage(cards, stage_id):
    """The subset of `cards` sitting in one CRM stage.

    Lets the board render as columns without a second query per stage: the
    queryset is iterated once and Django serves the rest from its own
    result cache.
    """
    wanted = str(stage_id)
    return [card for card in cards if str(card.stage_id) == wanted]


@register.filter
def nd_get(mapping, key):
    """Acesso por chave dinâmica — o template do Django não tem `d[k]`."""
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def nd_exam_sides(node):
    """Lados a renderizar para um item do roteiro.

    Item lateralizado rende duas colunas (esquerdo e direito), que viram
    duas linhas distintas de achado; os demais rendem uma só.
    """
    if getattr(node, 'lateralized', False):
        return [('left', 'Esquerdo'), ('right', 'Direito')]
    return [('not_applicable', '')]


@register.filter
def nd_exam_field(node, side):
    """Nome do campo do item no formulário — espelha `exams.recording.field_name`."""
    return f'no__{node.path}__{side}'


@register.filter
def nd_json(value):
    """Serializa para uso em atributo `data-*` — o JS da tela lê de volta."""
    import json

    from django.utils.html import escape

    return escape(json.dumps(value or [], ensure_ascii=False))


@register.filter
def nd_scale_value(finding, item_code):
    """Valor já registrado de um item de escala, como texto, para o `selected`."""
    if not finding:
        return ''
    scores = (getattr(finding, 'value_json', None) or {}).get('scores') or {}
    value = scores.get(item_code)
    return '' if value is None else str(value)
