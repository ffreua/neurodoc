import uuid

from django.db import models


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    row_version = models.BigIntegerField(default=1)

    class Meta:
        abstract = True


class TenantModel(TimestampedModel):
    tenant = models.ForeignKey('tenancy.Tenant', on_delete=models.PROTECT)

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'id'],
                name='%(app_label)s_%(class)s_tenant_id_uniq',
            ),
        ]


class InstallationSettings(TimestampedModel):
    """As chaves da instalacao que se viram **sem deploy**.

    Nasceu de uma pergunta do proprietario durante a auditoria pre-deploy:
    por que autorizar apagamento de arquivo ou liberar um endereco de API
    exige editar `.env`, regerar o runtime e republicar? A resposta honesta
    e que nao exige -- e que o caminho por `.env` tem um defeito de
    seguranca proprio: **desligar demora**. Uma trava que so se solta com um
    ciclo de deploy nao serve de freio de emergencia, e freio de emergencia
    e exatamente o que essas duas chaves precisam ser.

    Por que uma linha so, e nao um par chave/valor generico: sao duas
    decisoes nomeadas, cada uma com significado proprio e com trilha
    propria. Uma tabela de `chave = texto` aceitaria `documents_gc_dry_run
    = 'talvez'` e so quebraria na madrugada de domingo.

    **O `.env` semeia, o banco decide.** As variaveis
    `AI_BASE_URL_ALLOWLIST` e `DOCUMENTS_GC_DRY_RUN` valem para criar esta
    linha na primeira vez; depois disso quem manda e o console. Mexer no
    `.env` de uma instalacao que ja rodou nao muda nada -- e a tela do
    console diz isso com todas as letras, porque uma regra dessas descoberta
    por tentativa custa uma madrugada.
    """

    #: Garante uma linha so: o `unique=True` num campo de valor fixo e o
    #: jeito de o banco recusar a segunda, em vez de a aplicacao lembrar.
    singleton = models.BooleanField(default=True, unique=True, editable=False)

    #: Um host por linha. Vazio = so os provedores do catalogo.
    ai_base_url_allowlist = models.TextField(blank=True)

    #: `True` conta e registra sem apagar. Ver `documents/tasks.py`.
    documents_gc_dry_run = models.BooleanField(default=True)

    #: Por que a coleta foi autorizada a apagar. Exigido ao desligar o
    #: ensaio, pela mesma razao do `status_note` da organizacao: "por que
    #: isto esta ligado?" um ano depois nao tem outra fonte.
    documents_gc_note = models.CharField(max_length=255, blank=True)

    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        verbose_name = 'configuração da instalação'
        verbose_name_plural = 'configurações da instalação'

    def __str__(self):
        return 'Configuração da instalação'

    @classmethod
    def carregar(cls):
        """A linha unica, criada a partir do `.env` na primeira vez.

        `get_or_create` e nao `get`: uma instalacao que sobe pela primeira
        vez nao tem a linha, e a tarefa semanal nao pode falhar por isso --
        ela cai no padrao seguro, que e o do `.env`.
        """
        from django.conf import settings

        linha, _ = cls.objects.get_or_create(
            singleton=True,
            defaults={
                'ai_base_url_allowlist': chr(10).join(
                    getattr(settings, 'AI_BASE_URL_ALLOWLIST', []) or []
                ),
                'documents_gc_dry_run': getattr(settings, 'DOCUMENTS_GC_DRY_RUN', True),
            },
        )
        return linha

    def hosts_de_ia(self):
        """A lista de permissao, normalizada."""
        return {
            linha.strip().lower().rstrip('/')
            for linha in (self.ai_base_url_allowlist or '').splitlines()
            if linha.strip()
        }
