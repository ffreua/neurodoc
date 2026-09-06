"""Escolha do roteiro e montagem da árvore para a tela.

A regra de qual roteiro vale foi decidida com o produto: a organização
publica os oficiais e cada médico pode derivar o seu. Então, para um
médico, vale o roteiro pessoal dele quando existir; caso contrário, o
padrão da organização.
"""
from .models import ExamNode, ExamNodeType, ExamTemplate, ExamTemplateStatus, Specialty


def resolve_template(tenant_id, membership_id=None, specialty=Specialty.NEUROLOGY):
    """Roteiro em vigor: o pessoal do médico, senão o padrão da organização."""
    published = ExamTemplate.objects.filter(
        tenant_id=tenant_id, specialty=specialty, status=ExamTemplateStatus.PUBLISHED,
    )
    if membership_id is not None:
        personal = (
            published.filter(owner_membership_id=membership_id).order_by('-version').first()
        )
        if personal is not None:
            return personal
    return (
        published.filter(owner_membership__isnull=True, is_default=True)
        .order_by('-version').first()
        or published.filter(owner_membership__isnull=True).order_by('-version').first()
    )


def _render_value(node, findings_by_key):
    """Valores já registrados para um nó, indexados por lado.

    Devolve sempre um dicionário lado -> achado, porque um item lateralizado
    guarda esquerdo e direito como duas linhas distintas.
    """
    return {
        side: finding
        for (path, side), finding in findings_by_key.items()
        if path == node.path
    }


def build_tree(template, findings=()):
    """Árvore pronta para a tela, com os achados já anexados a cada item.

    Uma consulta só para os nós e uma passada em memória: o roteiro tem
    quase 400 nós e montar isso com uma consulta por nível deixaria a tela
    do atendimento lenta justamente onde ela é mais usada.
    """
    if template is None:
        return []

    findings_by_key = {
        (finding.item_code, finding.side): finding for finding in findings
    }

    nodes = list(
        ExamNode.objects
        .filter(template=template, active=True)
        .select_related('scale')
        .prefetch_related('scale__items')
        .order_by('order', 'path')
    )

    wrapped = {}
    for node in nodes:
        wrapped[node.id] = {
            'node': node,
            'children': [],
            'values': _render_value(node, findings_by_key),
            'is_group': node.node_type == ExamNodeType.GROUP,
            'filled': 0,
        }

    roots = []
    for node in nodes:
        entry = wrapped[node.id]
        if node.parent_id and node.parent_id in wrapped:
            wrapped[node.parent_id]['children'].append(entry)
        else:
            roots.append(entry)

    def count(entry):
        total = len(entry['values'])
        for child in entry['children']:
            total += count(child)
        entry['filled'] = total
        return total

    for root in roots:
        count(root)
    return roots
