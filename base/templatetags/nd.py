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


# Tom neutro do sistema. **Não** é `secondary`: apesar de a classe
# `bg-soft-secondary` existir no CSS do tema, ela não define fundo algum
# (medido: `rgba(0, 0, 0, 0)`), então todo crachá neutro aparecia como texto
# solto e a informação de que aquilo era um estado se perdia. `bg-soft-dark`
# é o cinza claro de verdade do tema.
_NEUTRAL_TONE = 'dark'

# Cada valor de estado que o produto mostra como crachá, no tom contextual do
# Duralux. Valor desconhecido cai no tom neutro em vez de receber uma cor
# adivinhada, que poderia sugerir a gravidade errada.
_BADGE_TONES = {
    # patients
    'active': 'success',
    'archived': 'dark',
    # scheduling
    'scheduled': 'primary',
    'confirmed': 'info',
    'checked_in': 'warning',
    'in_progress': 'warning',
    'completed': 'success',
    'cancelled': 'danger',
    'no_show': 'danger',
    # clinical
    'draft': 'dark',
    'finalized': 'success',
    'suspected': 'warning',
    'refuted': 'danger',
    'normal': 'success',
    'altered': 'warning',
    # medicações em uso
    'in_use': 'success',
    'suspended': 'warning',
    'finished': 'dark',
    # resultado laboratorial: fora da faixa pede atenção, não é falha do
    # sistema — `danger` fica reservado para erro de verdade.
    'low': 'warning',
    'high': 'warning',
    'abnormal': 'warning',
    'no_reference': 'dark',
    'blocked': 'danger',
    'not_assessed': 'dark',
    'not_informed': 'dark',
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
    'expired': 'dark',
    'revoked': 'danger',
    # finance
    'partial': 'warning',
    'paid': 'success',
    # ai / reporting / capture
    'disabled': 'dark',
    'blocked_privacy': 'danger',
    'queued': 'info',
    'running': 'warning',
    'succeeded': 'success',
    'stale': 'dark',
    'ready': 'success',
    'approved': 'success',
    'retired': 'dark',
    'paired': 'success',
    'open': 'primary',
    'closed': 'dark',
    # communications
    'delivered': 'success',
    'unknown': 'dark',
    'no_contact': 'warning',
    # Canal indisponivel e `danger` e nao `warning`: diferente de
    # paciente sem telefone, aqui nao ha nada que a clinica possa
    # cadastrar -- o envio esta quebrado ate alguem configurar.
    'channel_unavailable': 'danger',
    'needs_reconciliation': 'warning',
}


@register.filter
def nd_tone(value):
    """Duralux contextual colour for a model status value."""
    return _BADGE_TONES.get(str(value), _NEUTRAL_TONE)


@register.filter
def nd_role(value):
    """Nome do papel em português.

    `Membership.roles` é um `ArrayField` de strings, então o template recebe
    `owner`, `secretary` — e não o rótulo do `TextChoices`, que só existe
    para campo com `choices`. Sem isto a tela da equipe mostra o nome
    interno do papel para quem está concedendo o papel.
    """
    from tenancy.models import Role

    return dict(Role.choices).get(str(value), str(value))


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


@register.filter
def nd_confirmation_contacts(patient):
    """Telefone e e-mail utilizáveis deste paciente, de contatos diferentes.

    A agenda lia o **primeiro** contato e tirava dele o telefone e o
    e-mail. Quando o primeiro contato tinha só telefone — que é o caso do
    pré-cadastro feito ao telefone —, o botão "Enviar e-mail" nunca
    aparecia, ainda que um segundo contato tivesse e-mail cadastrado. O
    servidor aceitaria o envio: `communications.services.confirmation_contacts`
    varre todos os contatos. Era a tela discordando do que o sistema faz.

    A regra aqui é a mesma daquela função — contato com validade vencida
    não conta — e a busca é independente por canal, porque o telefone pode
    estar num contato e o e-mail em outro.
    """
    from django.utils import timezone

    agora = timezone.now()
    phone = email = ''
    for contact in patient.contacts.all():
        if contact.valid_until is not None and contact.valid_until <= agora:
            continue
        if not phone and contact.phone:
            phone = contact.phone
        if not email and contact.email:
            email = contact.email
        if phone and email:
            break
    return {'phone': phone, 'email': email}


@register.filter
def nd_hidden_errors(form):
    """Erros dos campos escondidos, achatados numa lista.

    Campo escondido e renderizado como `{{ field }}` e mais nada, entao um
    erro nele nao aparece em lugar nenhum: o formulario volta recusado sem
    dizer por que. Aconteceu com `contract_version` -- quem enviava o
    cadastro depois de o contrato ter mudado via a mesma tela de novo, sem
    explicacao e sem nada para corrigir.

    Filtro, e nao laco no template, porque o template precisa saber se ha
    **algum** erro antes de abrir a caixa de aviso -- senao a caixa nasce
    vazia toda vez que o formulario e desenhado.
    """
    erros = []
    for field in form.hidden_fields():
        erros.extend(field.errors)
    return erros


@register.filter
def nd_na_lista(nome, lista):
    """O campo está nesta lista de nomes separados por vírgula?

    Existe porque `form_fields.html` passou a precisar mover **dois**
    campos para o meio do formulário -- a caixa de aceite do contrato e a
    declaração de poderes --, e a comparação direta `field.name != somente`
    só dava conta de um. Comparar contra uma string com vírgulas pelo
    operador `in` do template pegaria `accept` dentro de
    `accept_contract`; dividir de verdade, não.
    """
    if not lista:
        return False
    return nome in [parte.strip() for parte in str(lista).split(',')]


@register.filter
def nd_idade(patient, referencia=None):
    """A idade do paciente para pôr ao lado do nome, ou vazio.

    `referencia` é a data em que se quer a idade. No prontuário é a do
    atendimento, e não a de hoje: quem relê a consulta de 2019 de uma
    criança precisa saber que ela tinha 4 anos ali, não 10 — a dose, a
    escala e o diagnóstico diferencial foram escolhidos para os 4.

    Abaixo de um ano sai em meses (a idade em anos seria "0", que não diz
    nada), e o ano de nascimento estimado sai com "~": é o cadastro que
    não tem a data, e a tela não pode fingir que tem. Vazio quando não há
    nem uma coisa nem outra — quem desenha decide como mostrar a ausência.
    """
    from datetime import datetime

    from django.utils import timezone

    from patients.observations import age_at

    if patient is None:
        return ''
    if isinstance(referencia, datetime):
        referencia = timezone.localtime(referencia).date() if timezone.is_aware(referencia) else referencia.date()
    referencia = referencia or timezone.localdate()
    nascimento = getattr(patient, 'birth_date', None)
    if nascimento:
        if nascimento > referencia:
            return ''
        anos = age_at(nascimento, referencia)
        if anos >= 1:
            return f'{anos} ano{"s" if anos != 1 else ""}'
        meses = (referencia.year - nascimento.year) * 12 + referencia.month - nascimento.month
        if referencia.day < nascimento.day:
            meses -= 1
        meses = max(meses, 0)
        return f'{meses} {"mês" if meses == 1 else "meses"}'
    estimado = getattr(patient, 'estimated_birth_year', None)
    if estimado and estimado <= referencia.year:
        return f'~{referencia.year - estimado} anos'
    return ''
