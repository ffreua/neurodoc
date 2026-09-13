"""O roteiro de exame que toda clínica recebe ao nascer.

O exame neurológico estruturado é o motivo de o produto existir para um
neurologista, e até aqui ele dependia de alguém lembrar de rodar
`manage.py install_exam_template` depois de criar a organização. Ninguém
lembra: a clínica entrava, atendia o primeiro paciente, abria o exame e
lia um aviso pedindo um comando de terminal que o dono do consultório não
tem como executar.

Provisionar é do sistema, não do operador. A instalação passou para o
mesmo ponto em que a organização nasce.
"""
import logging

from django.db import transaction

from .loader import DATA_DIR, TemplateLoadError, install_template
from .models import ExamTemplate, ExamTemplateStatus

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_FILE = DATA_DIR / 'neurologia.yaml'


def has_official_template(tenant_id):
    """A organização já tem roteiro publicado próprio (não de um médico)?"""
    return ExamTemplate.objects.filter(
        tenant_id=tenant_id,
        owner_membership__isnull=True,
        status=ExamTemplateStatus.PUBLISHED,
    ).exists()


def ensure_default_template(tenant_id, path=DEFAULT_TEMPLATE_FILE):
    """Instala o roteiro padrão se a clínica ainda não tiver um.

    Idempotente de propósito: reinstalar versiona (é o que `install_template`
    faz, e está certo para uma atualização deliberada), mas uma organização
    que já tem roteiro não deve ganhar uma versão nova só porque alguém
    rodou o provisionamento de novo.

    **Não derruba quem está entrando.** A falha aqui é de empacotamento — o
    YAML vem no repositório —, e uma clínica sem roteiro ainda é uma clínica
    utilizável: ela registra o exame em texto avulso e o roteiro pode ser
    instalado depois. Derrubar o cadastro inteiro por causa disso troca um
    problema pequeno por um intransponível.
    """
    if has_official_template(tenant_id):
        return None
    try:
        # Ponto de salvamento próprio: se a carga falhar no meio, o que ela
        # criou desaparece sem contaminar a transação de quem chamou.
        with transaction.atomic():
            template, _ = install_template(tenant_id, path)
    except (TemplateLoadError, OSError):
        logger.exception('Falha ao instalar o roteiro de exame no tenant %s', tenant_id)
        return None
    return template
