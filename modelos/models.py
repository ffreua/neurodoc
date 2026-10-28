"""O modelo de documento escrito pelo médico.

**É do médico, e não da clínica** — liga ao usuário e não herda
`TenantModel`. O médico que atende em duas clínicas pede o mesmo
hemograma nas duas, e o cirurgião que montou a lista de materiais da
artrodese não deveria refazê-la a cada vínculo. É o desenho do bloco do
SNCR (`sncr/models.py`), pelo motivo de produto e não pelo regulatório:
modelo não carrega dado de paciente, e o que ele carrega é o jeito de
trabalhar de quem o escreveu.

A consequência que se aceita: a clínica não vê nem herda o modelo de quem
sai dela. Cada tela filtra por `autor=request.user`, e é isso que separa um
médico do outro — não o inquilino.

Os modelos **do sistema** não estão aqui: moram em `modelos/padrao.py`, em
código. Esta tabela só guarda o que um médico escreveu ou copiou.

**Nada aponta para cá.** O documento emitido guarda o conteúdo inteiro no
próprio `content_snapshot`, e o identificador do modelo como texto
(`content_snapshot['modelo']`). Apagar ou editar um modelo nunca muda documento
emitido, e por isso apagar é apagar mesmo, sem arquivamento.
"""

from django.conf import settings
from django.db import models

from base.models import TimestampedModel

from .estrutura import MAX_NOME, TIPOS


class ModeloDocumento(TimestampedModel):
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='modelos_de_documento',
    )
    tipo = models.CharField(max_length=20, choices=TIPOS)
    nome = models.CharField(max_length=MAX_NOME)
    #: Na forma de `modelos.estrutura.normalizar`. Nunca gravado sem passar
    #: por ela.
    conteudo = models.JSONField(default=dict, blank=True)
    #: O modelo do sistema de onde esta cópia saiu (`slug`), ou vazio.
    origem = models.CharField(max_length=80, blank=True)

    class Meta:
        verbose_name = 'modelo de documento'
        verbose_name_plural = 'modelos de documento'
        ordering = ['nome']
        indexes = [models.Index(fields=['autor', 'tipo'], name='modelos_autor_tipo_idx')]

    def __str__(self):
        return self.nome
