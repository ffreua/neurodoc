from django.db import models

from base.models import TenantModel

# Django's app loader only auto-imports `<app>.models`; chat models live in
# their own module (ai/chat_models.py, per the PRD's component naming) and
# must be re-exported here so they register under the `ai` app label.
from .chat_models import (  # noqa: F401,E402
    ChatMessage, ChatMessageRole, ChatMessageState, ChatSession, ChatSessionStatus,
)


class AIJobKind(models.TextChoices):
    ENCOUNTER_SUMMARY = 'encounter_summary', 'Resumo do atendimento'
    PATIENT_SUMMARY = 'patient_summary', 'Resumo do paciente'
    DIAGNOSTIC_SUPPORT = 'diagnostic_support', 'Apoio ao raciocínio diagnóstico'
    LAB_EXTRACTION = 'lab_extraction', 'Leitura de laudo laboratorial'
    REPORT_TRANSCRIPTION = 'report_transcription', 'Transcrição de laudo'
    PATIENT_REPORT = 'patient_report', 'Relatório do paciente'


#: Tarefas sem atendimento: a fonte é o paciente inteiro.
#:
#: A distinção importa na chave de idempotência. Para tarefa de
#: atendimento, a fonte é a versão daquele atendimento; aqui não há
#: atendimento, e o paciente sozinho não serve — dois relatórios do mesmo
#: paciente colidiriam na mesma chave, e o segundo pedido reaproveitaria a
#: linha do primeiro sem rodar. O que distingue um pedido do outro é a
#: finalidade e o texto que o médico escreveu, resumidos em `target_ref`.
PATIENT_SOURCED_KINDS = frozenset({AIJobKind.PATIENT_REPORT})


#: Tarefas cuja fonte é um documento anexado, e não o texto do atendimento.
#: A distinção decide duas coisas: a chave de idempotência (o PDF, não a
#: versão do prontuário) e a verificação de desatualização — editar a conduta
#: não invalida a leitura de um laudo.
DOCUMENT_SOURCED_KINDS = frozenset({
    AIJobKind.LAB_EXTRACTION, AIJobKind.REPORT_TRANSCRIPTION,
})


class AIJobStatus(models.TextChoices):
    DISABLED = 'disabled', 'Desativado'
    BLOCKED_PRIVACY = 'blocked_privacy', 'Bloqueado (privacidade)'
    QUEUED = 'queued', 'Na fila'
    RUNNING = 'running', 'Processando'
    SUCCEEDED = 'succeeded', 'Concluído'
    FAILED = 'failed', 'Falhou'
    CANCELLED = 'cancelled', 'Cancelado'
    STALE = 'stale', 'Desatualizado'


class AIReviewState(models.TextChoices):
    PENDING = 'pending', 'Pendente de revisão'
    ACCEPTED = 'accepted', 'Aceito'
    EDITED = 'edited', 'Editado'
    REJECTED = 'rejected', 'Rejeitado'


class AIJob(TenantModel):
    user = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='ai_jobs')
    membership = models.ForeignKey('tenancy.Membership', on_delete=models.PROTECT, related_name='ai_jobs')
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, null=True, blank=True, related_name='ai_jobs',
    )
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.PROTECT, null=True, blank=True, related_name='ai_jobs',
    )
    kind = models.CharField(max_length=40, choices=AIJobKind.choices)
    #: Alvo mais específico que o atendimento, quando existe — hoje o
    #: `{'exam_result_id': ...}` da leitura de laudo. Fica como referência e
    #: não como chave estrangeira porque o worker precisa reautorizar o
    #: acesso pelo tenant a cada execução: uma FK daria a impressão de que a
    #: linha já é um passe livre para o arquivo.
    target_ref = models.JSONField(default=dict, blank=True)
    source_version = models.PositiveBigIntegerField()
    source_hash = models.CharField(max_length=64, blank=True)
    purpose = models.CharField(max_length=255)
    policy_version = models.CharField(max_length=20, default='v1')
    status = models.CharField(max_length=20, choices=AIJobStatus.choices, default=AIJobStatus.QUEUED)
    status_detail = models.CharField(max_length=255, blank=True)
    #: Por que a saída foi recusada, em termos de **forma** — qual campo,
    #: que tipo veio, que tipo se esperava. Nunca o valor.
    #:
    #: A alternativa era guardar a resposta crua do modelo, e ela foi
    #: recusada: resolveria o diagnóstico criando um depósito novo de
    #: conteúdo clínico, com retenção, acesso e exportação próprios para
    #: pensar. O que falta quando uma extração é recusada não é o
    #: conteúdo — é a forma, e ela não identifica ninguém. Por isso este
    #: campo pode aparecer na tela e ir num pedido de suporte, enquanto a
    #: resposta crua não poderia.
    #:
    #: Vazio no sucesso e em toda falha que acontece antes do modelo
    #: responder (autorização, privacidade, prazo): ali o `status_detail`
    #: já diz tudo que há para dizer.
    failure_diagnostics = models.JSONField(default=dict, blank=True)
    limits = models.JSONField(default=dict, blank=True)
    task_id = models.CharField(max_length=100, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=150)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'idempotency_key'], name='ai_aijob_idempotency_uniq'),
        ]

    def __str__(self):
        return f'{self.kind} ({self.status})'


