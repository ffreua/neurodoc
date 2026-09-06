"""Motor de roteiros de exame.

Um roteiro é uma **árvore** (`ExamNode` com `parent`), não uma lista: o
roteiro de exame neurológico usado como referência
(`docs/reference/roteiro-exame-neurologico.pdf`) chega a cinco níveis —
eixo → avaliação → grupo → item → variação. Um catálogo plano de itens não
comporta isso e foi o que deixou a tela de exame desconexa.

Três decisões estruturais:

1. **Especialidade é dado, não código.** Um roteiro inteiro é carregado de
   um arquivo YAML (`exams/data/*.yaml`). Neurologia é o primeiro; outra
   especialidade é outro arquivo, sem alterar modelo nem tela.
2. **A clínica publica, o médico personaliza.** Um roteiro com
   `owner_membership` nulo é o oficial da organização; um médico deriva o
   seu (`based_on`) e edita à vontade sem afetar os demais.
3. **O atendimento guarda qual roteiro e qual versão usou.** Um registro de
   2026 continua sendo lido com o roteiro de 2026, mesmo depois de o
   roteiro atual mudar — requisito de um prontuário, não conveniência.
"""
from django.core.exceptions import ValidationError
from django.db import models

from base.models import TenantModel


class Specialty(models.TextChoices):
    NEUROLOGY = 'neurology', 'Neurologia'
    GENERAL = 'general', 'Clínica geral'


class ExamTemplateStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    PUBLISHED = 'published', 'Publicado'
    RETIRED = 'retired', 'Aposentado'


class ExamNodeType(models.TextChoices):
    GROUP = 'group', 'Grupo'
    ITEM = 'item', 'Item'
    SCALE = 'scale', 'Escala'


class ExamInputType(models.TextChoices):
    STATE = 'state', 'Estado (não avaliado / normal / alterado)'
    CHOICE = 'choice', 'Escolha única'
    MULTICHOICE = 'multichoice', 'Múltipla escolha'
    NUMBER = 'number', 'Número'
    TEXT = 'text', 'Texto livre'
    BOOLEAN = 'boolean', 'Presente / ausente'


class ExamScale(TenantModel):
    """Escala funcional padronizada — Glasgow, MRC, MEEM, RASS, mRS…

    Vive fora da árvore de propósito: a mesma escala é usada por vários
    roteiros e por especialidades diferentes, e um nó apenas aponta para
    ela. É o bloco que permite "incluir escalas funcionais" sem editar o
    roteiro inteiro.
    """

    code = models.CharField(max_length=60)
    name = models.CharField(max_length=255)
    description = models.TextField(max_length=2000, blank=True)
    source_note = models.CharField(max_length=255, blank=True)
    min_score = models.IntegerField(null=True, blank=True)
    max_score = models.IntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'code'], name='exams_scale_tenant_code_uniq'),
        ]
        ordering = ['name']

    def __str__(self):
        return self.name


class ExamScaleItem(TenantModel):
    """Um eixo pontuável da escala (ex.: abertura ocular, 1 a 4 no Glasgow)."""

    scale = models.ForeignKey(ExamScale, on_delete=models.CASCADE, related_name='items')
    order = models.PositiveIntegerField(default=0)
    code = models.CharField(max_length=60)
    label = models.CharField(max_length=255)
    # [{"value": 4, "label": "Espontânea"}, ...] — pontuação explícita, nunca
    # inferida da ordem, para que uma escala com pontos não sequenciais
    # (ou invertidos, como a RASS) seja representável.
    options = models.JSONField(default=list)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'scale', 'code'], name='exams_scale_item_uniq'),
        ]
        ordering = ['order', 'code']

    def __str__(self):
        return f'{self.scale.code}/{self.code}'


class ExamTemplate(TenantModel):
    code = models.CharField(max_length=60)
    name = models.CharField(max_length=255)
    specialty = models.CharField(max_length=40, choices=Specialty.choices, default=Specialty.NEUROLOGY)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20, choices=ExamTemplateStatus.choices, default=ExamTemplateStatus.DRAFT,
    )
    description = models.TextField(max_length=2000, blank=True)
    source_note = models.CharField(max_length=255, blank=True)
    # Nulo = roteiro oficial da organização; preenchido = roteiro pessoal
    # daquele médico, derivado de um oficial.
    owner_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.CASCADE, null=True, blank=True, related_name='exam_templates',
    )
    based_on = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='derivatives',
    )
    is_default = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'code', 'version', 'owner_membership'],
                name='exams_template_version_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'specialty', 'status'], name='exams_template_lookup_idx'),
        ]
        ordering = ['name', '-version']

    @property
    def is_organization_template(self):
        return self.owner_membership_id is None

    def __str__(self):
        scope = 'organização' if self.is_organization_template else 'pessoal'
        return f'{self.name} v{self.version} ({scope})'


class ExamNode(TenantModel):
    template = models.ForeignKey(ExamTemplate, on_delete=models.CASCADE, related_name='nodes')
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='children',
    )
    order = models.PositiveIntegerField(default=0)
    code = models.CharField(max_length=60)
    # Caminho completo dentro do roteiro ("somatico.motricidade.tonus").
    # É ele que identifica o achado no atendimento, e não o id do nó: assim
    # um roteiro derivado registra o mesmo item com o mesmo identificador,
    # e dois atendimentos de roteiros diferentes continuam comparáveis.
    path = models.CharField(max_length=200)
    label = models.CharField(max_length=255)
    help_text = models.CharField(max_length=500, blank=True)
    node_type = models.CharField(max_length=20, choices=ExamNodeType.choices, default=ExamNodeType.ITEM)
    input_type = models.CharField(max_length=20, choices=ExamInputType.choices, blank=True)
    # [{"value": "ausente", "label": "Ausente"}, ...]
    options = models.JSONField(default=list, blank=True)
    lateralized = models.BooleanField(default=False)
    unit = models.CharField(max_length=20, blank=True)
    scale = models.ForeignKey(
        ExamScale, on_delete=models.PROTECT, null=True, blank=True, related_name='nodes',
    )
    # Eixo do roteiro a que o nó pertence, propagado da raiz — é o que a
    # tela usa para agrupar e o que vai para `ExaminationFinding.domain`.
    axis = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'template', 'path'], name='exams_node_path_uniq'),
        ]
        indexes = [
            models.Index(fields=['tenant', 'template', 'parent'], name='exams_node_tree_idx'),
        ]
        ordering = ['order', 'path']

    def clean(self):
        if self.node_type == ExamNodeType.ITEM and not self.input_type:
            raise ValidationError({'input_type': 'Um item precisa de um tipo de entrada'})
        if self.node_type == ExamNodeType.SCALE and self.scale_id is None:
            raise ValidationError({'scale': 'Um nó de escala precisa apontar para uma escala'})
        if self.input_type in (ExamInputType.CHOICE, ExamInputType.MULTICHOICE) and not self.options:
            raise ValidationError({'options': 'Escolha e múltipla escolha precisam de opções'})

    @property
    def records_value(self):
        return self.node_type in (ExamNodeType.ITEM, ExamNodeType.SCALE)

    def __str__(self):
        return f'{self.template_id}:{self.path}'
