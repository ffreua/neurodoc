from django.db import models
from django.db.models import Q

from base.models import TenantModel


class DeliveryChannel(models.TextChoices):
    EMAIL = 'email', 'Email'
    SMS = 'sms', 'SMS'


class DeliveryStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACCEPTED = 'accepted', 'Accepted'
    DELIVERED = 'delivered', 'Delivered'
    UNKNOWN = 'unknown', 'Unknown'
    FAILED = 'failed', 'Failed'
    NO_CONTACT = 'no_contact', 'No contact'
    NEEDS_RECONCILIATION = 'needs_reconciliation', 'Needs reconciliation'


class DeliveryAttemptOutcome(models.TextChoices):
    ACCEPTED = 'accepted', 'Accepted'
    DELIVERED = 'delivered', 'Delivered'
    UNKNOWN = 'unknown', 'Unknown'
    FAILED = 'failed', 'Failed'


class Delivery(TenantModel):
    document = models.ForeignKey(
        'documents.MedicalDocument', on_delete=models.PROTECT, null=True, blank=True, related_name='deliveries',
    )
    appointment = models.ForeignKey(
        'scheduling.Appointment', on_delete=models.PROTECT, null=True, blank=True, related_name='deliveries',
    )
    contact = models.ForeignKey('patients.PatientContact', on_delete=models.PROTECT, related_name='deliveries')
    channel = models.CharField(max_length=20, choices=DeliveryChannel.choices)
    event_version = models.PositiveBigIntegerField()
    status = models.CharField(max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    provider_id = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=100)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'idempotency_key'], name='communications_delivery_idem_uniq'),
            models.CheckConstraint(
                condition=(
                    Q(document__isnull=False, appointment__isnull=True)
                    | Q(document__isnull=True, appointment__isnull=False)
                ),
                name='communications_delivery_single_target',
            ),
        ]

    def __str__(self):
        return f'{self.channel}:{self.contact_id} ({self.status})'


class DeliveryAttempt(TenantModel):
    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT, related_name='attempts')
    attempt_number = models.PositiveIntegerField()
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=DeliveryAttemptOutcome.choices)
    provider_code = models.CharField(max_length=100, blank=True)
    sanitized_error = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['delivery', 'attempt_number'], name='communications_deliveryattempt_unique',
            ),
        ]

    def __str__(self):
        return f'{self.delivery_id}#{self.attempt_number} ({self.outcome})'


class DocumentAccessToken(TenantModel):
    document = models.ForeignKey('documents.MedicalDocument', on_delete=models.PROTECT, related_name='access_tokens')
    contact = models.ForeignKey('patients.PatientContact', on_delete=models.PROTECT, related_name='+')
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_access_at = models.DateTimeField(null=True, blank=True)
    otp_hash = models.CharField(max_length=255, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['token_hash'], name='communications_accesstoken_hash_uniq'),
        ]

    def __str__(self):
        return f'token for document {self.document_id}'


class MessagingSettings(TenantModel):
    """Configuração de SMS da clínica, informada pelo gestor.

    A chave do provedor fica **no banco e cifrada** (`base.crypto`), não em
    variável de ambiente: quem a tem é o gestor da clínica, que a informa
    pela tela, e cada clínica tem a sua. Em texto claro, um dump do banco
    entregaria a chave de SMS de todas elas.

    `enabled` é um segundo interruptor, por clínica, além do
    `settings.SMS_ENABLED` global: a instalação pode ter o canal disponível
    e uma clínica específica preferir não usar.
    """

    provider = models.CharField(max_length=20, default='smsdev')
    sms_enabled = models.BooleanField(default=False)
    sms_api_key_ciphertext = models.TextField(blank=True)
    sms_api_key_metadata = models.JSONField(default=dict, blank=True)
    #: Só os últimos caracteres, para a tela mostrar que existe uma chave e
    #: permitir conferir que é a certa, sem exibi-la.
    sms_api_key_hint = models.CharField(max_length=40, blank=True)
    sms_sender_name = models.CharField(max_length=40, blank=True)
    updated_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant'], name='communications_messagingsettings_tenant_uniq'),
        ]

    @property
    def has_api_key(self):
        return bool(self.sms_api_key_ciphertext)

    def api_key(self):
        """Chave em claro, para a chamada ao provedor.

        Levanta `SecretUnavailable` quando não abre — e é isso que se quer:
        tratar como vazio faria o sistema chamar o SMSDEV com chave em
        branco e reportar erro do provedor em vez do erro real.
        """
        from base.crypto import decrypt_secret

        return decrypt_secret(self.sms_api_key_ciphertext, self.sms_api_key_metadata)

    def __str__(self):
        return f'SMS {self.provider} ({"ativo" if self.sms_enabled else "inativo"})'


class DoctorEmailSettings(TenantModel):
    """Remetente de e-mail de um médico, configurado pelo gestor.

    Por médico porque o e-mail que o paciente recebe deve vir do consultório
    de quem o atende — e numa clínica com vários médicos isso são vários
    remetentes. Sem configuração própria, o envio usa o remetente global da
    instalação.

    A senha do SMTP fica cifrada, pelo mesmo motivo da chave do SMS.
    """

    physician_membership = models.OneToOneField(
        'tenancy.Membership', on_delete=models.CASCADE, related_name='email_settings',
    )
    enabled = models.BooleanField(default=False)
    from_name = models.CharField(max_length=120, blank=True)
    from_email = models.EmailField(max_length=254, blank=True)
    reply_to = models.EmailField(max_length=254, blank=True)
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(null=True, blank=True)
    smtp_user = models.CharField(max_length=255, blank=True)
    smtp_password_ciphertext = models.TextField(blank=True)
    smtp_password_metadata = models.JSONField(default=dict, blank=True)
    smtp_password_hint = models.CharField(max_length=40, blank=True)
    use_tls = models.BooleanField(default=True)
    use_ssl = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        pass

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.use_tls and self.use_ssl:
            raise ValidationError({
                'use_ssl': 'TLS e SSL são alternativos: escolha um. '
                           'A porta 587 costuma usar TLS; a 465, SSL.',
            })
        if self.enabled and not self.from_email:
            raise ValidationError({'from_email': 'Informe o e-mail remetente.'})
        if self.enabled and self.smtp_host and not self.smtp_port:
            raise ValidationError({'smtp_port': 'Informe a porta do servidor SMTP.'})

    @property
    def has_password(self):
        return bool(self.smtp_password_ciphertext)

    @property
    def uses_own_server(self):
        """Se tem servidor próprio, ou só troca o endereço do remetente.

        As duas coisas são úteis: um médico pode querer só que o e-mail saia
        no nome dele, usando o servidor da instalação.
        """
        return bool(self.smtp_host)

    def smtp_password(self):
        from base.crypto import decrypt_secret

        return decrypt_secret(self.smtp_password_ciphertext, self.smtp_password_metadata)

    def sender_header(self):
        if self.from_name and self.from_email:
            return f'{self.from_name} <{self.from_email}>'
        return self.from_email

    def __str__(self):
        return f'e-mail de {self.physician_membership_id} ({self.from_email or "sem remetente"})'