class AIArtifact(TenantModel):
    job = models.ForeignKey(AIJob, on_delete=models.PROTECT, related_name='artifacts')
    schema_version = models.CharField(max_length=20)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=20)
    source_refs = models.JSONField(default=list, blank=True)
    result = models.JSONField(default=dict, blank=True)
    review_state = models.CharField(max_length=20, choices=AIReviewState.choices, default=AIReviewState.PENDING)
    reviewer = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='superseded_by',
    )
    stale = models.BooleanField(default=False)

    def __str__(self):
        return f'artifact for job {self.job_id} ({self.review_state})'


class AIProviderSettings(TenantModel):
    """Provedor de IA da clínica, com a chave dela.

    A configuração era só de instalação: uma chave em variável de ambiente
    valendo para todas as clínicas. Isso serve a quem hospeda o sistema para
    si, e não a quem hospeda várias — cada clínica tem o próprio contrato
    com o provedor, a própria fatura e a própria decisão sobre para onde
    seus dados vão.

    A chave fica **cifrada** no banco (`base.crypto`), pelo mesmo motivo da
    chave de SMS: em texto claro, um dump entregaria a credencial de IA de
    todas as clínicas de uma vez.

    O modelo é escolhido de uma lista trazida do provedor, não digitado. Os
    identificadores mudam — o provedor aposenta o modelo e o nome que estava
    certo passa a dar erro no meio de um atendimento.
    """

    provider = models.CharField(max_length=40, default='openrouter')
    enabled = models.BooleanField(default=False)
    api_key_ciphertext = models.TextField(blank=True)
    api_key_metadata = models.JSONField(default=dict, blank=True)
    api_key_hint = models.CharField(max_length=40, blank=True)
    #: Endereço da API. Vazio usa o padrão do provedor; preenchido atende
    #: servidor próprio (Ollama, vLLM) e provedor fora do catálogo.
    base_url = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=200, blank=True)
    #: Modelos que o provedor respondeu na última consulta, para a lista da
    #: tela. Guardados porque consultar o provedor a cada abertura de tela
    #: deixaria a página refém da latência dele — e a lista muda em semanas,
    #: não em minutos.
    available_models = models.JSONField(default=list, blank=True)
    models_synced_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant'], name='ai_providersettings_tenant_uniq'),
        ]

    @property
    def has_api_key(self):
        return bool(self.api_key_ciphertext)

    @property
    def is_usable(self):
        """Ligada, com chave e com modelo escolhido.

        As três coisas juntas, porque faltando qualquer uma o pedido falha
        no provedor em vez de falhar aqui — e a falha lá chega ao médico
        como erro genérico no meio do atendimento.
        """
        return bool(self.enabled and self.api_key_ciphertext and self.model)

    def api_key(self):
        from base.crypto import decrypt_secret

        return decrypt_secret(self.api_key_ciphertext, self.api_key_metadata)

    def __str__(self):
        return f'IA {self.provider} ({"ativa" if self.enabled else "inativa"})'
