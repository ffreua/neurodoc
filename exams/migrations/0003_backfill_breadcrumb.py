"""Preenche a trilha legível dos nós já instalados.

O campo entrou depois de o roteiro já estar carregado nos tenants. Sem este
preenchimento, um achado registrado antes desta versão continuaria aparecendo
no grid sem a trilha dos grupos acima dele — e reinstalar o roteiro criaria
uma versão nova, deixando os achados antigos apontando para nós sem trilha.
"""
from django.db import migrations


def fill_breadcrumb(apps, schema_editor):
    ExamNode = apps.get_model('exams', 'ExamNode')

    by_id = {}
    for node in ExamNode.objects.all().only('id', 'parent_id', 'label', 'breadcrumb'):
        by_id[node.id] = node

    def trail(node):
        """Rótulos dos grupos acima do nó, sem o eixo (raiz) e sem ele mesmo."""
        parts = []
        current = by_id.get(node.parent_id) if node.parent_id else None
        while current is not None:
            parent = by_id.get(current.parent_id) if current.parent_id else None
            if parent is not None:  # o eixo é a raiz e não entra na trilha
                parts.append(current.label)
            current = parent
        return ' › '.join(reversed(parts))[:400]

    updates = []
    for node in by_id.values():
        value = trail(node)
        if node.breadcrumb != value:
            node.breadcrumb = value
            updates.append(node)
    if updates:
        ExamNode.objects.bulk_update(updates, ['breadcrumb'], batch_size=500)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0002_examnode_breadcrumb'),
    ]

    operations = [
        migrations.RunPython(fill_breadcrumb, noop),
    ]
